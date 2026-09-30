"""Domain exceptions. Each maps to an HTTP status and a stable, machine-readable error code."""


class ParkFinderError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class InvalidRequestError(ParkFinderError):
    status_code = 422
    code = "invalid_request"


class NotFoundError(ParkFinderError):
    status_code = 404
    code = "not_found"


class CityNotFoundError(NotFoundError):
    code = "city_not_found"


class UpstreamError(ParkFinderError):
    """A data provider failed (bad status, malformed payload, connection error)."""

    status_code = 502
    code = "upstream_error"


class UpstreamTimeoutError(UpstreamError):
    status_code = 504
    code = "upstream_timeout"


class UpstreamRateLimitedError(UpstreamError):
    status_code = 503
    code = "upstream_rate_limited"


class ServiceUnavailableError(ParkFinderError):
    """No trustworthy data could be produced (provider down and no fallback data)."""

    status_code = 503
    code = "service_unavailable"
