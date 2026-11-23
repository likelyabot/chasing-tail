"""SQLite persistence: schema, connection helper, one-time seeding.

Raw sqlite3 (kept dependency-light per the stack contract). Each request gets
its own connection; WAL mode keeps readers from blocking the writer.
"""
import json
import sqlite3
from pathlib import Path

from . import config
from .knowledge import WATER_GAUGES, WATER_SEEDS, SEED_USER

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    email TEXT
);
CREATE TABLE IF NOT EXISTS waters (
    id         INTEGER PRIMARY KEY,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    location   TEXT NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'lake',
    usgs_site  TEXT,
    gauges     TEXT,
    notes      TEXT
);
CREATE TABLE IF NOT EXISTS trips (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    water_id       INTEGER NOT NULL REFERENCES waters(id),
    date           TEXT NOT NULL,
    target_species TEXT,
    notes          TEXT,
    status         TEXT NOT NULL DEFAULT 'planned'
);
CREATE INDEX IF NOT EXISTS idx_trips_user_date ON trips(user_id, date);
CREATE TABLE IF NOT EXISTS catches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id       INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    species       TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1,
    lure_or_method TEXT,
    spot          TEXT,
    notes         TEXT,
    logged_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_catches_trip ON catches(trip_id);
"""


def connect() -> sqlite3.Connection:
    path = Path(config.DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create schema + seed static data. Idempotent; safe to call at startup."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Lightweight forward migrations for pre-existing databases.

    Waters is static seed data (no user write path), so adding columns and
    refreshing seed rows on startup is safe and keeps deployed DBs converged
    with the repo.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(waters)")}
    if "gauges" not in cols:
        conn.execute("ALTER TABLE waters ADD COLUMN gauges TEXT")


def _seed(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Exactly one user: Angler (email left NULL — no PII baked into the repo).
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (SEED_USER["name"], SEED_USER["email"]),
        )
    # Static water bodies. UPSERT (not INSERT OR IGNORE) so already-deployed
    # DBs pick up revised seed data (notes, gauges, coords) on next boot.
    for w in WATER_SEEDS:
        cur.execute(
            """INSERT INTO waters
               (slug, name, location, lat, lon, kind, usgs_site, gauges, notes)
               VALUES (:slug, :name, :location, :lat, :lon, :kind, :usgs_site, :gauges, :notes)
               ON CONFLICT(slug) DO UPDATE SET
                 name = excluded.name,
                 location = excluded.location,
                 lat = excluded.lat,
                 lon = excluded.lon,
                 kind = excluded.kind,
                 usgs_site = excluded.usgs_site,
                 gauges = excluded.gauges,
                 notes = excluded.notes""",
            {**w, "gauges": json.dumps(WATER_GAUGES.get(w["slug"], []))},
        )
    conn.commit()


def get_water_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM waters WHERE slug = ?", (slug,)).fetchone()


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
