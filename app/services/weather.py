"""Weather panel data: NWS forecast + Open-Meteo hourly + USGS gauges.

USGS strategy (2026-11-23 redesign, per research-scout dossiers):
Primary:  api.waterdata.usgs.gov OGC API (VERIFIED WORKING from the fleet
          network) — /ogcapi/v1/collections/latest-continuous/items?bbox=…
          then /collections/latest-daily/items?bbox=…. Features are filtered
          to the configured station ID (monitoring_location_id == USGS-<site>).
Fallback: legacy waterservices.usgs.gov layers (IV → DV → UV). These were
          observed DEGRADED from the fleet network on 2026-11-23 (DV 400
          server-side, UV CloudFront 403, IV intermittent) — kept only as a
          last resort; the OGC layer is the one that works.
Every layer parses DEFENSIVELY (USGS emits "NA" strings and occasionally
drops keys): a bad value is skipped, a failed layer falls through to the
next, and a failed gauge never poisons its siblings or the NWS/Open-Meteo
half of the panel. Last cached payload is served with stale=true; with no
cache at all the gauge shows an explicit no_data/error status.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .. import config
from ..knowledge import USGS_STATIONS

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _client_now() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=config.UPSTREAM_TIMEOUT_S,
            headers={"User-Agent": config.USER_AGENT},
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Generic file cache with staleness labelling.
# ---------------------------------------------------------------------------
def _cache_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return config.CACHE_DIR / f"{safe}.json"


def _read_cache(key: str) -> dict | None:
    p = _cache_path(key)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    # Stale only when the cached fetch is older than the staleness threshold —
    # a 2-minute-old cache is still fresh data, not stale.
    age = time.time() - raw.get("_fetched_ts", 0)
    raw["stale"] = age > config.STALE_AFTER_S
    return raw


def _write_cache(key: str, payload: dict) -> None:
    try:
        p = _cache_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as e:
        log.debug("cache write failed (%s): %s", key, e)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso_time(s: str | None) -> datetime | None:
    """Parse ISO-8601 (with Z or offset). Naive stamps are assumed UTC."""
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _age_hours(as_of: str | None) -> float | None:
    t = _parse_iso_time(as_of)
    if t is None:
        return None
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# NWS (unchanged behaviour: points -> gridpoint forecast).
# ---------------------------------------------------------------------------
async def _nws_points(client: httpx.AsyncClient, lat: float, lon: float) -> dict | None:
    key = f"nws_points_{lat:.4f}_{lon:.4f}"
    cached = _read_cache(key)
    if cached and (time.time() - cached.get("_fetched_ts", 0)) < config.TTL_NWS_POINTS:
        return cached
    url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("NWS points failed: %s", e)
        return cached  # may be stale
    payload = {
        "office": data["properties"]["forecastOffice"],
        "grid_id": data["properties"]["gridId"],
        "grid_x": data["properties"]["gridX"],
        "grid_y": data["properties"]["gridY"],
        "forecast_url": data["properties"]["forecast"],
        "raw": data,
        "_fetched_ts": time.time(),
        "stale": False,
    }
    _write_cache(key, payload)
    return payload


async def _nws_gridpoint(client: httpx.AsyncClient, pts: dict) -> dict:
    key = f"nws_fp_{pts['grid_id']}_{pts['grid_x']}_{pts['grid_y']}"
    cached = _read_cache(key)
    if cached and (time.time() - cached.get("_fetched_ts", 0)) < config.TTL_NWS_FORECAST:
        return cached
    try:
        r = await client.get(pts["forecast_url"], timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("NWS gridpoint failed: %s", e)
        return cached or {"error": f"NWS forecast unavailable: {e.__class__.__name__}"}
    periods = []
    for p in data["properties"]["periods"][:7]:
        periods.append({
            "name": p["name"],
            "startTime": p["startTime"],
            "endTime": p["endTime"],
            "temperature": p["temperature"],
            "tempUnit": p["temperatureUnit"],
            "windSpeed": p["windSpeed"],
            "windDirection": p["windDirection"],
            "probabilityOfPrecipitation": (p.get("probabilityOfPrecipitation") or {}).get("value"),
            "shortForecast": p["shortForecast"],
            "detailedForecast": p.get("detailedForecast"),
        })
    props = data["properties"]
    payload = {"updateTime": props.get("updateTime") or props.get("updatedAt") or props.get("updated"),
               "periods": periods,
               "headline": ((props.get("headlines") or [{}])[0].get("text")),
               "_fetched_ts": time.time(), "stale": False}
    _write_cache(key, payload)
    return payload


async def nws_forecast(water: dict) -> dict:
    """NWS forecast for a water body. Never raises; degrades to error dict."""
    client = _client_now()  # shared client — plain use; `async with` would close it
    try:
        pts = await _nws_points(client, water["lat"], water["lon"])
        if not pts or "error" in pts:
            return {"error": "NWS location lookup failed"}
        fp = await _nws_gridpoint(client, pts)
        if "error" in fp:
            return {"error": fp["error"], "office": pts.get("office")}
        ts = fp.get("_fetched_ts")
        return {
            "office": pts["office"],
            "grid": pts["grid_id"],
            "gridX": pts["grid_x"],
            "gridY": pts["grid_y"],
            "headline": fp.get("headline"),
            "updateTime": fp["updateTime"],
            "periods": fp["periods"],
            "stale": bool(fp.get("stale")),
            "fetched_at": (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else None),
        }
    except Exception as e:  # noqa: BLE001 — panel must not 500
        log.warning("NWS forecast unexpected error: %s", e)
        return {"error": f"NWS unavailable: {e.__class__.__name__}"}


# ---------------------------------------------------------------------------
# Open-Meteo (unchanged behaviour: 48 h hourly).
# ---------------------------------------------------------------------------
async def open_meteo_hourly(water: dict) -> dict:
    """48 h forecast. Returns the RAW Open-Meteo payload (nested 'hourly' and
    'daily' dicts — the UI and engine consume wx['hourly'], km/h units) plus
    fetched_at/stale bookkeeping. Never raises; degrades to error dict."""
    client = _client_now()  # shared client — plain use; `async with` would close it
    key = f"om_{water['slug']}"
    cached = _read_cache(key)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={water['lat']}&longitude={water['lon']}"
        "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability"
        "&daily=temperature_2m_max,temperature_2m_min,wind_speed_10m_max"
        "&forecast_days=2&timezone=America/Los_Angeles"
    )
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "hourly" not in data:
            raise ValueError("unexpected Open-Meteo payload")
    except Exception as e:
        log.warning("Open-Meteo failed: %s", e)
        if cached:
            return cached
        return {"error": f"Open-Meteo unavailable: {e.__class__.__name__}"}
    payload = {**data, "_fetched_ts": time.time(), "stale": False, "fetched_at": now_iso()}
    _write_cache(key, payload)
    return payload


# ---------------------------------------------------------------------------
# USGS — OGC API (primary) + legacy waterservices (fallback).
# ---------------------------------------------------------------------------
OGC_API_BASE = "https://api.waterdata.usgs.gov/ogcapi/v1"
# Collections that carry "latest" values. latest-continuous = 15-min sensor
# data; latest-daily = most recent daily row (covers stations that are not
# in the continuous collection). Verified 2026-11-23.
OGC_DATA_COLLECTIONS = ("latest-continuous", "latest-daily")

# Preferred USGS parameter codes per gauge role.
#   00060 discharge (cfs) · 00065 gage height (ft)
ROLE_PARAM_PREF = {
    "stage": ["00065", "00060"],
    "outflow": ["00060", "00065"],
    "primary": ["00060", "00065"],
    "secondary": ["00065", "00060"],
    "indicator": ["00060", "00065"],
}
DEFAULT_PARAM_PREF = ["00060", "00065"]

UNIT_LABELS = {
    "ft": "ft",
    "ft^3/s": "cfs",
    "degC": "°C",
    "Acre-ft": "acre-ft",
    "_FNU": "FNU",
    "uS/cm": "µS/cm",
    "mg/l": "mg/L",
    "pH Units": "pH",
}
PARAM_NAMES = {
    "00060": "Discharge",
    "00065": "Gage height",
    "00010": "Temperature",
    "00054": "Storage",
    "00095": "Conductivity",
    "00300": "Total suspended solids",
    "00400": "pH",
    "63160": "Elevation above NAVD88",
    "63680": "Turbidity",
}

NO_RECENT_DATA_AFTER_H = 30 * 24  # older than 30 days -> historical, not live


def _water_gauges(water: dict) -> list[dict]:
    """Gauge specs for a water (DB stores JSON text; routers may pass a list)."""
    g = water.get("gauges")
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except ValueError:
            g = []
    return g if isinstance(g, list) else []


def _ogc_bbox(site: str) -> str | None:
    """bbox (west,south,east,north) padded around the station's official coords."""
    info = USGS_STATIONS.get(site)
    if not info:
        return None
    pad = 0.03
    return (f"{info['lon'] - pad:.6f},{info['lat'] - pad:.6f},"
            f"{info['lon'] + pad:.6f},{info['lat'] + pad:.6f}")


async def _fetch_ogc_features(client: httpx.AsyncClient, collection: str, bbox: str) -> list | None:
    """GET one OGC collection slice. Returns feature list, or None on error."""
    url = f"{OGC_API_BASE}/collections/{collection}/items?bbox={bbox}&limit=100"
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        feats = data.get("features")
        return feats if isinstance(feats, list) else []
    except Exception as e:  # noqa: BLE001 — fall through to next layer
        log.warning("OGC %s fetch failed (bbox=%s): %s", collection, bbox, e)
        return None


def _ogc_candidates(features: list, site: str) -> list[dict]:
    """Extract parseable value rows for one station. Defensive: USGS emits
    'NA' strings and occasionally drops keys — bad rows are skipped, never raised."""
    out = []
    for f in features:
        try:
            p = f.get("properties") or {}
            if p.get("monitoring_location_id") != f"USGS-{site}":
                continue
            raw = p.get("value")
            if raw is None or str(raw).upper() == "NA":
                continue
            val = float(raw)
            if val != val or val in (float("inf"), float("-inf")):  # NaN/inf
                continue
            out.append({
                "param": str(p.get("parameter_code", "")),
                "value": val,
                "unit": p.get("unit_of_measure"),
                "time": p.get("time"),
            })
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _finish_gauge_value(site: str, role: str, chosen: dict, source: str) -> dict:
    """Normalize a chosen value row into the gauge payload shape."""
    unit_raw = chosen.get("unit") or ""
    param_code = chosen.get("param") or "?"
    payload = {
        "site": site,
        "role": role,
        "value": chosen["value"],
        "unit": UNIT_LABELS.get(unit_raw, unit_raw or "?"),
        "parameter": PARAM_NAMES.get(param_code, param_code),
        "as_of": chosen.get("time"),
        "source": source,
        "stale": False,
        "status": "live",
    }
    if unit_raw == "ft":
        payload["stage_ft"] = chosen["value"]
    elif unit_raw == "ft^3/s":
        payload["discharge_cfs"] = chosen["value"]
    age_h = _age_hours(chosen.get("time"))
    if age_h is not None:
        if age_h > config.STALE_AFTER_S / 3600.0:
            payload["stale"] = True
        if age_h > NO_RECENT_DATA_AFTER_H:
            payload["status"] = "no_recent_data"
            payload["note"] = (
                f"Most recent value is {int(age_h // 24)} days old — "
                "historical, not live."
            )
    return payload


async def _ogc_station_value(client: httpx.AsyncClient, site: str, role: str) -> tuple[dict | None, str | None]:
    """Query the OGC API for one station (latest-continuous then latest-daily).
    Returns (normalized value dict | None, error note | None). Never raises."""
    bbox = _ogc_bbox(site)
    if bbox is None:
        return None, f"station {site} missing from USGS_STATIONS registry"
    pref = ROLE_PARAM_PREF.get(role, DEFAULT_PARAM_PREF)
    last_err = "no OGC collection returned data"
    for collection in OGC_DATA_COLLECTIONS:
        feats = await _fetch_ogc_features(client, collection, bbox)
        if feats is None:
            last_err = f"OGC {collection} unreachable"
            continue
        cands = _ogc_candidates(feats, site)
        if not cands:
            last_err = (f"station {site} not present in OGC {collection} "
                        "collection (no recent data)")
            continue
        chosen = None
        for code in pref:
            matching = [c for c in cands if c["param"] == code]
            if matching:
                matching.sort(key=lambda c: c["time"] or "", reverse=True)
                chosen = matching[0]
                break
        if chosen is None:
            cands.sort(key=lambda c: c["time"] or "", reverse=True)
            chosen = cands[0]
        return _finish_gauge_value(site, role, chosen, f"ogc:{collection}"), None
    return None, last_err


# ---- legacy waterservices.usgs.gov layers (last resort; often degraded) ----

async def _fetch_usgs_iv(client: httpx.AsyncClient, site: str) -> dict | None:
    """Instantaneous values. Defensive parse — returns None on any problem."""
    url = (f"https://waterservices.usgs.gov/nwis/iv/?site={site}"
           "&format=json&sitesPerRequest=1")
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.warning("USGS IV failed for %s: %s", site, e)
        return None
    try:
        ds = payload["value"]["timeSeries"][0]
        last = ds["values"][0][-1]
        val = float(last["value"])  # may raise on "NA" -> caught below
        return {
            "stage_ft": val if ds["variable"]["variableCode"][0]["value"] == "00065" else None,
            "discharge_cfs": val if ds["variable"]["variableCode"][0]["value"] == "00060" else None,
            "as_of": last["dateTime"]["dateTimes"][0]["value"],
            "series": None,
            "source": "waterservices:iv",
        }
    except (KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("USGS IV parse failed for %s: %s", site, e)
        return None


async def _fetch_usgs_dv(client: httpx.AsyncClient, site: str) -> dict | None:
    """7-day daily values (gives a stage trend). Defensive parse."""
    url = (f"https://waterservices.usgs.gov/nwis/dv/?site={site}"
           "&format=json&period=7&sitesPerRequest=1")
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.warning("USGS DV failed for %s: %s", site, e)
        return None
    try:
        ts = payload["value"]["timeSeries"]
        stage_pts, dis_pts = [], []
        for s in ts:
            code = s["variable"]["variableCode"][0]["value"]
            for v in s["values"][0]:
                try:
                    val = float(v["value"])
                except (KeyError, TypeError, ValueError):
                    continue  # "NA" or missing value — skip, don't raise
                t = v["dateTime"]["dateTimes"][0]["value"]
                (stage_pts if code == "00065" else dis_pts).append((t, val))
        if not stage_pts and not dis_pts:
            return None
        out = {"series": {"stage": stage_pts, "discharge": dis_pts}, "source": "waterservices:dv"}
        if stage_pts:
            out["stage_ft"] = stage_pts[-1][1]
            out["as_of"] = stage_pts[-1][0]
        if dis_pts:
            out["discharge_cfs"] = dis_pts[-1][1]
            out.setdefault("as_of", dis_pts[-1][0])
        return out
    except (KeyError, IndexError, TypeError) as e:
        log.warning("USGS DV parse failed for %s: %s", site, e)
        return None


async def _fetch_usgs_uv(client: httpx.AsyncClient, site: str) -> dict | None:
    """Legacy updated-values page (last resort). Already exception-safe."""
    url = f"https://waterdata.usgs.gov/nwis/uv?site_no={site}&legacy=1"
    try:
        r = await client.get(url, timeout=config.UPSTREAM_TIMEOUT_S,
                             headers={"Referer": "https://waterdata.usgs.gov/"})
        r.raise_for_status()
        txt = r.text
        import re
        m = re.search(r"Gage height[^0-9\-]*([0-9]+\.?[0-9]*)\s*ft", txt)
        if m:
            return {"stage_ft": float(m.group(1)), "as_of": None, "source": "waterdata:uv"}
        m = re.search(r"Discharge[^0-9\-]*([0-9,]+\.?[0-9]*)\s*cubic feet per second", txt)
        if m:
            return {"discharge_cfs": float(m.group(1).replace(",", "")), "as_of": None,
                    "source": "waterdata:uv"}
        return None
    except Exception as e:
        log.warning("USGS UV failed for %s: %s", site, e)
        return None


def _legacy_pick(legacy: dict, role: str) -> tuple[float | None, str, str]:
    """Choose (value, unit, parameter) from a legacy payload by role preference."""
    if role in ("stage", "secondary"):
        if legacy.get("stage_ft") is not None:
            return legacy["stage_ft"], "ft", "Gage height"
        if legacy.get("discharge_cfs") is not None:
            return legacy["discharge_cfs"], "cfs", "Discharge"
    else:  # outflow / primary / indicator
        if legacy.get("discharge_cfs") is not None:
            return legacy["discharge_cfs"], "cfs", "Discharge"
        if legacy.get("stage_ft") is not None:
            return legacy["stage_ft"], "ft", "Gage height"
    return None, "?", "?"


def _legacy_to_norm(site: str, role: str, legacy: dict) -> dict | None:
    val, unit, param = _legacy_pick(legacy, role)
    if val is None:
        return None
    payload = {
        "site": site,
        "role": role,
        "value": val,
        "unit": unit,
        "parameter": param,
        "as_of": legacy.get("as_of"),
        "source": legacy.get("source", "legacy"),
        "stale": False,
        "status": "live",
    }
    if unit == "ft":
        payload["stage_ft"] = val
    elif unit == "cfs":
        payload["discharge_cfs"] = val
    age_h = _age_hours(legacy.get("as_of"))
    if age_h is None:
        payload["stale"] = True  # unknown age — label conservatively
    elif age_h > config.STALE_AFTER_S / 3600.0:
        payload["stale"] = True
    if age_h is not None and age_h > NO_RECENT_DATA_AFTER_H:
        payload["status"] = "no_recent_data"
        payload["note"] = f"Most recent value is {int(age_h // 24)} days old — historical, not live."
    # 7-day stage delta (trend note for the recommender)
    series = legacy.get("series") or {}
    st = series.get("stage") or []
    if len(st) >= 2:
        newest_t = _parse_iso_time(st[-1][0])
        oldest_t = _parse_iso_time(st[0][0])
        if newest_t and oldest_t and (newest_t - oldest_t).days >= 3:
            payload["delta_ft_7d"] = round(st[-1][1] - st[0][1], 2)
    return payload


async def _legacy_usgs_value(client: httpx.AsyncClient, site: str, role: str) -> dict | None:
    """Legacy IV → DV → UV chain. Never raises; returns normalized value or None."""
    try:
        for fetcher in (_fetch_usgs_iv, _fetch_usgs_dv, _fetch_usgs_uv):
            legacy = await fetcher(client, site)
            if legacy:
                norm = _legacy_to_norm(site, role, legacy)
                if norm:
                    return norm
    except Exception as e:  # noqa: BLE001 — belt and braces
        log.warning("legacy USGS chain failed for %s: %s", site, e)
    return None


async def _gauge_payload(water: dict, spec: dict, client: httpx.AsyncClient) -> dict:
    """Resolve one gauge: OGC API → legacy layers → cache → explicit no_data.
    Isolated: this function never raises, so one bad gauge can't hurt siblings."""
    site = str(spec.get("site", ""))
    role = spec.get("role", "primary")
    base = {
        "site": site,
        "role": role,
        "label": spec.get("label") or USGS_STATIONS.get(site, {}).get("name", site),
        "official_name": USGS_STATIONS.get(site, {}).get("official_name"),
        "spec_note": spec.get("note"),
    }
    cache_key = f"usgs_gauge_{site}_{role}"

    # 1) OGC API (verified-working endpoint)
    val, err = await _ogc_station_value(client, site, role)
    if val:
        out = {**base, **val, "fetched_at": now_iso()}
        _write_cache(cache_key, out)
        return out

    # 2) legacy waterservices layers (often degraded; last resort)
    legacy_val = await _legacy_usgs_value(client, site, role)
    if legacy_val:
        out = {**base, **legacy_val, "fetched_at": now_iso()}
        if err:
            out["note"] = f"OGC API: {err}; served from legacy layer."
        _write_cache(cache_key, out)
        return out

    # 3) last cached payload, labelled stale
    cached = _read_cache(cache_key)
    if cached:
        out = {k: v for k, v in cached.items() if k not in ("_fetched_ts",)}
        out.update(base)
        out["stale"] = True
        out["status"] = "stale_cache"
        out["note"] = f"Last cached value (fetched {out.get('fetched_at', '?')}). " \
                      f"Live fetch failed: {err}"
        return out

    # 4) nothing at all — explicit, honest no_data
    return {
        **base,
        "status": "no_data",
        "value": None,
        "unit": None,
        "parameter": None,
        "as_of": None,
        "source": None,
        "stale": False,
        "note": f"No live or cached data. {err}",
        "fetched_at": now_iso(),
    }


async def usgs_gauges(water: dict, client: httpx.AsyncClient | None = None) -> dict:
    """All gauges configured for a water body.

    Returns {"gauges": [...], "fetched_at": ...} where each gauge carries its
    own status (live / no_recent_data / stale_cache / no_data). A water with
    no gauges (Loon Lake — verified) gets an explanatory note.
    """
    specs = _water_gauges(water)
    if not specs:
        return {
            "gauges": [],
            "note": "No public USGS gauge for this water (verified 2026-11-23).",
            "fetched_at": now_iso(),
        }
    cl = client or _client_now()  # shared client — never closed here (lifespan owns it)
    try:
        results = await asyncio.gather(
            *[_gauge_payload(water, s, cl) for s in specs]
        )
    except Exception as e:  # noqa: BLE001 — should not happen; degrade anyway
        log.exception("usgs_gauges gather failed unexpectedly")
        return {"gauges": [], "error": f"USGS gauge fetch failed: {e.__class__.__name__}",
                "fetched_at": now_iso()}
    return {"gauges": list(results), "fetched_at": now_iso()}


# ---------------------------------------------------------------------------
# Bundle for the weather panel.
# ---------------------------------------------------------------------------
async def weather_bundle(water: dict) -> dict:
    client = _client_now()  # shared client — plain use; `async with` would close it
    nws, om, usgs = await asyncio.gather(
        nws_forecast(water),
        open_meteo_hourly(water),
        usgs_gauges(water, client),
    )
    return {"nws": nws, "open_meteo": om, "usgs": usgs, "water": water["slug"],
            "generated_at": now_iso()}
