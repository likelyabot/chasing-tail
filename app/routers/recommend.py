"""Recommendation engine endpoint: species + water + month + weather -> plan."""
import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..services import recommend as rec
from ..services import usgs as usgs_svc
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
    if date is not None:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, f"invalid date '{date}' — expected ISO format YYYY-MM-DD")
    row = db.get_water_by_slug(conn, water_slug)
    if not row:
        raise HTTPException(404, f"water '{water_slug}' not found")
    water = dict(row)

    om = usgs = usgs_live = None
    if live_weather:
        om, usgs, usgs_live = await asyncio.gather(
            wx.open_meteo_hourly(water), wx.usgs_gauges(water),
            usgs_svc.water_usgs(water_slug),
        )
    plan = rec.recommend(water_slug, date, species, om, usgs,
                         gear=db.get_gear(conn), usgs_live=usgs_live)
    plan["weather_live"] = bool(live_weather and om and "hourly" in om)
    return plan
