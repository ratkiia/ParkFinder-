"""Geospatial helpers: bounding boxes, coordinate validation and de-duplication."""

import math
import re
from dataclasses import dataclass
from typing import Iterable

from app.errors import InvalidRequestError
from app.models import BoundingBoxModel, LatLng, Park


def is_valid_coordinate(lat: object, lng: object) -> bool:
    """True for finite, in-range numbers. (0, 0) "null island" is treated as malformed data."""
    if isinstance(lat, bool) or isinstance(lng, bool):
        return False
    try:
        lat_f, lng_f = float(lat), float(lng)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat_f) and math.isfinite(lng_f)):
        return False
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return False
    return not (lat_f == 0 and lng_f == 0)


@dataclass(frozen=True)
class BBox:
    """An axis-aligned bounding box. Boxes crossing the antimeridian are not supported (US-only app)."""

    south: float
    west: float
    north: float
    east: float

    @classmethod
    def create(cls, south: float, west: float, north: float, east: float) -> "BBox":
        for value in (south, west, north, east):
            if not math.isfinite(value):
                raise InvalidRequestError("Bounding box values must be finite numbers.")
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            raise InvalidRequestError("Latitude must be between -90 and 90.")
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise InvalidRequestError("Longitude must be between -180 and 180.")
        if south >= north:
            raise InvalidRequestError("'south' must be less than 'north'.")
        if west >= east:
            raise InvalidRequestError("'west' must be less than 'east'.")
        return cls(south, west, north, east)

    @property
    def lat_span(self) -> float:
        return self.north - self.south

    @property
    def lng_span(self) -> float:
        return self.east - self.west

    @property
    def center(self) -> tuple[float, float]:
        return ((self.south + self.north) / 2, (self.west + self.east) / 2)

    def ensure_max_span(self, max_span: float) -> None:
        if self.lat_span > max_span or self.lng_span > max_span:
            raise InvalidRequestError(
                f"Requested area is too large; each side must be at most {max_span} degrees. Zoom in and retry."
            )

    def clamp_to_span(self, max_span: float) -> "BBox":
        """Shrink the box around its center so neither side exceeds ``max_span``."""
        lat_c, lng_c = self.center
        half_lat = min(self.lat_span, max_span) / 2
        half_lng = min(self.lng_span, max_span) / 2
        return BBox(
            max(-90.0, lat_c - half_lat),
            max(-180.0, lng_c - half_lng),
            min(90.0, lat_c + half_lat),
            min(180.0, lng_c + half_lng),
        )

    def snapped(self, step: float) -> "BBox":
        """Expand outward to a grid so small map pans share a cache entry and edge parks are included."""
        return BBox(
            max(-90.0, round(math.floor(self.south / step) * step, 6)),
            max(-180.0, round(math.floor(self.west / step) * step, 6)),
            min(90.0, round(math.ceil(self.north / step) * step, 6)),
            min(180.0, round(math.ceil(self.east / step) * step, 6)),
        )

    def contains(self, lat: float, lng: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lng <= self.east

    def cache_key(self) -> str:
        return f"{self.south:.4f},{self.west:.4f},{self.north:.4f},{self.east:.4f}"

    def to_model(self) -> BoundingBoxModel:
        return BoundingBoxModel(south=self.south, west=self.west, north=self.north, east=self.east)

    def center_model(self) -> LatLng:
        lat, lng = self.center
        return LatLng(lat=lat, lng=lng)


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _name_key(name: str) -> str:
    return _NON_ALNUM.sub(" ", name.lower()).strip()


def dedupe_parks(parks: Iterable[Park], *, proximity_deg: float = 0.002) -> list[Park]:
    """Remove duplicates by id, then by same name at (nearly) the same place.

    OSM can map one park as a node *and* a polygon; overlapping queries can return the same park twice.
    When duplicates collide, the entry carrying more information wins.
    """
    by_id: dict[str, Park] = {}
    for park in parks:
        existing = by_id.get(park.id)
        if existing is None or _richness(park) > _richness(existing):
            by_id[park.id] = park

    result: list[Park] = []
    for park in by_id.values():
        key = _name_key(park.name)
        duplicate_index = next(
            (
                i
                for i, other in enumerate(result)
                if _name_key(other.name) == key
                and abs(other.location.lat - park.location.lat) <= proximity_deg
                and abs(other.location.lng - park.location.lng) <= proximity_deg
            ),
            None,
        )
        if duplicate_index is None:
            result.append(park)
        elif _richness(park) > _richness(result[duplicate_index]):
            result[duplicate_index] = park
    return result


def _richness(park: Park) -> int:
    fields = (park.description, park.location.address, park.hours, park.website, park.acreage, park.rating)
    return sum(v is not None for v in fields) + len(park.amenities) + len(park.images)
