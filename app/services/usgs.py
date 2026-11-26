"""USGS NWIS Instant Values — live stage/flow/temp headline per water.

Complements the OGC-API gauge reader in weather.py (which serves the
multi-station "USGS gauges" panel). This service targets the task-verified
Instant Values (IV) endpoint — FREE, no API key — for the headline gauge of
each monitored water:

    new-bullards-bar          -> 11413515  NEW BULLARDS BAR RES (pool stage)
    sacramento-river-westport -> 11389500  SACRAMENTO R A COLUSA
                                 (discharge; stage/temp only if USGS streams them)
                                  secondary 11389390 (upper reach, Moulton Weir)
    collins-lake / loon-lake  -> NO USGS gauge (verified 2026-11-23) -> None

Verified query form (tested 2026-11-25):
    https://waterservices.usgs.gov/nwis/iv/?format=json&sites=<id>
        &parameterCd=00010,00065,00015&period=P7D

Parameter codes (NWIS UnitValues vocabulary):
    00010 = gage height (ft)   00065 = discharge (cfs)   00015 = water temp (deg F)

Observed response shape (verified 2026-11-26 against 11389500):
    value.timeSeries[].variable.variableCode[0].value  -> parameter code
    value.timeSeries[].values[0].value                 -> LIST of
        {"value": "44.90", "qualifiers": ["P"], "dateTime": "2026-11-19T12:45:00.000-08:00"}
    value.timeSeries[].values[0].qualifier             -> legend [{qualifierCode, ...}]

Qualifiers (P = provisional, A = alternate source, ...) are DISPLAYED, never
treated as errors.

Resilience contract (mirrors weather.py):
  * File cache, TTL_USGS (15 min) — don't hammer USGS.
  * Upstream down -> serve cache; cache older than STALE_AFTER_S -> stale=True.
  * Upstream down + no cache -> status="no_data" (never raises, never 500s).
  * No reading in the 7-day window -> status="no_recent_reading" with null
    values (the NBB gauge reports infrequently — never fabricate a value).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from .. import config
from .weather import _read_cache, _write_cache

log = logging.getLogger(__name__)

IV_BASE = "https://waterservices.usgs.gov/nwis/iv/"
PERIOD = "P7D"  # NBB gauge reports infrequently; 7-day window keeps "updated Xh/Xd ago" meaningful

# NWIS parameter code -> payload field (verified mapping, task spec 2026-11-25).
PARAM_FIELD = {
    "00010": "stage_ft",
    "00065": "flow_cfs",
    "00015": "temp_f",
}

# Headline gauge per water. Slugs absent here (collins-lake, loon-lake) have
# no USGS gauge — water_usgs() returns None for them (never fabricate data).
SITE_SPECS = {
    "new-bullards-bar": {
        "primary": {
            "site": "11413515",
            "name": "NEW BULLARDS BAR RES NR NORTH SAN JUAN CA",
            "label": "NBB pool",
            "params": ["00010"],
        },
    },
    "sacramento-river-westport": {
        "primary": {
            "site": "11389500",
            "name": "SACRAMENTO R A COLUSA CA",
            "label": "Sac @ Colusa",
            # Stage (00010) and temp (00015) requested too, but USGS currently
            # streams only 00065 for this site — missing params come back null.
            "params": ["00065", "00010", "00015"],
        },
        "secondary": {
            "site": "11389390",
            "name": "SACRAMENTO R OPPOSITE MOULTON WEIR CA",
            "label": "Upper reach (Moulton Weir)",
            "params": ["00065", "00010"],
        },
    },
}

_client = httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S)


async def aclose() -> None:
    await _client.aclose()


def _parse_dt(s) -> datetime | None:
    """ISO-8601 (USGS emits e.g. 2026-11-19T12:45:00.000-08:00) -> aware dt."""
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # USGS always sends offsets; be safe
    return dt


def parse_iv_payload(payload) -> dict:
    """Parsed IV JSON -> {param_code: {"points": [(dt, float, [quals])], "desc": str|None}}.

    Defensive by construction: bad shapes yield {} (or partial), never raise.
    Points are sorted chronologically so callers can take [-1] / [-2].
    """
    out: dict = {}
    try:
        series = (payload or {}).get("value", {}).get("timeSeries", [])
    except AttributeError:
        return out
    if not isinstance(series, list):
        return out
    for s in series:
        if not isinstance(s, dict):
            continue
        vc = s.get("variable", {}).get("variableCode", [])
        code = vc[0].get("value") if vc and isinstance(vc[0], dict) else None
        if not code or not isinstance(code, str):
            continue
        values = s.get("values") or []
        group = values[0] if values and isinstance(values[0], dict) else {}
        pts = []
        for row in group.get("value", []) or []:
            if not isinstance(row, dict):
                continue
            try:
                v = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            dt = _parse_dt(row.get("dateTime"))
            if dt is None:
                continue
            quals = [str(q) for q in (row.get("qualifiers") or []) if isinstance(q, str)]
            pts.append((dt, v, quals))
        pts.sort(key=lambda p: p[0])
        desc = None
        for leg in group.get("qualifier", []) or []:
            if isinstance(leg, dict) and leg.get("qualifierDescription"):
                desc = str(leg["qualifierDescription"])
                break
        out[code] = {"points": pts, "desc": desc}
    return out


def _assemble(site: str, spec: dict, parsed: dict, status: str, stale: bool,
              now: datetime) -> dict:
    """Fold parsed per-param series into the headline block (spec shape)."""
    block = {
        "site": site,
        "name": spec["name"],
        "label": spec["label"],
        "stage_ft": None,
        "flow_cfs": None,
        "temp_f": None,
        "flow_prev_cfs": None,  # prior reading — feeds the "flow rising" alert
        "as_of_iso": None,
        "age_hours": None,
        "qualifiers": None,
        "status": status,
        "stale": stale,
        "note": None,
    }
    latest_dt = None
    quals: set = set()
    for code, data in parsed.items():
        field = PARAM_FIELD.get(code)
        pts = data.get("points") or []
        if field is None or not pts:
            continue
        last_dt, last_v, last_q = pts[-1]
        block[field] = round(last_v, 2)
        if field == "flow_cfs" and len(pts) >= 2:
            block["flow_prev_cfs"] = round(pts[-2][1], 2)
        if latest_dt is None or last_dt > latest_dt:
            latest_dt = last_dt
        quals.update(last_q)
    if latest_dt is not None:
        block["as_of_iso"] = latest_dt.isoformat(timespec="minutes")
        age_h = (now - latest_dt).total_seconds() / 3600.0
        block["age_hours"] = round(max(age_h, 0.0), 1)
        if quals:
            block["qualifiers"] = "".join(sorted(quals))
    else:
        # Upstream answered (or cache existed) but nothing in the window.
        if status in ("live", "cached", "stale"):
            status = "no_recent_reading"
            block["note"] = "no recent USGS reading (nothing in the last 7 days)"
    block["status"] = status
    return block


async def fetch_site(spec: dict, client: httpx.AsyncClient | None = None) -> dict:
    """Latest IV readings for one site spec. Returns a block dict; never raises."""
    site = spec["site"]
    params = ",".join(spec["params"])
    url = f"{IV_BASE}?format=json&sites={site}&parameterCd={params}&period={PERIOD}"
    owner = client if client is not None else _client
    now = datetime.now(timezone.utc)
    cache_key = f"usgs_iv_{site}"

    parsed = None
    status = "no_data"
    stale = False
    last_err: Exception | None = None
    for attempt in (1, 2):  # one retry on transient failure (short backoff)
        try:
            r = await owner.get(url, headers={"User-Agent": config.USER_AGENT})
            if r.status_code >= 500 and attempt == 1:
                await asyncio.sleep(1.0)
                continue
            r.raise_for_status()
            payload = r.json()
            _write_cache(cache_key, payload)
            parsed = parse_iv_payload(payload)
            status, stale = "live", False
            break
        except Exception as e:  # noqa: BLE001 — resilience contract: degrade, don't raise
            last_err = e
            if attempt == 1:
                await asyncio.sleep(1.0)
                continue
    if parsed is None:
        cached = _read_cache(cache_key)
        if cached is not None:
            parsed = parse_iv_payload(cached)
            # _fetched_ts is an epoch float (weather.py cache convention).
            age = time.time() - cached.get("_fetched_ts", 0)
            stale = age > config.STALE_AFTER_S
            status = "stale" if stale else "cached"
        else:
            log.warning("USGS IV unavailable for %s (%s), no cache: %s",
                        site, spec["label"], last_err)
    return _assemble(site, spec, parsed or {}, status, stale, now)


async def water_usgs(slug: str, client: httpx.AsyncClient | None = None) -> dict | None:
    """Headline USGS block for a water slug. None = no USGS gauge (never fabricate)."""
    spec_map = SITE_SPECS.get(slug)
    if not spec_map:
        return None
    results = await asyncio.gather(*(fetch_site(s, client) for s in spec_map.values()))
    primary, *rest = results
    if rest:
        primary["secondary"] = rest[0]
    return primary
