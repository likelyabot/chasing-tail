"""Catches: full CRUD, nested under trips (cascade delete with the trip)."""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import CatchIn, CatchOut, CatchUpdate

router = APIRouter(prefix="/api/catches", tags=["catches"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("", response_model=list[CatchOut])
def list_catches(trip_id: int | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    if trip_id is not None:
        rows = conn.execute("SELECT * FROM catches WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM catches ORDER BY id DESC LIMIT 500").fetchall()
    return [dict(r) for r in rows]


@router.post("", response_model=CatchOut, status_code=201)
def create_catch(body: CatchIn, conn: sqlite3.Connection = Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM trips WHERE id = ?", (body.trip_id,)).fetchone():
        raise HTTPException(404, f"trip {body.trip_id} not found")
    cur = conn.execute(
        """INSERT INTO catches (trip_id, species, count, lure_or_method, spot, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (body.trip_id, body.species, body.count, body.lure_or_method, body.spot, body.notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM catches WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.get("/{catch_id}", response_model=CatchOut)
def get_catch(catch_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM catches WHERE id = ?", (catch_id,)).fetchone()
    if not row:
        raise HTTPException(404, "catch not found")
    return dict(row)


@router.patch("/{catch_id}", response_model=CatchOut)
def update_catch(catch_id: int, body: CatchUpdate, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM catches WHERE id = ?", (catch_id,)).fetchone()
    if not row:
        raise HTTPException(404, "catch not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE catches SET {sets} WHERE id = ?", (*updates.values(), catch_id))
        conn.commit()
    row = conn.execute("SELECT * FROM catches WHERE id = ?", (catch_id,)).fetchone()
    return dict(row)


@router.delete("/{catch_id}", status_code=204)
def delete_catch(catch_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    cur = conn.execute("DELETE FROM catches WHERE id = ?", (catch_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "catch not found")
    return None
