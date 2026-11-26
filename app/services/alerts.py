"""Condition alerts derived from live weather + USGS + static stocking data.

Each alert is a dict:
    {"key": str, "signature": str, "severity": "info"|"warn", "message": str}

  * key       — stable per alert TYPE (dedupe handle, e.g. "rain_incoming").
  * signature — coarse fingerprint of the underlying CONDITION. While the
                condition persists the signature stays constant, so clients
                (localStorage) can suppress repeats without re-firing; when
                the condition changes materially the signature changes and
                the alert legitimately fires again.
  * severity  — display styling only.

derive_alerts() is PURE (no I/O) — easy to test, safe to call per request.
maybe_mirror() is the optional best-effort mirror to HERMES_CHAT_ENDPOINT:
in-app alerts are PRIMARY; the mirror is fire-and-forget, dedupes per
process lifetime, and swallows every failure (short timeout, no retries).
"""
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from .. import config, knowledge
from .weather import HPA_TO_INHG

log = logging.getLogger(__name__)

# --- thresholds (heuristic, documented per task spec) -----------------------
# "Pressure dropping in ~N h": fire when the 24 h-ahead low is at least this
# far below current pressure (~0.015 inHg — a real frontal signal, not noise).
PRESSURE_DROP_ALERT_HPA = 0.5
PRESSURE_AHEAD_HOURS = 24
# "Rain incoming": first hour within the lookahead whose precip probability
# crosses this threshold.
RAIN_PROB_THRESHOLD_PCT = 50
RAIN_LOOKAHEAD_HOURS = 12
# "Flow rising sharply": latest USGS reading vs the PRIOR reading — both a
# percentage AND an absolute floor (low-flow rivers swing % wildly on tiny
# deltas; 300 cfs is a real access/strike-zone change on the Sac).
FLOW_RISE_PCT = 15.0
FLOW_RISE_MIN_CFS = 300.0

# Process-lifetime dedupe for the optional chat mirror (signature -> seen).
_MIRRORED: set[str] = set()


def _local_now(om: dict | None) -> tuple[datetime, timezone]:
    """Local now at the water (offset from the OM payload; UTC if absent)."""
    offset = (om or {}).get("utc_offset_seconds") or 0
    tz = timezone(timedelta(seconds=offset))
    return datetime.now(timezone.utc).astimezone(tz), tz


def _hourly_pairs(om: dict, var: str) -> list[tuple[datetime, float]]:
    """[(aware local dt, value)] for one hourly variable; junk rows dropped."""
    h = (om or {}).get("hourly") or {}
    times = h.get("time") or []
    vals = h.get(var) or []
    offset = (om or {}).get("utc_offset_seconds") or 0
    tz = timezone(timedelta(seconds=offset))
    out = []
    for t, v in zip(times, vals):
        if v is None:
            continue
        try:
            dt = datetime.fromisoformat(str(t))
            fv = float(v)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        out.append((dt, fv))
    return out


def _pressure_drop_alert(om: dict, local_now: datetime) -> dict | None:
    pairs = _hourly_pairs(om, "pressure_msl")
    cur = None
    for dt, p in pairs:
        if dt <= local_now:
            cur = p
    if cur is None:
        return None
    horizon = local_now + timedelta(hours=PRESSURE_AHEAD_HOURS)
    lows = [(dt, p) for dt, p in pairs if local_now < dt <= horizon]
    if not lows:
        return None
    min_dt, min_p = min(lows, key=lambda x: x[1])
    drop = cur - min_p
    if drop < PRESSURE_DROP_ALERT_HPA:
        return None
    hours_ahead = max(int(round((min_dt - local_now).total_seconds() / 3600.0)), 1)
    return {
        "key": "pressure_drop",
        "signature": min_dt.strftime("%Y-%m-%d"),  # same low-pressure day = same condition
        "severity": "info",
        "message": (f"Pressure dropping in ~{hours_ahead} h "
                    f"(-{drop * HPA_TO_INHG:.2f} inHg to {min_p:.0f} hPa)"),
    }


def _rain_alert(om: dict, local_now: datetime) -> dict | None:
    pairs = _hourly_pairs(om, "precipitation_probability")
    limit = local_now + timedelta(hours=RAIN_LOOKAHEAD_HOURS)
    for dt, p in pairs:
        if dt <= local_now:
            continue
        if dt > limit:
            break
        if p >= RAIN_PROB_THRESHOLD_PCT:
            hours_ahead = max(int(round((dt - local_now).total_seconds() / 3600.0)), 1)
            return {
                "key": "rain_incoming",
                "signature": dt.strftime("%Y-%m-%d"),  # same onset day = same condition
                "severity": "warn",
                "message": f"Rain incoming in ~{hours_ahead} h (up to {int(p)}% chance)",
            }
    return None


def _stocking_alert(slug: str, today: date) -> dict | None:
    tomorrow = today + timedelta(days=1)
    iso = tomorrow.isoformat()
    if iso in knowledge.STOCKING_DATES.get(slug, []):
        return {
            "key": "stocking_tomorrow",
            "signature": iso,  # the stocking date itself
            "severity": "info",
            "message": "Stocking day tomorrow (per stocked-water schedule)",
        }
    return None


def _flow_alert(usgs: dict | None) -> dict | None:
    if not usgs:
        return None
    cur, prev = usgs.get("flow_cfs"), usgs.get("flow_prev_cfs")
    if not cur or not prev or prev <= 0:
        return None
    pct = (cur - prev) / prev * 100.0
    if pct >= FLOW_RISE_PCT and (cur - prev) >= FLOW_RISE_MIN_CFS:
        label = usgs.get("label") or "River"
        return {
            "key": "flow_rising",
            # Bucketed flow level: persists while flow stays in the same
            # ~100 cfs band, re-fires when it climbs into a new band.
            "signature": f"f{int(cur // 100)}",
            "severity": "warn",
            "message": (f"Flow rising sharply: {prev:,.0f} -> {cur:,.0f} cfs "
                        f"(+{pct:.0f}% vs prior reading) at {label}"),
        }
    return None


def derive_alerts(slug: str, om: dict | None = None, usgs: dict | None = None,
                  *, today: date | None = None) -> list[dict]:
    """All alerts for a water. Never raises; may return [].

    om    = Open-Meteo payload (or error dict / None when offline).
    usgs  = headline block from services.usgs.water_usgs() (or None).
    today = local calendar date (defaults to local-now via om offset).
    """
    local_now, _ = _local_now(om)
    if today is None:
        today = local_now.date()
    alerts: list[dict] = []
    if om and "hourly" in om:
        pd = _pressure_drop_alert(om, local_now)
        if pd:
            alerts.append(pd)
        ra = _rain_alert(om, local_now)
        if ra:
            alerts.append(ra)
    sa = _stocking_alert(slug, today)
    if sa:
        alerts.append(sa)
    fa = _flow_alert(usgs)
    if fa:
        alerts.append(fa)
    return alerts


async def maybe_mirror(alerts_by_water: dict[str, list[dict]]) -> None:
    """Optional mirror of NEW alert signatures to HERMES_CHAT_ENDPOINT.

    In-app alerts are primary; this is best-effort polish. No-op unless the
    endpoint is configured. Swallows every error and uses a short timeout —
    it must never slow down or break the request that triggered it.
    """
    if not config.HERMES_CHAT_ENDPOINT:
        return
    lines = []
    for water, alerts in alerts_by_water.items():
        for a in alerts:
            sig = f"{water}:{a['key']}:{a['signature']}"
            if sig in _MIRRORED:
                continue
            _MIRRORED.add(sig)
            lines.append(f"[{water}] {a['message']}")
    if len(_MIRRORED) > 2000:  # bound the set over long uptimes
        _MIRRORED.clear()
    if not lines:
        return
    msg = "Chasing Tail(s) condition alerts: " + "; ".join(lines[:6])
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                config.HERMES_CHAT_ENDPOINT,
                json={"message": msg},
                headers={"User-Agent": config.USER_AGENT},
            )
    except Exception as e:  # noqa: BLE001 — mirror is fire-and-forget
        log.debug("alert mirror failed (ignored): %s", e)
