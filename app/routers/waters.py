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


def _parse_json_field(raw, default):
    """Defensively parse a JSON column (bad JSON / NULL -> default)."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return default
    return default


def _hydrate(row: dict) -> dict:
    """Parse the gauges/extent JSON columns (defensive: bad JSON -> default)."""
    row["gauges"] = _parse_json_field(row.pop("gauges", None), [])
    row["extent"] = _parse_json_field(row.pop("extent", None), None)
    return row


@router.get("", response_model=list[WaterOut])
def list_waters(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT * FROM waters ORDER BY id").fetchall()
    return [_hydrate(dict(r)) for r in rows]
