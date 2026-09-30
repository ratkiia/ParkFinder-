"""Pydantic models shared by the API layer and the data providers.

Optional fields are ``None`` / empty when a provider has no data: the API never invents details.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ParkSource = Literal["openstreetmap", "sample"]


def _is_http_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 2048


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    address: str | None = None


class Park(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    location: Location
    amenities: list[str] = Field(default_factory=list)
    hours: str | None = None
    images: list[str] = Field(default_factory=list)
    acreage: float | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    website: str | None = None
    source: ParkSource = "sample"

    @field_validator("description", "hours", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("images", mode="before")
    @classmethod
    def _only_http_images(cls, value: object) -> list[str]:
        # Drop anything that is not an absolute http(s) URL instead of failing the whole park.
        if not isinstance(value, list):
            return []
        return [v for v in value if _is_http_url(v)]

    @field_validator("website", mode="before")
    @classmethod
    def _only_http_website(cls, value: object) -> str | None:
        return value if _is_http_url(value) else None

    @field_validator("amenities", mode="before")
    @classmethod
    def _clean_amenities(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        seen: dict[str, None] = {}
        for item in value:
            if isinstance(item, str) and item.strip():
                seen.setdefault(item.strip().lower(), None)
        return list(seen)


class BoundingBoxModel(BaseModel):
    south: float
    west: float
    north: float
    east: float


class LatLng(BaseModel):
    lat: float
    lng: float


class ResolvedArea(BaseModel):
    """The geographic area a search was resolved to (e.g. a geocoded city)."""

    label: str
    bbox: BoundingBoxModel
    center: LatLng


class ParksResponse(BaseModel):
    parks: list[Park]
    count: int
    area: ResolvedArea | None = None
    sources: list[ParkSource]
    degraded: bool = Field(
        default=False, description="True when the primary provider failed and fallback data is shown."
    )
    warnings: list[str] = Field(default_factory=list)
    attribution: str = "Park data © OpenStreetMap contributors (ODbL)"


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = Field(default=None, description="Matches the X-Request-ID header and the server logs.")
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
