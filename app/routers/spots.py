"""Productive spots: per-water lat/lon bookmarks for the Leaflet map.

CRUD mirroring the gear/catches style:
  GET    /api/spots?water_slug=...   list (optionally one water)
  POST   /api/spots                  create (201)
  GET    /api/spots/{id}             one
  PUT    /api/spots/{id}             partial update
  DELETE /api/spots/{id}             204

Unknown water_slug -> 404 (mirrors trips' behaviour); out-of-range
coordinates -> 422 via Pydantic bounds.
"""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import SpotIn, SpotOut, SpotUpdate

router = APIRouter(prefix="/api/spots", tags=["spots"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _require_water(conn: sqlite3.Connection, slug: str) -> None:
    if not conn.execute("SELECT 1 FROM waters WHERE slug = ?", (slug,)).fetchone():
        raise HTTPException(404, f"water '{slug}' not found")


@router.get("", response_model=list[SpotOut])
def list_spots(water_slug: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    if water_slug is not None:
        _require_water(conn, water_slug)
        rows = conn.execute(
            "SELECT * FROM spots WHERE water_slug = ? ORDER BY name COLLATE NOCASE, id",
            (water_slug,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM spots ORDER BY water_slug, name COLLATE NOCASE, id"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("", response_model=SpotOut, status_code=201)
def create_spot(body: SpotIn, conn: sqlite3.Connection = Depends(get_conn)):
    _require_water(conn, body.water_slug)
    cur = conn.execute(
        "INSERT INTO spots (name, water_slug, lat, lon, notes) VALUES (?, ?, ?, ?, ?)",
        (body.name, body.water_slug, body.lat, body.lon, body.notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM spots WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.get("/{spot_id}", response_model=SpotOut)
def get_spot(spot_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
    if not row:
        raise HTTPException(404, "spot not found")
    return dict(row)


@router.put("/{spot_id}", response_model=SpotOut)
def update_spot(spot_id: int, body: SpotUpdate, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
    if not row:
        raise HTTPException(404, "spot not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "water_slug" in updates:
        _require_water(conn, updates["water_slug"])
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE spots SET {sets} WHERE id = ?", (*updates.values(), spot_id))
        conn.commit()
    row = conn.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
    return dict(row)


@router.delete("/{spot_id}", status_code=204)
def delete_spot(spot_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    cur = conn.execute("DELETE FROM spots WHERE id = ?", (spot_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "spot not found")
    return None
