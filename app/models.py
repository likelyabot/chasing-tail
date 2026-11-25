"""Pydantic request/response models."""
from datetime import date as _date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator


def _check_iso_date(v: str | None) -> str | None:
    """Reject non-ISO or impossible dates (e.g. 2026-13-45) with 422."""
    if v is None:
        return v
    try:
        _date.fromisoformat(v)
    except (TypeError, ValueError):
        raise ValueError("date must be a valid ISO date YYYY-MM-DD")
    return v


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)


class UserOut(UserIn):
    id: int


class WaterOut(BaseModel):
    id: int
    slug: str
    name: str
    location: str
    lat: float
    lon: float
    kind: str
    usgs_site: str | None
    gauges: list = []
    notes: str | None


class TripIn(BaseModel):
    user_id: int
    water_id: int
    date: str = Field(description="ISO date YYYY-MM-DD")
    target_species: str | None = None
    notes: str | None = None
    status: Literal["planned", "completed", "cancelled"] = "planned"

    @field_validator("date")
    @classmethod
    def _valid_date(cls, v: str | None) -> str | None:
        return _check_iso_date(v)


class TripUpdate(BaseModel):
    user_id: int | None = None
    water_id: int | None = None
    date: str | None = None
    target_species: str | None = None
    notes: str | None = None
    status: Literal["planned", "completed", "cancelled"] | None = None

    @field_validator("date")
    @classmethod
    def _valid_date(cls, v: str | None) -> str | None:
        return _check_iso_date(v)


class TripOut(TripIn):
    id: int
    water_name: str | None = None
    water_slug: str | None = None
    user_name: str | None = None
    catch_count: int = 0


class CatchIn(BaseModel):
    trip_id: int
    species: str = Field(min_length=1, max_length=100)
    count: int = Field(default=1, ge=1, le=1000)
    lure_or_method: str | None = None
    spot: str | None = None
    notes: str | None = None


class CatchUpdate(BaseModel):
    species: str | None = None
    count: int | None = Field(default=None, ge=1, le=1000)
    lure_or_method: str | None = None
    spot: str | None = None
    notes: str | None = None


class CatchOut(CatchIn):
    id: int
    logged_at: str


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    enabled: bool
    reply: str
    upstream: dict | None = None


# ---------- gear (PUT /api/gear) ----------
_Item = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class RodIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    use: str = Field(default="", max_length=200)


class ReelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    pairing: str = Field(default="", max_length=100)
    line: str = Field(default="", max_length=200)


class GearIn(BaseModel):
    """Full gear payload. Unknown TOP-LEVEL keys are rejected (422);
    unknown keys inside individual rod/reel objects are ignored."""

    model_config = {"extra": "forbid"}

    rods: list[RodIn] = Field(max_length=50)
    reels: list[ReelIn] = Field(max_length=50)
    lures: list[_Item] = Field(max_length=100)
    extras: list[_Item] = Field(max_length=100)
