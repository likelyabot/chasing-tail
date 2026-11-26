"""Catch-photo storage: multipart intake, magic-byte validation, file I/O.

Why hand-rolled multipart: the stack contract forbids new Python
dependencies, and FastAPI's ``UploadFile``/``Form`` parameters require
``python-multipart`` (asserted at import time). Browsers emit a perfectly
regular RFC 7578 multipart body, so a small explicit parser over the raw
bytes is the boring, dependency-free answer. Everything here is resilient:
malformed input yields typed errors (raised by the router as 400/413/404),
never a traceback.

Layout on the data volume (survives container recreation):
    <PHOTO_DIR>/<trip_id>/<photo_id>.<ext>
"""
import logging
import re
import uuid
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

#: ext -> Content-Type for GET /api/photos/<id>
MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
)


def detect_ext(head: bytes) -> str | None:
    """Identify the image type from magic bytes; None when unrecognized."""
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


# ---------------------------------------------------------------------------
# Multipart parsing (stdlib only)
# ---------------------------------------------------------------------------

_DISPOSITION_RE = re.compile(r'name="([^"]*)"|filename="([^"]*)"', re.IGNORECASE)


def parse_multipart(body: bytes, boundary: str) -> tuple[dict, list]:
    """Split a multipart/form-data body into (fields, files).

    fields: {name: text_value}
    files:  [(field_name, filename, raw_bytes), ...]

    Malformed chunks are skipped, never raised — the router decides how to
    treat "no usable file part" (400).
    """
    delim = ("--" + boundary).encode("latin-1", "replace")
    fields: dict = {}
    files: list = []
    for chunk in body.split(delim)[1:]:
        if chunk in (b"", b"--", b"--\r\n", b"\r\n"):
            continue  # epilogue / empty separator
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        sep = chunk.find(b"\r\n\r\n")
        if sep == -1:
            continue  # no header/body split — malformed, skip
        head = chunk[:sep].decode("latin-1")
        data = chunk[sep + 4:]
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = filename = None
        for line in head.split("\r\n"):
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            if key.strip().lower() != "content-disposition":
                continue
            for m in _DISPOSITION_RE.finditer(value):
                if m.group(1) is not None:
                    name = m.group(1)
                else:
                    filename = m.group(2)
        if filename is not None:
            files.append((name or "", filename, data))
        elif name is not None:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def extract_boundary(content_type: str | None) -> str | None:
    """Pull the boundary token out of a multipart Content-Type header."""
    if not content_type or "multipart/form-data" not in content_type.lower():
        return None
    m = re.search(r"boundary=(\"?[^\";]+\"?)", content_type, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip("\"")


# ---------------------------------------------------------------------------
# File I/O (paths stay inside PHOTO_DIR — no traversal possible: ids are
# server-generated uuid4 hex and trip ids are integers)
# ---------------------------------------------------------------------------

def trip_photo_dir(trip_id: int) -> Path:
    return Path(config.PHOTO_DIR) / str(int(trip_id))


def photo_path(photo_id: str, trip_id: int, ext: str) -> Path:
    return trip_photo_dir(trip_id) / f"{photo_id}.{ext}"


def store_photo(trip_id: int, ext: str, data: bytes) -> tuple[str, Path]:
    """Persist bytes under a fresh uuid id; returns (id, path).

    Writes to a temp name first, then renames, so a crash mid-upload never
    leaves a half-written file behind a live id.
    """
    dest = trip_photo_dir(trip_id)
    dest.mkdir(parents=True, exist_ok=True)
    pid = uuid.uuid4().hex
    tmp = dest / f".tmp-{pid}"
    tmp.write_bytes(data)
    final = dest / f"{pid}.{ext}"
    tmp.replace(final)
    return pid, final


def delete_photo_file(pid: str, trip_id: int, ext: str) -> None:
    """Best-effort unlink (missing file is not an error)."""
    try:
        p = photo_path(pid, trip_id, ext)
        if p.is_file():
            p.unlink()
    except OSError:
        log.warning("photo file removal failed for %s (row already gone)", pid)


def sweep_trip_photos(trip_id: int) -> int:
    """Remove a trip's whole photo dir after the trip row is deleted.

    Called from the trips router (FK cascade handles the rows). Returns the
    number of files removed; errors are logged, never raised.
    """
    d = trip_photo_dir(trip_id)
    removed = 0
    try:
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file():
                    p.unlink()
                    removed += 1
            d.rmdir()
    except OSError:
        log.warning("photo sweep failed for trip %s", trip_id)
    return removed
