"""Live conditions: USGS water level/flow + barometric pressure + alerts.

GET /api/conditions/<water_slug> ->
    {
      "water": "<slug>",
      "usgs": {site, name, label, stage_ft, flow_cfs, temp_f, flow_prev_cfs,
               as_of_iso, age_hours, qualifiers, status, stale, note,
               secondary?: {...}} | null,   # null = no USGS gauge (never fabricated)
      "pressure": {hpa, inhg, trend, window_hours, delta_hpa, as_of_local} | null,
      "alerts": [ {key, signature, severity, message}, ... ],   # may be empty
      "generated_at": "..."
    }

Resilience: both upstreams (USGS IV, Open-Meteo) are independently cached and
degrade to stale/no_data — this endpoint never 500s because of them.
"""
import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..services import alerts as cond_alerts
from ..services import usgs as usgs_svc
from ..services import weather as wx

router = APIRouter(prefix="/api/conditions", tags=["conditions"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/{water_slug}")
async def conditions(water_slug: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.get_water_by_slug(conn, water_slug)
    if not row:
        raise HTTPException(404, f"water '{water_slug}' not found")
    water = dict(row)
    # Independent, cached, non-raising upstreams (see their modules).
    om, usgs_block = await asyncio.gather(
        wx.open_meteo_hourly(water), usgs_svc.water_usgs(water_slug)
    )
    om = om if isinstance(om, dict) and "hourly" in om else None
    usgs_block = usgs_block if isinstance(usgs_block, dict) else None
    alerts = cond_alerts.derive_alerts(water_slug, om, usgs_block)
    # Optional mirror (no-op unless HERMES_CHAT_ENDPOINT is set).
    await cond_alerts.maybe_mirror({water_slug: alerts})
    return {
        "water": water_slug,
        "usgs": usgs_block,
        "pressure": (om or {}).get("pressure"),
        "alerts": alerts,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
