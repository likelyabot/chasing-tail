"""Catch photos: upload (multipart), serve, delete.

POST /api/trips/{trip_id}/photos   multipart field "file" (+ optional "catch_id")
GET  /api/trips/{trip_id}/photos   list a trip's photos
GET  /api/photos/{photo_id}        serve the stored image (LAN-only, like the rest of the API)
DELETE /api/photos/{photo_id}      remove row + file

Constraints honoured: no new Python deps (multipart parsed by hand — see
app/services/photo_store.py), storage on the data volume (config.PHOTO_DIR
defaults next to the DB), never a 500 (every I/O path degrades to a typed
4xx), ~10 MB cap, jpg/png/webp only (magic bytes, not file names).
"""
import logging
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import config, db
from ..services import photo_store

log = logging.getLogger(__name__)

router = APIRouter(tags=["photos"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _photo_out(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["url"] = f"/api/photos/{d['id']}"
    return d


@router.post("/api/trips/{trip_id}/photos", status_code=201)
async def upload_photo(trip_id: int, request: Request,
                       conn: sqlite3.Connection = Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM trips WHERE id = ?", (trip_id,)).fetchone():
        raise HTTPException(404, f"trip {trip_id} not found")

    ctype = request.headers.get("content-type") or ""
    boundary = photo_store.extract_boundary(ctype)
    if not boundary:
        raise HTTPException(400, "expected a multipart/form-data upload")

    # Reject oversized bodies. We still DRAIN the request first: answering
    # mid-upload makes strict clients (urllib, curl) see a broken pipe when
    # they keep sending; a clean 413 after the body is consumed is polite.
    clen = request.headers.get("content-length")
    if clen is not None and clen.isdigit() and int(clen) > config.PHOTO_MAX_BYTES:
        received = 0
        while received < config.PHOTO_MAX_BYTES * 2:
            msg = await request.receive()
            received += len(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        raise HTTPException(413, f"photo exceeds the {config.PHOTO_MAX_BYTES // (1024 * 1024)} MB limit")

    body = await request.body()
    if len(body) > config.PHOTO_MAX_BYTES:
        raise HTTPException(413, f"photo exceeds the {config.PHOTO_MAX_BYTES // (1024 * 1024)} MB limit")

    fields, files = photo_store.parse_multipart(body, boundary)
    if not files:
        raise HTTPException(400, "no file part found in the upload")
    _, filename, data = files[0]  # first file part wins; the UI sends exactly one

    ext = photo_store.detect_ext(data[:16])
    if ext is None:
        raise HTTPException(400, "unsupported image type — only jpg, png and webp are accepted")

    catch_id = None
    if fields.get("catch_id"):
        try:
            catch_id = int(fields["catch_id"])
        except ValueError:
            raise HTTPException(400, "catch_id must be an integer")
        if not conn.execute(
            "SELECT 1 FROM catches WHERE id = ? AND trip_id = ?", (catch_id, trip_id)
        ).fetchone():
            raise HTTPException(404, f"catch {catch_id} not found on trip {trip_id}")

    pid, path = photo_store.store_photo(trip_id, ext, data)
    conn.execute(
        "INSERT INTO photos (id, trip_id, catch_id, ext, size_bytes, created_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (pid, trip_id, catch_id, ext, len(data), _utcnow()),
    )
    conn.commit()
    log.info("photo %s stored for trip %s (%d bytes, %s%s)",
             pid, trip_id, len(data), ext, f" catch={catch_id}" if catch_id else "")
    return {
        "id": pid, "trip_id": trip_id, "catch_id": catch_id, "ext": ext,
        "size_bytes": len(data), "created_utc": _utcnow(),
        "url": f"/api/photos/{pid}",
    }


@router.get("/api/trips/{trip_id}/photos")
def list_trip_photos(trip_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM trips WHERE id = ?", (trip_id,)).fetchone():
        raise HTTPException(404, f"trip {trip_id} not found")
    rows = conn.execute(
        "SELECT * FROM photos WHERE trip_id = ? ORDER BY created_utc, id", (trip_id,)
    ).fetchall()
    return [_photo_out(r) for r in rows]


@router.get("/api/photos/{photo_id}")
def get_photo(photo_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        raise HTTPException(404, "photo not found")
    path = photo_store.photo_path(row["id"], row["trip_id"], row["ext"])
    if not path.is_file():  # row survived but the file didn't — degrade, don't 500
        log.warning("photo row %s has no backing file — returning 404", photo_id)
        return JSONResponse({"detail": "photo file missing"}, status_code=404)
    return FileResponse(path, media_type=photo_store.MEDIA_TYPES[row["ext"]])


@router.delete("/api/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        raise HTTPException(404, "photo not found")
    conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    conn.commit()
    photo_store.delete_photo_file(row["id"], row["trip_id"], row["ext"])
    return None
