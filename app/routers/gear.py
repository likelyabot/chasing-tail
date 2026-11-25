"""Gear: Angler's tackle — DB-backed, editable from the UI.

GET  serves the saved payload (falls back to the static GEAR defaults when
     the row is missing/corrupt — see db.get_gear).
PUT  validates the full payload (GearIn) and stores it; extra top-level
     keys are rejected with 422 (item-level unknown keys are ignored).
DELETE drops the row so GET falls back to the repo defaults. 204.
"""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends

from .. import db
from ..models import GearIn

router = APIRouter(prefix="/api/gear", tags=["gear"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("")
def get_gear(conn: sqlite3.Connection = Depends(get_conn)):
    return db.get_gear(conn)


@router.put("")
def put_gear(payload: GearIn, conn: sqlite3.Connection = Depends(get_conn)):
    data = payload.model_dump()
    db.save_gear(conn, data)
    return data


@router.delete("", status_code=204)
def delete_gear(conn: sqlite3.Connection = Depends(get_conn)):
    db.delete_gear(conn)
    return None
