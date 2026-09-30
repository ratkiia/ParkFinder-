"""Turn a US city name into a bounding box using OpenStreetMap Nominatim.

Usage policy: https://operations.osmfoundation.org/policies/nominatim/
(identifying User-Agent, max 1 request/second, cache results).
"""

import logging

import httpx

from app.config import Settings
from app.errors import CityNotFoundError, UpstreamError
from app.geo import BBox, is_valid_coordinate
from app.http_client import request_json
from app.providers.base import GeocodedCity
from app.rate_limit import MinIntervalLimiter

logger = logging.getLogger(__name__)

# Nominatim "addresstype" values that represent a populated place a resident would call a city.
PLACE_TYPES = frozenset({"city", "town", "village", "hamlet", "municipality", "borough", "suburb", "county"})


class NominatimGeocoder:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, limiter: MinIntervalLimiter) -> None:
        self._client = client
        self._settings = settings
        self._limiter = limiter

    async def geocode_city(self, query: str) -> GeocodedCity:
        await self._limiter.wait()
        data = await request_json(
            self._client,
            "GET",
            self._settings.nominatim_url,
            provider="Nominatim",
            params={"q": query, "format": "jsonv2", "countrycodes": "us", "limit": 5},
            max_retries=self._settings.max_retries,
            backoff_seconds=self._settings.retry_backoff_seconds,
            max_retry_after_seconds=self._settings.max_retry_after_seconds,
        )
        if not isinstance(data, list):
            raise UpstreamError("Nominatim returned an unexpected payload.")

        candidates = [c for c in (parse_result(item) for item in data) if c is not None]
        if not candidates:
            raise CityNotFoundError(f"No US city matching '{query}' was found.")
        # Prefer a real populated place over e.g. a street or building with the same name.
        preferred = [c for c, kind in candidates if kind in PLACE_TYPES]
        return preferred[0] if preferred else candidates[0][0]


def parse_result(item: object) -> tuple[GeocodedCity, str] | None:
    """Parse one Nominatim result; return None for malformed entries."""
    if not isinstance(item, dict):
        return None
    try:
        lat, lng = float(item["lat"]), float(item["lon"])
        south, north, west, east = (float(v) for v in item["boundingbox"])
    except (KeyError, TypeError, ValueError):
        return None
    if not is_valid_coordinate(lat, lng):
        return None
    try:
        bbox = BBox.create(south, west, north, east)
    except Exception:  # noqa: BLE001 - malformed provider data is skipped, not fatal
        logger.debug("Skipping Nominatim result with invalid bbox: %s", item.get("boundingbox"))
        return None
    label = str(item.get("display_name") or item.get("name") or "").strip() or "Unknown place"
    kind = str(item.get("addresstype") or item.get("type") or "")
    return GeocodedCity(label=label, bbox=bbox, lat=lat, lng=lng), kind
