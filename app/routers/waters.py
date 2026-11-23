"""Waters: static seed, read-only."""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends

from .. import db
from ..models import WaterOut

router = APIRouter(prefix="/api/waters", tags=["waters"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("", response_model=list[WaterOut])
def list_waters(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT * FROM waters ORDER BY id").fetchall()
    return [dict(r) for r in rows]
