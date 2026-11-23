"""Weather panel data: NWS forecast + Open-Meteo hourly + USGS gauge level."""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from .. import db
from ..services import weather as wx

router = APIRouter(prefix="/api/weather", tags=["weather"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/{water_slug}")
async def weather_for_water(water_slug: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.get_water_by_slug(conn, water_slug)
    if not row:
        raise HTTPException(404, f"water '{water_slug}' not found")
    bundle = await wx.weather_bundle(dict(row))
    # Surface per-source failures as 200-with-errors (panel degrades gracefully).
    if bundle["nws"].get("error") and bundle["open_meteo"].get("error"):
        # All sources failed: 502, but carry the bundle so per-source error
        # details reach the client (a bare HTTPException would discard them).
        return JSONResponse(status_code=502, content=bundle)
    return bundle
