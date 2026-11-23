"""Pydantic request/response models."""
from typing import Literal

from pydantic import BaseModel, Field


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
    notes: str | None


class TripIn(BaseModel):
    user_id: int
    water_id: int
    date: str = Field(description="ISO date YYYY-MM-DD")
    target_species: str | None = None
    notes: str | None = None
    status: Literal["planned", "completed", "cancelled"] = "planned"


class TripUpdate(BaseModel):
    user_id: int | None = None
    water_id: int | None = None
    date: str | None = None
    target_species: str | None = None
    notes: str | None = None
    status: Literal["planned", "completed", "cancelled"] | None = None


class TripOut(TripIn):
    id: int
    water_name: str | None = None
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
