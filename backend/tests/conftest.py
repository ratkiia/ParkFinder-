import os

# Must run before any `app` import: importing app.main builds the default app, which would
# otherwise start writing to the real backend/logs directory during tests.
os.environ["PARKFINDER_LOG_TO_FILE"] = "false"

import json  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from app.cache import TTLCache  # noqa: E402
from app.config import Settings  # noqa: E402
from app.errors import CityNotFoundError  # noqa: E402
from app.geo import BBox  # noqa: E402
from app.models import Location, Park  # noqa: E402
from app.providers.base import GeocodedCity  # noqa: E402
from app.providers.sample import SampleParkProvider  # noqa: E402
from app.services.park_service import ParkService  # noqa: E402

SAMPLE_PARKS: list[dict[str, Any]] = [
    {
        "id": "prospect-park",
        "name": "Prospect Park",
        "description": "A 526-acre park in the heart of Brooklyn...",
        "location": {"lat": 40.6602, "lng": -73.969, "address": "Brooklyn, NY 11225"},
        "amenities": ["playground", "dog-run"],
        "hours": "6:00 AM - 1:00 AM",
        "images": ["https://example.com/prospect-1.jpg"],
        "acreage": 526,
        "rating": 4.7,
    },
    {
        "id": "zilker-park",
        "name": "Zilker Park",
        "location": {"lat": 30.2669, "lng": -97.7729, "address": "2100 Barton Springs Rd, Austin, TX 78704"},
    },
    # Malformed records that must be skipped, not crash the loader:
    {"id": "bad-coords", "name": "Nowhere Park", "location": {"lat": 999, "lng": 0}},
    {"id": "no-name", "location": {"lat": 40.0, "lng": -73.0}},
    "not-an-object",
]

AUSTIN_BBOX = BBox(30.09, -97.94, 30.52, -97.56)


def make_park(park_id: str = "osm-way-1", name: str = "Test Park", lat: float = 30.27, lng: float = -97.74,
              **kwargs: Any) -> Park:
    return Park(id=park_id, name=name, location=Location(lat=lat, lng=lng), source="openstreetmap", **kwargs)


@pytest.fixture
def sample_path(tmp_path: Path) -> Path:
    path = tmp_path / "parks.sample.json"
    path.write_text(json.dumps(SAMPLE_PARKS), encoding="utf-8")
    return path


@pytest.fixture
def settings(sample_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        sample_data_path=sample_path,
        log_dir=tmp_path / "logs",
        log_to_file=True,
        retry_backoff_seconds=0,
        max_retry_after_seconds=0,
        max_retries=1,
        nominatim_min_interval_seconds=0,
        rate_limit_per_minute=1000,
        rate_limit_burst=1000,
        cors_origins=["http://localhost:5173"],
        nominatim_url="https://nominatim.test/search",
        overpass_url="https://overpass.test/api/interpreter",
    )


class FakeGeocoder:
    def __init__(self, result: GeocodedCity | None = None, exc: Exception | None = None) -> None:
        self.result = result or GeocodedCity(label="Austin, Texas, United States", bbox=AUSTIN_BBOX,
                                             lat=30.27, lng=-97.74)
        self.exc = exc
        self.calls: list[str] = []

    async def geocode_city(self, query: str) -> GeocodedCity:
        self.calls.append(query)
        if self.exc:
            raise self.exc
        return self.result


class FakePrimary:
    name = "openstreetmap"

    def __init__(self, parks: list[Park] | None = None, exc: Exception | None = None) -> None:
        self.parks = parks if parks is not None else [make_park()]
        self.exc = exc
        self.bbox_calls: list[BBox] = []
        self.id_calls: list[str] = []

    async def parks_in_bbox(self, bbox: BBox) -> list[Park]:
        self.bbox_calls.append(bbox)
        if self.exc:
            raise self.exc
        return self.parks

    async def park_by_id(self, park_id: str) -> Park | None:
        self.id_calls.append(park_id)
        if self.exc:
            raise self.exc
        return next((p for p in self.parks if p.id == park_id), None)


def build_service(settings: Settings, geocoder: FakeGeocoder | None = None,
                  primary: FakePrimary | None = None) -> ParkService:
    return ParkService(
        settings=settings,
        geocoder=geocoder or FakeGeocoder(),
        primary=primary or FakePrimary(),
        sample=SampleParkProvider(settings.sample_data_path),
        cache=TTLCache(max_entries=100, default_ttl=60),
    )


__all__ = ["AUSTIN_BBOX", "CityNotFoundError", "FakeGeocoder", "FakePrimary", "build_service", "make_park"]
