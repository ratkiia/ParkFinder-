"""Local park data from ``assets/parks.sample.json``, used as a fallback and for offline demos."""

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from app.geo import BBox, dedupe_parks
from app.models import Park

logger = logging.getLogger(__name__)

_WORDS = re.compile(r"[a-z0-9]+")


class SampleParkProvider:
    name = "sample"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._parks: list[Park] | None = None

    def _load(self) -> list[Park]:
        if self._parks is not None:
            return self._parks
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("Sample data file not found: %s", self._path)
            raw = []
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Sample data file unreadable (%s): %s", self._path, exc)
            raw = []
        if not isinstance(raw, list):
            logger.error("Sample data must be a JSON array; ignoring %s", self._path)
            raw = []

        parks: list[Park] = []
        for index, item in enumerate(raw):
            try:
                parks.append(Park.model_validate({**item, "source": "sample"}))
            except (ValidationError, TypeError) as exc:
                # One bad record must not take down the rest of the dataset.
                logger.warning("Skipping invalid sample park at index %d: %s", index, exc)
        self._parks = dedupe_parks(parks)
        return self._parks

    async def parks_in_bbox(self, bbox: BBox) -> list[Park]:
        return [p for p in self._load() if bbox.contains(p.location.lat, p.location.lng)]

    async def parks_matching_city(self, city: str) -> list[Park]:
        """Match on the city words appearing in the park address (used when geocoding is unavailable)."""
        city_part = city.split(",")[0]
        wanted = _WORDS.findall(city_part.lower())
        if not wanted:
            return []
        matches = []
        for park in self._load():
            address_words = _WORDS.findall((park.location.address or "").lower())
            if _contains_sequence(address_words, wanted):
                matches.append(park)
        return matches

    async def park_by_id(self, park_id: str) -> Park | None:
        return next((p for p in self._load() if p.id == park_id), None)


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))
