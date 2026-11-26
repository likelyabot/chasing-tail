"""Community tab API: FishBrain manual imports + optional Reddit feed.

GET    /api/community?water_slug=&days=7   unified bundle (both sources)
POST   /api/community/fishbrain/import     paste a FishBrain CSV/JSON export
DELETE /api/community/fishbrain/import/{batch_id}   undo an import batch
"""
import sqlite3
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import db
from ..services import community as comm

router = APIRouter(prefix="/api/community", tags=["community"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("")
async def community(
    water_slug: str | None = None,
    days: int = Query(default=7, ge=1, le=3650),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """FishBrain imports + Reddit feed, both filtered by water (when given)
    and the recency window. Reddit is disabled (not errored) unless the
    REDDIT_* env vars are set."""
    if water_slug is not None and db.get_water_by_slug(conn, water_slug) is None:
        raise HTTPException(404, f"water '{water_slug}' not found")
    return await comm.build_community_bundle(conn, water_slug, days)


@router.post("/fishbrain/import")
async def fishbrain_import(
    request: Request,
    source_label: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Accept a pasted FishBrain export (CSV or JSON) as raw text.

    Fuzzy column detection + tolerant date parsing; unparseable rows are
    skipped and counted, never fatal. Returns the normalized rows plus
    their matched water (null = "Other").
    """
    raw = await request.body()
    if not raw.strip():
        raise HTTPException(400, "empty export — paste a FishBrain CSV or JSON export")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "export must be UTF-8 text")
    try:
        rows, skipped = comm.parse_fishbrain_export(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rows:
        raise HTTPException(400, f"no usable rows (skipped {skipped})")

    batch_id = uuid.uuid4().hex[:12]
    now = comm._utcnow()
    label = (source_label or "FishBrain import").strip()[:100] or "FishBrain import"
    conn.execute(
        "INSERT INTO fishbrain_batches (batch_id, imported_at, row_count, source_label) "
        "VALUES (?,?,?,?)",
        (batch_id, now, len(rows), label),
    )
    for r in rows:
        conn.execute(
            """INSERT INTO fishbrain_rows
               (batch_id, imported_at, species, date, weight_lb, length_in,
                location, notes, photo_url)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (batch_id, now, r["species"], r["date"], r["weight_lb"], r["length_in"],
             r["location"], r["notes"], r["photo_url"]),
        )
    conn.commit()
    return {
        "batch_id": batch_id,
        "imported": len(rows),
        "skipped": skipped,
        "rows": [{**r, "water": comm.match_water(r.get("location") or "")} for r in rows],
    }


@router.delete("/fishbrain/import/{batch_id}")
def fishbrain_delete(batch_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Undo an import batch (rows cascade-delete with the batch)."""
    deleted = conn.execute(
        "SELECT COUNT(*) FROM fishbrain_rows WHERE batch_id=?", (batch_id,)
    ).fetchone()[0]
    cur = conn.execute("DELETE FROM fishbrain_batches WHERE batch_id=?", (batch_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, f"batch '{batch_id}' not found")
    return {"batch_id": batch_id, "deleted_rows": deleted}
