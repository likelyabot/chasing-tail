"""Community tab: FishBrain manual imports + optional Reddit poller.

FishBrain
---------
The user exports his own journal/catches on his phone and pastes the CSV or
JSON into the app (no secrets, no third-party scraping). Parsing is
deliberately FUZZY: column names are recognized by common variants
(case-insensitive, punctuation-stripped), and dates tolerate ISO, US m/d/y
and "Mon DD YYYY" forms. Unparseable rows are skipped and counted — never
fatal. Imported rows are the user's own data on a LAN-only DB.

Reddit
------
OFFICIAL API only: OAuth2 client_credentials grant for a free personal
"script"-type app. Entirely OPTIONAL — enabled only when REDDIT_CLIENT_ID
and REDDIT_CLIENT_SECRET are both set (config). Otherwise the API reports
``reddit.enabled: false`` and the UI shows a muted configure notice; nothing
errors. Fetch-on-request with the same file-cache/stale-flag degradation as
the weather sources: Reddit down => last good feed served with
``stale: true``, never a 500. Politeness: at most 4 feed requests per poll
(one /hot per configured subreddit), 429 + Retry-After honored, UA identifies
the app generically. Secrets only ever arrive via env vars.
"""
import asyncio
import base64
import csv
import io
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx

from .. import config
from .weather import _read_cache, _write_cache

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Water matching (shared by FishBrain location matching and Reddit post
# classification). Aliases are lowercase substrings; matching is
# case-insensitive. Iteration order is fixed (dict order) so a text that
# mentions two waters deterministically yields the earlier one.
# ---------------------------------------------------------------------------
WATER_ALIASES = {
    "collins-lake": ("collins lake", "merle collins", "virginia ranch"),
    "new-bullards-bar": ("new bullards bar", "bullards bar"),
    "loon-lake": ("loon lake", "crystal basin"),
    "sacramento-river-westport": ("sacramento river", "westport", "red bluff", "colusa"),
}

# These names are common OUTSIDE California too, so on public Reddit they
# only match when the text carries CA context (see match_water).
_CA_DISAMBIGUATED = frozenset({"collins-lake", "loon-lake"})

_CA_COUNTIES = (
    "butte", "lassen", "shasta", "tehama", "colusa", "glenn", "placer",
    "sacramento", "sutter", "yolo", "el dorado", "sierra", "trinity",
    "mendocino", "lake", "madera", "mariposa", "tuolumne", "calaveras",
    "amador", "alpine", "mono", "inyo", "san joaquin", "stanislaus",
    "fresno", "tulere", "kern", "san luis obispo", "santa barbara",
    "ventura", "los angeles", "orange", "riverside", "san bernardino",
    "imperial", "san diego", "san mateo", "santa clara", "alameda",
    "contra costa", "solano", "sonoma", "marin", "san francisco",
)
_CA_CONTEXT_RE = re.compile(
    r"\b(?:california|ca|" + "|".join(re.escape(c) for c in _CA_COUNTIES) + r")\b",
    re.IGNORECASE,
)


def match_water(text, disambiguate: bool = False) -> str | None:
    """Keyword-match free text against the four waters. Returns a slug or None.

    Loose mode (FishBrain — the user's own exports): the first water with any
    alias hit wins.

    Disambiguate mode (public Reddit): "Loon Lake" / "Collins Lake" are common
    place names, so they only match when the text ALSO carries CA context —
    a county name or an explicit California/CA mention — OR a second,
    water-specific alias (e.g. "Crystal Basin" beside "Loon Lake"). The
    matched alias spans are masked before the context check so the "Lake" in
    the water's own name does not count as "Lake County" context.
    """
    if not text:
        return None
    t = str(text).lower()
    for slug, aliases in WATER_ALIASES.items():
        hits = [a for a in aliases if a in t]
        if not hits:
            continue
        if disambiguate and slug in _CA_DISAMBIGUATED and len(hits) < 2:
            masked = t
            for a in hits:
                masked = masked.replace(a, " ")
            if not _CA_CONTEXT_RE.search(masked):
                continue
        return slug
    return None


# ---------------------------------------------------------------------------
# FishBrain export parsing (fuzzy columns, tolerant dates)
# ---------------------------------------------------------------------------
# Accepted column-name variants per normalized field (headers are compared
# after lowercasing and stripping all non-alphanumerics, so "Species Name",
# "species_name" and "SPECIESNAME" all normalize to "speciesname").
FIELD_VARIANTS = {
    "species": (
        "species", "fish", "speciesname", "fishspecies", "speciesname",
        "fishspeciesname", "speciestype",
    ),
    "date": (
        "date", "time", "created", "createdat", "createdon", "catchdate",
        "catchtime", "datecaught", "timestamp", "datetime",
    ),
    "weight_lb": (
        "weight", "wt", "lbs", "lb", "weightlb", "weightlbs", "weightinlbs",
        "pounds", "pound",
    ),
    "length_in": (
        "length", "len", "inches", "inch", "lengthin", "lengthinches",
        "lengthinch", "totallength", "forklength",
    ),
    "location": (
        "location", "spot", "water", "area", "watername", "locationname",
        "spotname", "waterbody", "lake", "river", "pond", "dam", "reservoir",
    ),
    "notes": (
        "notes", "comments", "details", "comment", "description", "remarks",
        "note",
    ),
    "photo_url": (
        "photourl", "photo", "image", "imageurl", "img", "url", "thumbnail",
        "thumb", "photothumb", "photos", "picture", "pictures",
    ),
}

MAX_EXPORT_CHARS = 2_000_000
_WEIGHT_MAX = 10_000.0   # lb — anything bigger is a parse artifact
_LENGTH_MAX = 200.0      # in

_JSON_WRAPPERS = (
    "entries", "records", "data", "journal", "catches", "logs", "items",
    "results", "rows",
)

_UNIT_RE = re.compile(r"\b(lbs?|pounds?|inches?|in|ft|feet)\b\.?", re.IGNORECASE)


def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def _detect_columns(headers) -> dict:
    """Map normalized-field -> original header cell, by variant lookup."""
    norm_to_orig: dict[str, str] = {}
    for h in headers:
        n = _norm_header(h)
        if n and n not in norm_to_orig:
            norm_to_orig[n] = h
    mapping: dict[str, str] = {}
    for field, variants in FIELD_VARIANTS.items():
        for v in variants:
            if v in norm_to_orig:
                mapping[field] = norm_to_orig[v]
                break
    return mapping


def _parse_csv(text: str) -> list[dict]:
    """CSV with a header row -> list of {original_header: value} dicts."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError("CSV needs a header row plus at least one data row")
    headers = [h.strip() for h in rows[0]]
    records = []
    for r in rows[1:]:
        rec = {}
        for i, h in enumerate(headers):
            if h:
                rec[h] = r[i] if i < len(r) else ""
        records.append(rec)
    return records


def _parse_json(text: str) -> list[dict]:
    """FishBrain-style JSON export -> list of record dicts.

    Accepts a top-level array of objects, an object wrapping such an array
    (known wrapper keys first, then any list-of-objects value), or a single
    flat object (one record).
    """
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise ValueError(f"invalid JSON: {e}") from None
    if isinstance(obj, list):
        records = [r for r in obj if isinstance(r, dict)]
    elif isinstance(obj, dict):
        records = None
        for k in _JSON_WRAPPERS:
            v = obj.get(k)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                records = v
                break
        if records is None:
            for v in obj.values():
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    records = v
                    break
        if records is None and all(
            not isinstance(v, (list, dict)) for v in obj.values()
        ):
            records = [obj]
    else:
        raise ValueError("JSON export must be an array or object of records")
    if not records:
        raise ValueError("JSON export contained no object rows")
    return records


def _from_epoch(v: float) -> datetime | None:
    """Epoch seconds or millis (1000 AD–2100 sanity band) -> aware UTC dt."""
    try:
        if v >= 1e11:
            v /= 1000.0
        if not (9.0e8 <= v <= 4.2e9):
            return None
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


_DATE_FORMATS = (
    "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m.%d.%Y",
    "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y",
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
)


def parse_flexible_date(value) -> str | None:
    """Tolerant date parse -> ISO YYYY-MM-DD, or None when unparseable.

    Accepts ISO (date or datetime, Z/offset), US m/d/y (several separators,
    2-digit years), "Mon DD YYYY" / "Month DD, YYYY", and epoch seconds/millis
    (numbers or digit strings).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        dt = _from_epoch(float(value))
        return dt.strftime("%Y-%m-%d") if dt else None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10,13}", s):
        dt = _from_epoch(float(s))
        return dt.strftime("%Y-%m-%d") if dt else None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_measure(raw, max_val: float) -> float | None:
    """Parse a weight/length cell ("12.5 lbs", "12,5", "12.5") -> float or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = _UNIT_RE.sub("", s).strip()
    if "," in s:
        parts = s.split(",")
        # "1,250" = thousands separator; "12,5" = decimal comma
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    if not (0 < v <= max_val):
        return None
    return round(v, 2)


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _normalize_records(records: list[dict]) -> tuple[list[dict], int]:
    """Records -> (normalized rows, skipped_count).

    Skipped = rows that are entirely empty, or rows whose date is PRESENT but
    unparseable. A MISSING date is not fatal — the row is imported with
    date=null (shown as "undated" in the UI).
    """
    headers: list = []
    for r in records:
        for k in r.keys():
            if k not in headers:
                headers.append(k)
    mapping_global = _detect_columns(headers)
    if not mapping_global:
        raise ValueError(
            "no recognizable columns — expected something like "
            "species/date/weight/length/location/notes/photo"
        )
    rows: list[dict] = []
    skipped = 0
    for rec in records:
        # Per-record detection: heterogeneous exports (mixed key spellings
        # across rows) still resolve each row's own columns; the global
        # mapping is the fallback for sparse rows.
        mapping = _detect_columns(list(rec.keys())) or mapping_global
        def get(field):
            col = mapping.get(field)
            if col is None:
                return None
            return _clean(rec.get(col))

        species = get("species")
        date_raw = get("date")
        weight_raw = get("weight_lb")
        length_raw = get("length_in")
        location = get("location")
        notes = get("notes")
        photo = get("photo_url")

        if not any([species, date_raw, weight_raw, length_raw, location, notes, photo]):
            skipped += 1
            continue
        date = parse_flexible_date(date_raw) if date_raw is not None else None
        if date_raw is not None and date is None:
            skipped += 1
            continue
        rows.append({
            "species": species,
            "date": date,
            "weight_lb": parse_measure(weight_raw, _WEIGHT_MAX) if weight_raw else None,
            "length_in": parse_measure(length_raw, _LENGTH_MAX) if length_raw else None,
            "location": location,
            "notes": notes,
            "photo_url": photo,
        })
    return rows, skipped


def parse_fishbrain_export(text: str) -> tuple[list[dict], int]:
    """Parse a pasted FishBrain export (CSV or JSON) -> (rows, skipped).

    Raises ValueError with a human-readable reason when the text is not a
    usable export at all (empty, no recognizable columns, bad JSON...).
    """
    text = text.strip()
    if not text:
        raise ValueError("empty export — paste a FishBrain CSV or JSON export")
    if len(text) > MAX_EXPORT_CHARS:
        raise ValueError("export too large (max 2 MB)")
    if text[0] in "{[":
        records = _parse_json(text)
    else:
        records = _parse_csv(text)
    rows, skipped = _normalize_records(records)
    if not rows and not skipped:
        raise ValueError("no usable rows found")
    return rows, skipped


# ---------------------------------------------------------------------------
# Reddit poller (official API, optional)
# ---------------------------------------------------------------------------
_REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_FEED_LOCK = asyncio.Lock()


def reddit_enabled() -> bool:
    return bool(config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET)


def reddit_subreddits() -> list[str]:
    """Subreddits to poll, capped so a poll stays within the politeness budget."""
    subs = config.REDDIT_SUBREDDITS[: config.REDDIT_MAX_SUBS]
    if len(config.REDDIT_SUBREDDITS) > config.REDDIT_MAX_SUBS:
        log.warning(
            "REDDIT_SUBREDDITS has %d entries — polling only the first %d "
            "(politeness cap)", len(config.REDDIT_SUBREDDITS), config.REDDIT_MAX_SUBS,
        )
    return subs


def normalize_reddit_child(child) -> dict | None:
    """One Reddit listing child -> normalized post dict, or None if unusable.

    Pure function (no I/O) so the smoke suite can exercise it hermetically
    against fixtures.
    """
    data = child.get("data") if isinstance(child, dict) else None
    if not isinstance(data, dict):
        return None
    rid = data.get("id")
    title = (data.get("title") or "").strip()
    if not rid or not title:
        return None
    selftext = (data.get("selftext") or "").strip()
    return {
        "reddit_id": str(rid),
        "sub": data.get("subreddit") or "",
        "title": title,
        "author": data.get("author") or "[deleted]",
        "created_utc": float(data.get("created_utc") or 0),
        "permalink": "https://www.reddit.com" + (data.get("permalink") or ""),
        "selftext_excerpt": selftext[:500] or None,
        "matched_water": match_water(title + " " + selftext, disambiguate=True),
    }


async def _reddit_token(client: httpx.AsyncClient) -> str:
    """Client-credentials token, file-cached ahead of expiry (300 s margin)."""
    cached = _read_cache("reddit_token")
    if isinstance(cached, dict) and cached.get("token"):
        age = time.time() - float(cached.get("_fetched_ts") or 0)
        ttl = max(float(cached.get("expires_in") or 3600) - 300, 60)
        if age < ttl:
            return cached["token"]
    basic = base64.b64encode(
        f"{config.REDDIT_CLIENT_ID}:{config.REDDIT_CLIENT_SECRET}".encode()
    ).decode()
    r = await client.post(
        _REDDIT_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}", "User-Agent": config.USER_AGENT},
    )
    if r.status_code != 200:
        raise RuntimeError(f"reddit token: HTTP {r.status_code}")
    tok = r.json()
    if not tok.get("access_token"):
        raise RuntimeError("reddit token: no access_token in response")
    _write_cache("reddit_token", {
        "token": tok["access_token"],
        "expires_in": tok.get("expires_in", 3600),
        "_fetched_ts": time.time(),
    })
    return tok["access_token"]


def _retry_after_s(r: httpx.Response) -> float:
    try:
        return max(1.0, min(float(r.headers.get("Retry-After") or 5), config.REDDIT_RETRY_AFTER_CAP_S))
    except ValueError:
        return 5.0


async def _fetch_hot(client: httpx.AsyncClient, token: str, sub: str) -> httpx.Response:
    """GET /r/{sub}/hot with one 401 re-auth and one 429 Retry-After retry."""
    url = f"https://oauth.reddit.com/r/{sub}/hot?limit={config.REDDIT_LIMIT}"

    def hdrs(tok: str) -> dict:
        return {"Authorization": f"Bearer {tok}", "User-Agent": config.USER_AGENT}

    r = await client.get(url, headers=hdrs(token))
    if r.status_code == 401:
        _write_cache("reddit_token", {})  # drop the bad/expired token
        token = await _reddit_token(client)
        r = await client.get(url, headers=hdrs(token))
    if r.status_code == 429:
        await asyncio.sleep(_retry_after_s(r))
        r = await client.get(url, headers=hdrs(token))
    return r


def _store_posts(conn: sqlite3.Connection, posts: list[dict]) -> None:
    """Upsert normalized posts (dedupe by reddit_id) + prune >30-day-old rows."""
    now = _utcnow()
    for p in posts:
        conn.execute(
            """INSERT INTO reddit_posts
               (reddit_id, sub, title, author, created_utc, permalink,
                selftext_excerpt, matched_water, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(reddit_id) DO UPDATE SET
                 sub=excluded.sub, title=excluded.title, author=excluded.author,
                 created_utc=excluded.created_utc, permalink=excluded.permalink,
                 selftext_excerpt=excluded.selftext_excerpt,
                 matched_water=excluded.matched_water,
                 fetched_at=excluded.fetched_at""",
            (p["reddit_id"], p["sub"], p["title"], p["author"], p["created_utc"],
             p["permalink"], p["selftext_excerpt"], p["matched_water"], now),
        )
    cutoff = time.time() - config.REDDIT_PRUNE_DAYS * 86400
    conn.execute("DELETE FROM reddit_posts WHERE created_utc < ?", (cutoff,))
    conn.commit()


async def poll_reddit(conn: sqlite3.Connection) -> tuple[list[dict], list[str]]:
    """Fetch /hot for each configured sub, upsert+prune the DB, refresh cache.

    Returns (posts, per-sub errors). Raises RuntimeError only when NOTHING
    came back (caller then falls back to the stale cache, weather-style).
    """
    subs = reddit_subreddits()
    if not subs:
        raise RuntimeError("no subreddits configured")
    posts: list[dict] = []
    errors: list[str] = []
    async with _FEED_LOCK:
        async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
            try:
                token = await _reddit_token(client)
            except Exception as e:
                raise RuntimeError(f"auth failed: {e}") from e
            for sub in subs:
                try:
                    r = await _fetch_hot(client, token, sub)
                    if r.status_code != 200:
                        errors.append(f"r/{sub}: HTTP {r.status_code}")
                        continue
                    listing = r.json()
                    for child in listing.get("data", {}).get("children", []):
                        p = normalize_reddit_child(child)
                        if p:
                            posts.append(p)
                except Exception as e:
                    errors.append(f"r/{sub}: {type(e).__name__}: {e}")
        if not posts and errors:
            raise RuntimeError("; ".join(errors))
        _store_posts(conn, posts)
        _write_cache("reddit_feed", {"posts": posts, "_fetched_ts": time.time()})
        return posts, errors


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_from_epoch(v) -> str | None:
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


async def _reddit_section(conn: sqlite3.Connection, water_slug: str | None, days: int) -> dict:
    """Reddit half of the community bundle (stale-flag degradation, never 500)."""
    base = {
        "enabled": reddit_enabled(),
        "subs": reddit_subreddits(),
        "stale": False,
        "fetched_at": None,
        "posts": [],
        "error": None,
    }
    if not base["enabled"]:
        base["notice"] = (
            "Reddit feed: set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in Portainer "
            "to enable (free personal 'script' app)."
        )
        return base

    cached = _read_cache("reddit_feed")
    error: str | None = None
    if not (isinstance(cached, dict) and cached.get("posts") is not None):
        error = "no cached feed yet"
    else:
        age = time.time() - float(cached.get("_fetched_ts") or 0)
        if age > config.TTL_REDDIT:
            try:
                _, errs = await poll_reddit(conn)
                cached = _read_cache("reddit_feed") or cached
                error = "; ".join(errs) if errs else None
            except Exception as e:
                log.warning("reddit poll failed — serving stale: %s", e)
                error = str(e)

    stale = False
    posts: list[dict] = []
    if isinstance(cached, dict) and cached.get("posts") is not None:
        posts = cached["posts"]
        stale = error is not None
        base["fetched_at"] = _iso_from_epoch(cached.get("_fetched_ts"))
    base["stale"] = stale
    base["error"] = error

    cutoff = time.time() - days * 86400
    out = []
    for p in posts:
        if water_slug and p.get("matched_water") != water_slug:
            continue
        if (p.get("created_utc") or 0) < cutoff:
            continue
        q = dict(p)
        q["created_utc"] = _iso_from_epoch(p.get("created_utc"))
        out.append(q)
    out.sort(key=lambda p: p.get("created_utc") or "", reverse=True)
    base["posts"] = out[:100]
    return base


# ---------------------------------------------------------------------------
# Unified bundle
# ---------------------------------------------------------------------------
async def build_community_bundle(
    conn: sqlite3.Connection, water_slug: str | None, days: int
) -> dict:
    """GET /api/community payload: FishBrain imports + Reddit feed, both
    filtered by water (when given) and the recency window."""
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    cur = conn.execute(
        """SELECT * FROM fishbrain_rows
           WHERE date IS NULL OR date >= ?
           ORDER BY CASE WHEN date IS NULL THEN 1 ELSE 0 END, date DESC, id DESC
           LIMIT 200""",
        (cutoff_date,),
    )
    fb_rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["water"] = match_water(d.get("location") or "")
        if water_slug and d["water"] != water_slug:
            continue
        fb_rows.append(d)
    batches = [
        dict(b) for b in conn.execute(
            "SELECT * FROM fishbrain_batches ORDER BY imported_at DESC, batch_id DESC LIMIT 50"
        ).fetchall()
    ]
    reddit = await _reddit_section(conn, water_slug, days)
    return {"fishbrain": {"batches": batches, "rows": fb_rows}, "reddit": reddit}
