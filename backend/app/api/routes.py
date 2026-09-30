"""Public REST endpoints (``/api/v1``). Read-only, GET only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.geo import BBox
from app.models import ErrorResponse, Park, ParksResponse
from app.services.park_service import ParkService

# Letters (incl. accented), spaces and common punctuation in US place names, e.g. "St. Louis, MO", "Coeur d'Alene".
CITY_PATTERN = r"^\s*[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .,'\-]*$"
PARK_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,119}$"

_ERRORS = {
    422: {"model": ErrorResponse, "description": "Invalid input"},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    503: {"model": ErrorResponse, "description": "Data provider unavailable"},
}

router = APIRouter(prefix="/api/v1", tags=["parks"])


def get_park_service(request: Request) -> ParkService:
    return request.app.state.park_service


Service = Annotated[ParkService, Depends(get_park_service)]


@router.get("/parks/by-city", response_model=ParksResponse, responses={**_ERRORS, 404: _ERRORS[422] | {"description": "City not found"}})
async def parks_by_city(
    service: Service,
    city: Annotated[
        str,
        Query(min_length=2, max_length=100, pattern=CITY_PATTERN, description="US city, e.g. 'Austin, TX'"),
    ],
) -> ParksResponse:
    """List parks in a US city. The city is geocoded, then parks inside its bounds are returned."""
    return await service.search_by_city(city)


@router.get("/parks/in-bounds", response_model=ParksResponse, responses=_ERRORS)
async def parks_in_bounds(
    service: Service,
    south: Annotated[float, Query(ge=-90, le=90)],
    west: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
) -> ParksResponse:
    """List parks inside a map viewport. Each side may span at most ``max_bbox_span_deg`` degrees."""
    return await service.search_in_bounds(BBox.create(south, west, north, east))


@router.get("/parks/{park_id}", response_model=Park, responses={**_ERRORS, 404: _ERRORS[422] | {"description": "Park not found"}})
async def park_details(
    service: Service,
    park_id: Annotated[str, Path(pattern=PARK_ID_PATTERN)],
) -> Park:
    """Full details for a single park."""
    return await service.get_park(park_id)
