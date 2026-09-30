"""Orchestrates geocoding, park lookup, caching and graceful degradation.

Degradation policy:
* Primary provider (OpenStreetMap) fails -> serve local sample data for the same area,
  flagged ``degraded=True`` with a warning.
* Nothing trustworthy to show -> raise ``ServiceUnavailableError`` (HTTP 503) rather than
  claiming "no parks here", which could be false.
"""

import logging
import re
from typing import Any

from app.cache import TTLCache
from app.config import Settings
from app.errors import CityNotFoundError, NotFoundError, ServiceUnavailableError, UpstreamError
from app.geo import BBox, dedupe_parks
from app.models import Park, ParksResponse, ResolvedArea
from app.providers.base import GeocodedCity, Geocoder, ParkProvider
from app.providers.sample import SampleParkProvider

logger = logging.getLogger("parkfinder.service")

_WHITESPACE = re.compile(r"\s+")


def normalize_city_query(city: str) -> str:
    return _WHITESPACE.sub(" ", city).strip(" ,")


class ParkService:
    def __init__(
        self,
        *,
        settings: Settings,
        geocoder: Geocoder,
        primary: ParkProvider,
        sample: SampleParkProvider,
        cache: TTLCache[Any],
    ) -> None:
        self._settings = settings
        self._geocoder = geocoder
        self._primary = primary
        self._sample = sample
        self._cache = cache

    # ------------------------------------------------------------------ public API

    async def search_by_city(self, city: str) -> ParksResponse:
        query = normalize_city_query(city)
        try:
            place: GeocodedCity = await self._cache.get_or_set(
                f"geo:{query.lower()}",
                lambda: self._geocoder.geocode_city(query),
                ttl=self._settings.geocode_cache_ttl_seconds,
            )
        except CityNotFoundError:
            parks = await self._sample.parks_matching_city(query)
            if parks:
                return self._logged("city", query, parks, sources=["sample"], warnings=[
                    f"'{query}' was not found by the geocoder; showing matching sample data."
                ])
            raise
        except UpstreamError as exc:
            logger.warning(
                "Geocoding failed for %r: %s", query, exc.message,
                extra={"event": {"event": "provider_failure", "provider": "nominatim", "error_code": exc.code}},
            )
            parks = await self._sample.parks_matching_city(query) if self._settings.enable_sample_fallback else []
            if parks:
                return self._logged("city", query, parks, sources=["sample"], degraded=True, warnings=[
                    "The location service is unavailable; showing sample data only."
                ])
            raise ServiceUnavailableError(
                "The location service is temporarily unavailable. Please try again shortly.",
                retry_after=exc.retry_after,
            ) from exc

        warnings: list[str] = []
        bbox = place.bbox
        max_span = self._settings.max_bbox_span_deg
        if bbox.lat_span > max_span or bbox.lng_span > max_span:
            bbox = bbox.clamp_to_span(max_span)
            warnings.append("This area is very large; showing parks near its center only.")

        parks, sources, degraded = await self._parks_in_bbox(bbox, warnings)
        area = ResolvedArea(label=place.label, bbox=bbox.to_model(), center=bbox.center_model())
        response = self._response(parks, sources=sources, degraded=degraded, warnings=warnings, area=area)
        _log_search("city", query, response)
        return response

    async def search_in_bounds(self, bbox: BBox) -> ParksResponse:
        bbox.ensure_max_span(self._settings.max_bbox_span_deg)
        warnings: list[str] = []
        parks, sources, degraded = await self._parks_in_bbox(bbox, warnings)
        area = ResolvedArea(label="Current map area", bbox=bbox.to_model(), center=bbox.center_model())
        response = self._response(parks, sources=sources, degraded=degraded, warnings=warnings, area=area)
        _log_search("bounds", bbox.cache_key(), response)
        return response

    async def get_park(self, park_id: str) -> Park:
        cached = self._cache.get(f"park:{park_id}")
        if cached is not None:
            return cached

        park = await self._sample.park_by_id(park_id)
        if park is None and park_id.startswith("osm-"):
            try:
                park = await self._cache.get_or_set(
                    f"park-fetch:{park_id}", lambda: self._primary.park_by_id(park_id)
                )
            except UpstreamError as exc:
                raise ServiceUnavailableError(
                    "Park details are temporarily unavailable. Please try again shortly.",
                    retry_after=exc.retry_after,
                ) from exc
        if park is None:
            raise NotFoundError(f"Park '{park_id}' was not found.")
        self._remember([park])
        return park

    # ------------------------------------------------------------------ internals

    async def _parks_in_bbox(self, bbox: BBox, warnings: list[str]) -> tuple[list[Park], list[str], bool]:
        snapped = bbox.snapped(self._settings.bbox_snap_deg)
        cache_key = f"parks:{snapped.cache_key()}"
        cache_hit = self._cache.get(cache_key) is not None
        logger.info(
            "Park cache %s for %s", "hit" if cache_hit else "miss", cache_key,
            extra={"event": {"event": "cache_lookup", "cache_key": cache_key, "hit": cache_hit}},
        )
        try:
            parks: list[Park] = await self._cache.get_or_set(
                cache_key, lambda: self._primary.parks_in_bbox(snapped)
            )
        except UpstreamError as exc:
            logger.warning(
                "Primary park provider failed: %s", exc.message,
                extra={"event": {"event": "provider_failure", "provider": self._primary.name, "error_code": exc.code}},
            )
            if self._settings.enable_sample_fallback:
                fallback = await self._sample.parks_in_bbox(bbox)
                if fallback:
                    warnings.append("Live park data is temporarily unavailable; showing sample data only.")
                    self._remember(fallback)
                    return fallback, ["sample"], True
            raise ServiceUnavailableError(
                "Park data is temporarily unavailable. Please try again shortly.",
                retry_after=exc.retry_after,
            ) from exc

        if len(parks) >= self._settings.max_results:
            warnings.append("Many parks match this area; zoom in to see them all.")
        self._remember(parks)
        return parks, [self._primary.name], False

    def _remember(self, parks: list[Park]) -> None:
        # Lets the details endpoint serve parks seen in recent searches without another upstream call.
        for park in parks:
            self._cache.set(f"park:{park.id}", park)

    def _logged(self, kind: str, query: str, parks: list[Park], **kwargs: Any) -> ParksResponse:
        response = self._response(parks, **kwargs)
        _log_search(kind, query, response)
        return response

    @staticmethod
    def _response(
        parks: list[Park],
        *,
        sources: list[str],
        degraded: bool = False,
        warnings: list[str] | None = None,
        area: ResolvedArea | None = None,
    ) -> ParksResponse:
        unique = sorted(dedupe_parks(parks), key=lambda p: p.name.lower())
        return ParksResponse(
            parks=unique,
            count=len(unique),
            area=area,
            sources=sources,  # type: ignore[arg-type]
            degraded=degraded,
            warnings=warnings or [],
        )


def _log_search(kind: str, query: str, response: ParksResponse) -> None:
    logger.info(
        "Park search (%s) %r -> %d parks from %s%s",
        kind, query, response.count, ",".join(response.sources), " [degraded]" if response.degraded else "",
        extra={"event": {
            "event": "park_search",
            "kind": kind,
            "query": query,
            "count": response.count,
            "sources": response.sources,
            "degraded": response.degraded,
            "warnings": response.warnings,
        }},
    )
