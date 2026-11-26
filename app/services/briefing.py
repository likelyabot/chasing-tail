"""Per-trip briefing composition: plan + conditions + gear in one payload.

Backs GET /api/trips/<id>/briefing. Aggregates the three existing data
sources so a single place answers "what to bring" + "what/when to target":

  * PLAN       — app.services.recommend for the trip's water + date:
                 target species (with pixel-art sprites via
                 app/services/species_icons.py), regulations, stocking,
                 recommended tactics/windows, kayak verdict, reminders.
  * CONDITIONS — the weather/conditions endpoints' data for the trip:
                 Open-Meteo temp/wind/rain + sunrise/sunset, barometric
                 pressure + trend, lunar phase (pure local calc), and USGS
                 NWIS instant values split into water level (stage) and
                 flow (discharge).
  * GEAR       — the user's tackle (db.get_gear, flattened) plus
                 conditional additions from app/services/gear_rules
                 (every item carries a reason).

Planned trips (future date inside the 48 h forecast window) get
conditions.weather.horizon = "forecast"; logged trips (past date) get the
latest snapshot labelled "last_known" — there is no historical weather
API in this stack, so the snapshot's generated_at tells the reader how
fresh it is.

Resilience contract: both upstreams (Open-Meteo, USGS) are independently
cached and degrade to None/error dicts — this module never raises for
them. The router wraps the whole composition in a last-resort guard so
the endpoint can still never 500.
"""
import asyncio
import sqlite3
from datetime import date, datetime, timezone

from .. import db
from . import gear_rules
from . import lunar
from . import recommend as rec
from . import species_icons
from . import usgs as usgs_svc
from . import weather as wx


# --- conditions ------------------------------------------------------------

def _nums(values):
    """Numeric values only (drops None/junk; bools are not numbers here)."""
    return [v for v in (values or [])
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _date_covered(times, trip_date: date) -> bool:
    """True when the trip date falls inside the payload's hourly window."""
    days = [str(t)[:10] for t in (times or []) if str(t)[:10].count("-") == 2]
    if not days:
        return False
    iso = trip_date.isoformat()
    return min(days) <= iso <= max(days)


def summarize_weather(om: dict | None, trip_date: date | None) -> dict:
    """Condense the Open-Meteo payload to the briefing's weather block.

    Pure over the payload (works on fresh AND cached data). Missing
    upstream -> source=None + a note; never raises.
    """
    if not isinstance(om, dict) or "hourly" not in om:
        return {"source": None, "horizon": None,
                "note": "no weather data (upstream unavailable or errored)"}
    h = om.get("hourly") or {}
    temps = _nums(h.get("temperature_2m"))
    winds = _nums(h.get("wind_speed_10m"))
    probs = _nums(h.get("precipitation_probability"))
    d = om.get("daily") or {}

    def first_day(key):
        v = d.get(key)
        return v[0] if isinstance(v, list) and v else None

    horizon = ("forecast" if trip_date and _date_covered(h.get("time"), trip_date)
               else "last_known")
    return {
        "source": "open-meteo",
        "horizon": horizon,
        "temp_min_f": min(temps) if temps else None,
        "temp_max_f": max(temps) if temps else None,
        "wind_peak_mph": max(winds) if winds else None,
        "precip_prob_max_pct": max(probs) if probs else None,
        "sunrise": first_day("sunrise"),
        "sunset": first_day("sunset"),
    }


def _usgs_view(src: dict | None, value, unit: str) -> dict | None:
    """Render one USGS IV reading (stage or discharge) as a briefing view."""
    if value is None or not isinstance(src, dict):
        return None
    return {
        "value": value,
        "unit": unit,
        "label": src.get("label"),
        "site": src.get("site"),
        "as_of_iso": src.get("as_of_iso"),
        "age_hours": src.get("age_hours"),
        "status": src.get("status"),
        "stale": bool(src.get("stale")),
    }


def split_usgs(block: dict | None) -> tuple[dict | None, dict | None]:
    """Split a USGS IV block into (water_level, flow) briefing views.

    Primary site first; the secondary reading (Sacramento Colusa pair,
    NBB outflow) fills whichever dimension the primary lacks. No gauge /
    no data -> (None, None) — never fabricated.
    """
    if not isinstance(block, dict):
        return None, None
    sec = block.get("secondary") if isinstance(block.get("secondary"), dict) else None
    level = _usgs_view(block, block.get("stage_ft"), "ft")
    if level is None and sec:
        level = _usgs_view(sec, sec.get("stage_ft"), "ft")
    flow = _usgs_view(block, block.get("flow_cfs"), "cfs")
    if flow is None and sec:
        flow = _usgs_view(sec, sec.get("flow_cfs"), "cfs")
    return level, flow


def build_conditions(trip: dict, om: dict | None, usgs_block: dict | None) -> dict:
    """Assemble the briefing's conditions block (pure over inputs)."""
    trip_date: date | None = None
    d = trip.get("date")
    if isinstance(d, str):
        try:
            trip_date = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            trip_date = None
    weather = summarize_weather(om, trip_date)
    level, flow = split_usgs(usgs_block)
    pressure = (wx._pressure_summary(om)
                if isinstance(om, dict) and "hourly" in om else None)
    return {
        "date": trip.get("date"),
        "weather": weather,
        "water_level": level,
        "flow": flow,
        "pressure": pressure,
        "lunar": lunar.moon_phase(trip_date or date.today()),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --- plan --------------------------------------------------------------------

def build_plan_block(plan: dict | None) -> dict:
    """Slice the recommendation engine's plan into the briefing's plan block.

    species carry the pixel-art sprite filename (canonical mapping in
    app/services/species_icons.py — same table the Plan tab renders from).
    tactics = the top-ranked suggestion's rig/lures/lines/tips (the
    "what/how to target" windows).
    """
    plan = plan or {}
    sugg = plan.get("suggestions") or []
    species = [{
        "name": s.get("species"),
        "sprite": species_icons.resolve_sprite(s.get("species")),
        "activity": s.get("activity"),
        "score": s.get("score"),
    } for s in sugg[:3]]
    top = sugg[0] if sugg else None
    tactics = None
    if top:
        tactics = {
            "rod": top.get("rod"),
            "lures": top.get("lures") or [],
            "lines": top.get("lines"),
            "tips": top.get("tips") or [],
        }
    return {
        "species": species,
        "regs": plan.get("regs"),
        "stocking": plan.get("stocking"),
        "tactics": tactics,
        "kayak": plan.get("kayak"),
        "reminders": plan.get("reminders"),
        "winter_targeting": plan.get("winter_targeting"),
    }


# --- gear ---------------------------------------------------------------------

def flatten_base_gear(gear: dict | None) -> list[str]:
    """The user's saved tackle as a flat checklist (category-prefixed)."""
    gear = gear or {}
    items: list[str] = []
    for r in gear.get("rods") or []:
        if isinstance(r, dict) and r.get("name"):
            items.append(f"{r['name']} (rod)")
    for r in gear.get("reels") or []:
        if isinstance(r, dict) and r.get("name"):
            items.append(f"{r['name']} (reel)")
    for key in ("lures", "extras"):
        for x in gear.get(key) or []:
            if isinstance(x, str) and x.strip():
                items.append(x.strip())
    return items


def build_gear_block(gear: dict | None, water_slug: str,
                     conditions: dict, kayak: dict | None) -> dict:
    """Base gear + conditional additions (each with a reason)."""
    return {
        "base": flatten_base_gear(gear),
        "conditional": gear_rules.derive_conditional_gear(
            water_slug, conditions, kayak),
    }


# --- composition ---------------------------------------------------------------

def assemble_briefing(trip: dict, water: dict, plan: dict | None,
                      om: dict | None, usgs_block: dict | None,
                      gear: dict | None) -> dict:
    """Pure assembly of the full briefing payload from pre-fetched parts."""
    slug = water.get("slug") or ""
    conditions = build_conditions(trip, om, usgs_block)
    return {
        "trip_id": trip.get("id"),
        "water": {"slug": slug, "name": water.get("name"), "kind": water.get("kind")},
        "plan": build_plan_block(plan),
        "conditions": conditions,
        "gear": build_gear_block(gear, slug, conditions,
                                 (plan or {}).get("kayak")),
    }


async def build_briefing(conn: sqlite3.Connection, trip_row: sqlite3.Row,
                         water_row: sqlite3.Row) -> dict:
    """Fetch upstreams (cached, non-raising) and compose the briefing.

    Raises only on programmer error — the router guards the whole call so
    the endpoint degrades to a 200 skeleton instead of a 500.
    """
    trip, water = dict(trip_row), dict(water_row)
    slug = water.get("slug") or ""
    # recommend() raises ValueError on a bad date; validate once and pass
    # None (month-based plan) instead so a corrupted row can't 500 the API.
    rec_date = None
    d = trip.get("date")
    if isinstance(d, str):
        try:
            datetime.strptime(d, "%Y-%m-%d")
            rec_date = d
        except ValueError:
            rec_date = None
    om, gauges, usgs_block = await asyncio.gather(
        wx.open_meteo_hourly(water), wx.usgs_gauges(water),
        usgs_svc.water_usgs(slug),
    )
    om = om if isinstance(om, dict) and "hourly" in om else None
    usgs_block = usgs_block if isinstance(usgs_block, dict) else None
    gear = db.get_gear(conn)
    plan = rec.recommend(slug, rec_date, trip.get("target_species"),
                         om, gauges, gear=gear, usgs_live=usgs_block)
    return assemble_briefing(trip, water, plan, om, usgs_block, gear)
