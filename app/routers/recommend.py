"""Recommendation engine endpoint: species + water + month + weather -> plan."""
import asyncio
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..services import recommend as rec
from ..services import weather as wx

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("")
async def recommend(
    water_slug: str,
    date: str | None = None,
    species: str | None = None,
    live_weather: bool = True,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Rule-based plan. live_weather=false skips upstream fetches (offline mode)."""
    row = db.get_water_by_slug(conn, water_slug)
    if not row:
        raise HTTPException(404, f"water '{water_slug}' not found")
    water = dict(row)

    om = usgs = None
    if live_weather:
        om, usgs = await asyncio.gather(
            wx.open_meteo_hourly(water), wx.usgs_level(water)
        )
    plan = rec.recommend(water_slug, date, species, om, usgs)
    plan["weather_live"] = bool(live_weather and om and "hourly" in om)
    return plan
