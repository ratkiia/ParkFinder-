"""FastAPI application factory.

Run locally:  ``uvicorn app.main:app --reload`` (from the ``backend`` folder).
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.cache import TTLCache
from app.config import Settings, get_settings
from app.errors import ParkFinderError
from app.logging_config import configure_logging
from app.providers.nominatim import NominatimGeocoder
from app.providers.overpass import OverpassParkProvider
from app.providers.sample import SampleParkProvider
from app.rate_limit import MinIntervalLimiter, TokenBucketLimiter
from app.request_context import REQUEST_ID_HEADER, request_id_var, resolve_request_id
from app.services.park_service import ParkService

logger = logging.getLogger("parkfinder")
access_logger = logging.getLogger("parkfinder.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _error(status: int, code: str, message: str, *, details: list[dict] | None = None,
           retry_after: float | None = None) -> JSONResponse:
    headers = {"Retry-After": str(max(1, round(retry_after)))} if retry_after is not None else None
    # request_id lets a user or support engineer find the matching log lines.
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


def build_park_service(settings: Settings, client: httpx.AsyncClient) -> ParkService:
    return ParkService(
        settings=settings,
        geocoder=NominatimGeocoder(client, settings, MinIntervalLimiter(settings.nominatim_min_interval_seconds)),
        primary=OverpassParkProvider(client, settings),
        sample=SampleParkProvider(settings.sample_data_path),
        cache=TTLCache(max_entries=settings.cache_max_entries, default_ttl=settings.cache_ttl_seconds),
    )


def create_app(settings: Settings | None = None, *, park_service: ParkService | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if park_service is not None:  # injected (tests)
            app.state.park_service = park_service
            yield
            return
        timeout = httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout)
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        ) as client:
            app.state.park_service = build_park_service(settings, client)
            yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Find US city parks. Data © OpenStreetMap contributors.",
        lifespan=lifespan,
    )

    limiter = TokenBucketLimiter(rate_per_minute=settings.rate_limit_per_minute, burst=settings.rate_limit_burst)

    @app.middleware("http")
    async def observability_and_rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Assign a request id, enforce the rate limit, add security headers and write the access log."""
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        # Keyed on the direct peer address. Behind a trusted proxy, derive it from X-Forwarded-For instead.
        client_ip = request.client.host if request.client else "unknown"
        rate_limited = False
        try:
            if request.url.path.startswith("/api/v1") and request.method != "OPTIONS":
                allowed, retry_after = limiter.check(client_ip)
                if not allowed:
                    rate_limited = True
                    response = _error(429, "rate_limited", "Too many requests. Please slow down.",
                                      retry_after=retry_after)
            if not rate_limited:
                try:
                    response = await call_next(request)
                except Exception:  # noqa: BLE001 - last-resort guard so every request is answered and logged
                    logger.exception("Unhandled error", extra={"event": {"event": "unhandled_error"}})
                    response = _error(500, "internal_error", "An unexpected error occurred. Please try again later.")

            response.headers[REQUEST_ID_HEADER] = request_id
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)

            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            status = response.status_code
            level = (
                logging.DEBUG if request.url.path == "/api/health"
                else logging.ERROR if status >= 500
                else logging.WARNING if status >= 400
                else logging.INFO
            )
            access_logger.log(
                level,
                "%s %s -> %d (%.1f ms)", request.method, request.url.path, status, duration_ms,
                extra={"event": {
                    "event": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query[:300],
                    "status": status,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                    "user_agent": request.headers.get("user-agent", "")[:200],
                    "rate_limited": rate_limited,
                }},
            )
            return response
        finally:
            request_id_var.reset(token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=["Retry-After", REQUEST_ID_HEADER],
        max_age=600,
    )

    @app.exception_handler(ParkFinderError)
    async def handle_domain_error(_: Request, exc: ParkFinderError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, retry_after=exc.retry_after)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Echo only the location and message, never the raw input.
        details = [{"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "")}
                   for e in exc.errors()]
        return _error(422, "validation_error", "The request parameters are invalid.", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "internal_error", "An unexpected error occurred. Please try again later.")

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.version}

    app.include_router(router)
    return app


app = create_app()
