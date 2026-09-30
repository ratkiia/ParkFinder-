"""Provider interfaces. New data sources (e.g. a municipal open-data API) implement these protocols."""

from dataclasses import dataclass
from typing import Protocol

from app.geo import BBox
from app.models import Park


@dataclass(frozen=True)
class GeocodedCity:
    label: str
    bbox: BBox
    lat: float
    lng: float


class Geocoder(Protocol):
    async def geocode_city(self, query: str) -> GeocodedCity: ...


class ParkProvider(Protocol):
    name: str

    async def parks_in_bbox(self, bbox: BBox) -> list[Park]: ...

    async def park_by_id(self, park_id: str) -> Park | None: ...
