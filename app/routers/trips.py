"""Trips: full CRUD + the consolidated per-trip briefing. Multi-user
capable — any user may create/update/delete."""
import asyncio
import logging
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import TripIn, TripOut, TripUpdate
from ..services import briefing

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trips", tags=["trips"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _row_to_out(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    w = conn.execute(
        "SELECT name, slug FROM waters WHERE id = ?", (row["water_id"],)
    ).fetchone()
    d["water_name"] = w["name"] if w else None
    d["water_slug"] = w["slug"] if w else None
    d["user_name"] = conn.execute(
        "SELECT name FROM users WHERE id = ?", (row["user_id"],)
    ).fetchone()["name"]
    d["catch_count"] = conn.execute(
        "SELECT COUNT(*) FROM catches WHERE trip_id = ?", (row["id"],)
    ).fetchone()[0]
    return d


@router.get("", response_model=list[TripOut])
def list_trips(user_id: int | None = None, status: str | None = None,
               conn: sqlite3.Connection = Depends(get_conn)):
    q = "SELECT * FROM trips"
    clauses, args = [], []
    if user_id is not None:
        clauses.append("user_id = ?")
        args.append(user_id)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date DESC, id DESC"
    rows = conn.execute(q, args).fetchall()
    return [_row_to_out(conn, r) for r in rows]


@router.post("", response_model=TripOut, status_code=201)
def create_trip(body: TripIn, conn: sqlite3.Connection = Depends(get_conn)):
    if not db.get_user(conn, body.user_id):
        raise HTTPException(404, f"user {body.user_id} not found")
    if not conn.execute(
        "SELECT 1 FROM waters WHERE id = ?", (body.water_id,)
    ).fetchone():
        raise HTTPException(404, f"water {body.water_id} not found")
    cur = conn.execute(
        """INSERT INTO trips (user_id, water_id, date, target_species, notes, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (body.user_id, body.water_id, body.date, body.target_species, body.notes, body.status),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_out(conn, row)


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(trip_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not row:
        raise HTTPException(404, "trip not found")
    return _row_to_out(conn, row)


@router.get("/{trip_id}/briefing")
async def trip_briefing(trip_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """Consolidated per-trip briefing: plan + conditions + gear.

    One place answers "what to bring" + "what/when to target":
      plan       — target species (with pixel-art sprites), regs,
                   stocking, recommended tactics/windows (recommend engine)
      conditions — weather (temp/wind/rain/sun), pressure + trend, lunar,
                   USGS water level + flow for the trip's water
      gear       — the user's tackle + conditional additions (each with a
                   human-readable reason; see app/services/gear_rules.py)

    Works for planned trips (future date -> forecast window) and logged
    trips (past date -> latest snapshot, labelled conditions.horizon).
    Resilient: upstreams degrade individually; the endpoint never 500s
    (worst case: 200 with degraded blocks + a note).
    """
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not row:
        raise HTTPException(404, "trip not found")
    w = conn.execute(
        "SELECT * FROM waters WHERE id = ?", (row["water_id"],)
    ).fetchone()
    if not w:  # FK-integrity paranoia: a dangling water_id must not 500
        raise HTTPException(404, "trip's water not found")
    try:
        return await briefing.build_briefing(conn, row, w)
    except Exception:
        # Last-resort guard (constraint: never 500 or crash). Upstreams are
        # individually non-raising, so this only fires on programmer error.
        log.exception("briefing assembly failed for trip %s — serving degraded 200", trip_id)
        return {
            "trip_id": trip_id,
            "water": {"slug": w["slug"], "name": w["name"], "kind": w["kind"]},
            "plan": {"species": [], "regs": None, "stocking": None, "tactics": None,
                     "kayak": None, "reminders": [], "winter_targeting": None},
            "conditions": {
                "date": row["date"],
                "weather": {"source": None, "horizon": None,
                            "note": "briefing assembly failed — see server log"},
                "water_level": None, "flow": None, "pressure": None,
                "lunar": None,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "gear": {"base": [], "conditional": []},
        }


@router.patch("/{trip_id}", response_model=TripOut)
def update_trip(trip_id: int, body: TripUpdate, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not row:
        raise HTTPException(404, "trip not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "user_id" in updates and not db.get_user(conn, updates["user_id"]):
        raise HTTPException(404, f"user {updates['user_id']} not found")
    if "water_id" in updates and not conn.execute(
        "SELECT 1 FROM waters WHERE id = ?", (updates["water_id"],)
    ).fetchone():
        raise HTTPException(404, f"water {updates['water_id']} not found")
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE trips SET {sets} WHERE id = ?", (*updates.values(), trip_id))
        conn.commit()
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    return _row_to_out(conn, row)


@router.delete("/{trip_id}", status_code=204)
def delete_trip(trip_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    cur = conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "trip not found")
    # FK cascade dropped the photo ROWS; sweep the FILES on the data volume.
    # Best-effort (logged inside) — a filesystem hiccup must not fail the API.
    from ..services import photo_store
    photo_store.sweep_trip_photos(trip_id)
    return None
