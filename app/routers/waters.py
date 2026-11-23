"""Waters: static seed, read-only."""
import json
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


def _hydrate(row: dict) -> dict:
    """Parse the gauges JSON column into a list (defensive: bad JSON -> [])."""
    raw = row.pop("gauges", None)
    if isinstance(raw, str):
        try:
            row["gauges"] = json.loads(raw)
        except ValueError:
            row["gauges"] = []
    elif raw is None:
        row["gauges"] = []
    return row


@router.get("", response_model=list[WaterOut])
def list_waters(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT * FROM waters ORDER BY id").fetchall()
    return [_hydrate(dict(r)) for r in rows]
