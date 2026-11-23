"""Weather + water-level aggregation with file cache and graceful degradation.

Sources:
- NWS API (api.weather.gov): points -> gridpoint forecast. Authoritative
  text forecast.
- Open-Meteo: hourly temp/wind/gusts/precip-prob (numeric, for the UI chart
  and the recommendation engine's weather inputs).
- USGS Water Services: reservoir levels. Layered:
    1. /nwis/iv/  (instantaneous values — real-time)
    2. /nwis/dv/  (daily values, last 7 days)
    3. waterdata.usgs.gov/nwis/uv (updated values — legacy service)
  Each layer is cached; on total failure the last cached payload is served
  with stale=true. If nothing is cached, usgs=null with an error note.

Cache layout: CACHE_DIR/<key>.json = {"fetched_at": epoch, "payload": ...}
"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from .. import config

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=config.UPSTREAM_TIMEOUT_S,
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# File cache
# ---------------------------------------------------------------------------
def _cache_path(key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return config.CACHE_DIR / f"{digest}.json"


def _cache_read(key: str) -> tuple[float, dict] | None:
    p = _cache_path(key)
    try:
        raw = json.loads(p.read_text())
        return raw["fetched_at"], raw["payload"]
    except (OSError, ValueError, KeyError):
        return None


def _cache_write(key: str, payload: dict) -> None:
    try:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    except OSError as e:
        log.warning("cache write failed (%s): %s", key, e)


def _wrap(payload: dict, ttl: float, key: str) -> dict:
    """Return payload with freshness annotations; fall back to stale cache."""
    now = time.time()
    cached = _cache_read(key)
    if cached is not None:
        fetched_at, cached_payload = cached
        if now - fetched_at <= ttl:
            return {**payload, "fetched_at": fetched_at, "stale": False}
        # Fresh fetch failed or was skipped: serve the old copy, flagged.
        if now - fetched_at <= config.STALE_AFTER_S:
            return {**cached_payload, "fetched_at": fetched_at, "stale": True}
    return {**payload, "fetched_at": now, "stale": False}


async def _get_json(client: httpx.AsyncClient, url: str, tries: int = 2,
                    timeout: float | None = None) -> dict | None:
    last_exc: Exception | None = None
    for i in range(tries):
        try:
            r = await client.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_exc = RuntimeError(f"HTTP {r.status_code} from {url}")
        except Exception as e:  # noqa: BLE001 — network layer, report and move on
            last_exc = e
        if i + 1 < tries:
            await asyncio.sleep(1.5 * (i + 1))
    if last_exc:
        log.info("upstream fetch failed (%s): %s", url, last_exc)
    return None


# ---------------------------------------------------------------------------
# NWS
# ---------------------------------------------------------------------------
async def nws_forecast(water: dict) -> dict:
    """Full NWS forecast for a water body, with grid mapping cached 7d."""
    client = http()
    pt_key = f"nws-points:{water['slug']}"
    pt_cached = _cache_read(pt_key)
    if pt_cached and time.time() - pt_cached[0] <= config.TTL_NWS_POINTS:
        points = pt_cached[1]
    else:
        points = await _get_json(
            client, f"https://api.weather.gov/points/{water['lat']},{water['lon']}"
        )
        if points is None:
            if pt_cached:  # serve stale mapping
                points = pt_cached[1]
            else:
                return {"error": "NWS points lookup failed and no cached mapping."}
        else:
            _cache_write(pt_key, points)

    props = points.get("properties", {})
    fc_url = props.get("forecast")
    if not fc_url:
        return {"error": "NWS points response had no forecast URL.", "office": props.get("gridId")}

    fc_key = f"nws-forecast:{water['slug']}"
    fc = await _get_json(client, fc_url)
    if fc is None:
        cached = _cache_read(fc_key)
        if cached:
            fetched_at, payload = cached
            stale = time.time() - fetched_at > config.TTL_NWS_FORECAST
            return {"office": props.get("gridId"), "grid": props.get("gridX"), "gridY": props.get("gridY"),
                    "periods": payload.get("periods", []), "headline": payload.get("headline"),
                    "fetched_at": fetched_at, "stale": stale}
        return {"error": "NWS forecast fetch failed and no cached forecast."}

    _cache_write(fc_key, {"periods": fc["properties"]["periods"], "headline": fc["properties"].get("headline")})
    return _wrap(
        {
            "office": props.get("gridId"),
            "grid": props.get("gridX"),
            "gridY": props.get("gridY"),
            "headline": fc["properties"].get("headline"),
            "periods": fc["properties"]["periods"],
        },
        config.TTL_NWS_FORECAST,
        fc_key,
    )


# ---------------------------------------------------------------------------
# Open-Meteo
# ---------------------------------------------------------------------------
async def open_meteo_hourly(water: dict) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={water['lat']}&longitude={water['lon']}"
        "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability"
        "&daily=temperature_2m_max,temperature_2m_min,wind_speed_10m_max"
        "&forecast_days=2&timezone=America%2FLos_Angeles"
    )
    client = http()
    key = f"open-meteo:{water['slug']}"
    data = await _get_json(client, url)
    if data is None:
        cached = _cache_read(key)
        if cached:
            fetched_at, payload = cached
            stale = time.time() - fetched_at > config.TTL_OPEN_METEO
            return {**payload, "fetched_at": fetched_at, "stale": stale}
        return {"error": "Open-Meteo fetch failed and no cached data."}
    _cache_write(key, data)
    return _wrap(data, config.TTL_OPEN_METEO, key)


# ---------------------------------------------------------------------------
# USGS (layered)
# ---------------------------------------------------------------------------
def _parse_iv(payload: dict) -> dict | None:
    ts = payload.get("value", {}).get("timeSeries", [])
    out: dict = {}
    for t in ts:
        desc = t.get("variable", {}).get("variableDescription", "")
        vals = t.get("values", [])
        if not vals:
            continue
        last = vals[-1]
        if "Stage" in desc or "Gage height" in desc.lower():
            out["stage_ft"] = float(last["value"])
            out["as_of"] = last["dateTime"]
        elif "Storage" in desc:
            out["storage_acft"] = float(last["value"])
            out.setdefault("as_of", last["dateTime"])
    return out or None


def _parse_dv(payload: dict) -> dict | None:
    ts = payload.get("value", {}).get("timeSeries", [])
    out: dict = {}
    for t in ts:
        desc = t.get("variable", {}).get("variableDescription", "")
        vals = t.get("values", [])
        if not vals:
            continue
        last = vals[-1]
        if "Stage" in desc or "Gage height" in desc.lower():
            out["stage_ft"] = float(last["value"])
            out["as_of"] = last["dateTime"]
        elif "Storage" in desc:
            out["storage_acft"] = float(last["value"])
            out.setdefault("as_of", last["dateTime"])
    return out or None


async def _usgs_layer(client: httpx.AsyncClient, site: str) -> dict | None:
    """Try IV, then DV, then UV. Return normalized gauge data + source.

    Short per-attempt timeout: when USGS is unhealthy we don't want the whole
    weather panel to hang for minutes — the cache/stale path covers gaps.
    """
    usgs_timeout = 10.0
    # Layer 1: instantaneous values
    data = await _get_json(
        client,
        f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites={site}&parameterCd=00065,00060",
        timeout=usgs_timeout,
    )
    if data:
        parsed = _parse_iv(data)
        if parsed:
            return {**parsed, "source": "iv"}
    # Layer 2: daily values, last 7 days
    end = date.today()
    start = end - timedelta(days=7)
    data = await _get_json(
        client,
        "https://waterservices.usgs.gov/nwis/dv/?format=json&sites={}&parameterCd=00065,00060"
        "&startDate={}&endDate={}".format(site, start.isoformat(), end.isoformat()),
        timeout=usgs_timeout,
    )
    if data:
        parsed = _parse_dv(data)
        if parsed:
            return {**parsed, "source": "dv"}
    # Layer 3: legacy updated-values service (CSV)
    try:
        r = await client.get(
            "https://waterdata.usgs.gov/nwis/uv",
            params={
                "cb_00065": "on", "cb_00060": "on", "format": "csv",
                "site_no": site, "period": "D7",
            },
            timeout=usgs_timeout,
        )
        if r.status_code == 200:
            rows = [ln.split(",") for ln in r.text.strip().splitlines()[1:]]
            stage = storage = as_of = None
            for row in rows:
                if len(row) >= 6:
                    try:
                        if row[4].strip() == "00065" and row[5].strip():
                            stage, as_of = float(row[5]), row[3]
                        elif row[4].strip() == "00060" and row[5].strip():
                            storage = float(row[5])
                            as_of = as_of or row[3]
                    except ValueError:
                        continue
            if stage is not None:
                return {"stage_ft": stage, "storage_acft": storage, "as_of": as_of, "source": "uv"}
    except Exception as e:  # noqa: BLE001
        log.info("USGS UV layer failed: %s", e)
    return None


async def usgs_level(water: dict) -> dict | None:
    """Reservoir level for waters with a USGS site; None if no site configured."""
    site = water.get("usgs_site")
    if not site:
        return None
    key = f"usgs:{site}"
    client = http()
    parsed = await _usgs_layer(client, site)
    if parsed:
        _cache_write(key, parsed)
        return _wrap(parsed, config.TTL_USGS, key)
    cached = _cache_read(key)
    if cached:
        fetched_at, payload = cached
        stale = time.time() - fetched_at > config.TTL_USGS
        return {**payload, "fetched_at": fetched_at, "stale": stale,
                "note": "live fetch failed; showing last cached reading"}
    return {"site": site, "error": "USGS fetch failed and no cached reading.", "stale": True}


# ---------------------------------------------------------------------------
# Aggregated endpoint payload
# ---------------------------------------------------------------------------
async def weather_bundle(water: dict) -> dict:
    nws, om, usgs = await asyncio.gather(
        nws_forecast(water), open_meteo_hourly(water), usgs_level(water)
    )
    return {
        "water": {
            "slug": water["slug"], "name": water["name"], "location": water["location"],
            "kind": water["kind"], "lat": water["lat"], "lon": water["lon"],
        },
        "nws": nws,
        "open_meteo": om,
        "usgs": usgs,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
