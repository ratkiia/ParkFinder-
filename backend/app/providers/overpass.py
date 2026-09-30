"""Fetch parks from OpenStreetMap via the Overpass API.

Parks are mapped as points (nodes) *or* polygons (ways / multipolygon relations).
``out center`` makes Overpass return a representative center for polygons, so every
park can be placed on the map. A polygon that merely overlaps the requested box is
still returned, so parks straddling the box edge are not lost.
"""

import logging
import re

import httpx

from app.config import Settings
from app.errors import UpstreamError
from app.geo import BBox, dedupe_parks, is_valid_coordinate
from app.http_client import request_json
from app.models import Location, Park

logger = logging.getLogger(__name__)

OSM_ID_PATTERN = re.compile(r"^osm-(node|way|relation)-(\d{1,15})$")

# OSM tag -> amenity label shown in the UI. Only explicit tags are used; nothing is guessed.
_AMENITY_TAGS: dict[str, tuple[set[str], str]] = {
    "toilets": ({"yes"}, "restrooms"),
    "drinking_water": ({"yes"}, "drinking-water"),
    "dog": ({"yes", "leashed", "unleashed"}, "dogs-allowed"),
    "wheelchair": ({"yes", "designated"}, "wheelchair-accessible"),
    "lit": ({"yes"}, "lit-at-night"),
    "playground": ({"yes"}, "playground"),
    "bbq": ({"yes"}, "bbq"),
    "parking": ({"yes", "surface", "multi-storey", "underground"}, "parking"),
}

_EXCLUDED_ACCESS = {"private", "no"}


def build_bbox_query(bbox: BBox, *, timeout_seconds: int, limit: int) -> str:
    box = f"{bbox.south:.6f},{bbox.west:.6f},{bbox.north:.6f},{bbox.east:.6f}"
    return (
        f"[out:json][timeout:{timeout_seconds}];\n"
        f'(node["leisure"="park"]({box});way["leisure"="park"]({box});relation["leisure"="park"]({box}););\n'
        f"out tags center {limit};"
    )


def build_id_query(osm_type: str, osm_id: str, *, timeout_seconds: int) -> str:
    return f"[out:json][timeout:{timeout_seconds}];\n{osm_type}({osm_id});\nout tags center;"


def _format_address(tags: dict[str, str]) -> str | None:
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    region = " ".join(p for p in (tags.get("addr:state"), tags.get("addr:postcode")) if p)
    parts = [p for p in (street, tags.get("addr:city"), region) if p]
    return ", ".join(parts) or None


def parse_element(element: object) -> Park | None:
    """Convert one Overpass element into a Park, or None when it is unusable.

    Unnamed, private, or coordinate-less features are skipped instead of guessed at.
    """
    if not isinstance(element, dict):
        return None
    osm_type, osm_id = element.get("type"), element.get("id")
    if osm_type not in ("node", "way", "relation") or not isinstance(osm_id, int):
        return None

    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    tags = {str(k): str(v).strip() for k, v in tags.items() if v is not None}

    name = tags.get("name", "")
    if not name or tags.get("access") in _EXCLUDED_ACCESS:
        return None

    point = element if osm_type == "node" else element.get("center")
    if not isinstance(point, dict) or not is_valid_coordinate(point.get("lat"), point.get("lon")):
        return None

    amenities = [label for tag, (values, label) in _AMENITY_TAGS.items() if tags.get(tag) in values]

    try:
        return Park(
            id=f"osm-{osm_type}-{osm_id}",
            name=name,
            description=tags.get("description"),
            location=Location(lat=float(point["lat"]), lng=float(point["lon"]), address=_format_address(tags)),
            amenities=amenities,
            hours=tags.get("opening_hours"),
            images=[tags["image"]] if "image" in tags else [],
            website=tags.get("website") or tags.get("contact:website"),
            source="openstreetmap",
        )
    except ValueError:
        logger.debug("Skipping malformed OSM element %s/%s", osm_type, osm_id)
        return None


def parse_elements(payload: object) -> list[Park]:
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise UpstreamError("Overpass returned an unexpected payload.")
    parks = [p for p in (parse_element(e) for e in payload["elements"]) if p is not None]
    return dedupe_parks(parks)


class OverpassParkProvider:
    name = "openstreetmap"

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @property
    def _server_timeout(self) -> int:
        # Ask Overpass to give up slightly before our own read timeout.
        return max(5, int(self._settings.read_timeout) - 2)

    async def _run(self, query: str) -> object:
        return await request_json(
            self._client,
            "POST",
            self._settings.overpass_url,
            provider="Overpass",
            data={"data": query},
            max_retries=self._settings.max_retries,
            backoff_seconds=self._settings.retry_backoff_seconds,
            max_retry_after_seconds=self._settings.max_retry_after_seconds,
        )

    async def parks_in_bbox(self, bbox: BBox) -> list[Park]:
        query = build_bbox_query(bbox, timeout_seconds=self._server_timeout, limit=self._settings.max_results)
        return parse_elements(await self._run(query))

    async def park_by_id(self, park_id: str) -> Park | None:
        match = OSM_ID_PATTERN.match(park_id)
        if not match:
            return None
        query = build_id_query(match.group(1), match.group(2), timeout_seconds=self._server_timeout)
        parks = parse_elements(await self._run(query))
        return parks[0] if parks else None
