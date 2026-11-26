#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING Chasing Tail(s) server.

Usage: python3 scripts/smoke_test.py [BASE_URL]   (default http://localhost:8090)

Verifies the acceptance criteria:
  1. /healthz returns 200
  2. a second user can be created via API (multi-user capability)
  3. trip + catch CRUD round-trip (create/list/update/delete); trip responses
     expose water_slug (drives the inline per-card "in season + regs" panel)
  4. weather endpoint returns real live NWS data for Collins Lake
  5. kayak gate: Loon Lake always NO KAYAK
  6. dossier integration (2026-11-23 research-scout dossiers):
     - regs seeds match dossier §4 exactly (all four waters)
     - weather panel queries the correct USGS station IDs via OGC API
     - mid-Dec Sacramento trip recommends chinook (2/day, 4 possession)
     - Loon trip shows NO KAYAK flag AND road-status reminder
     - invalid ?date= -> 422
  7. gear: GET default shape, PUT round-trip, 422 on invalid payloads,
     DELETE resets to defaults, recommend works with edited gear
     (DB state restored before the final cleanup)
  8. inline plan: GET /api/recommend with a created trip's water_slug+date
     returns 200 with suggestions (the per-card Plan panel's data source)
  9. lunar: GET /api/weather/<slug> carries a `lunar` object (valid phase,
     illumination 0-100, day countdowns) for at least two waters, and the
     pure function app.services.lunar.moon_phase reproduces three published
     almanac dates (2026-11-09 new, 2026-11-24 full, 2026-12-09 new) within
     tolerance via direct import (no server needed for those checks)
  10. community: FishBrain CSV+JSON import (fuzzy columns, tolerant dates,
      water matching, batch undo), unified GET filters, Reddit disabled path
      (env unset), hermetic parser/matching fixtures (no live Reddit calls)
  11. live conditions (task t_04a00997):
      - /api/conditions/<slug>: USGS IV block for NBB (site 11413515) +
        Sacramento (site 11389500) with as_of_iso/age_hours/qualifiers;
        null for Collins/Loon (no gauge — never fabricated); alerts list
        (may be empty) with stable key/signature/severity/message shape
      - weather bundle carries a pressure block (hPa/inHg + trend)
      - recommend stays 200 with the new live soft modifiers
      - hermetic (no network): IV wire-shape parsing, forced-outage
        degradation (stale cache served / no_data — never a 500), pressure
        trend classification, alert derivation + stable dedupe signatures
Exit code 0 = all pass.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# Pure stdlib module (app/__init__.py and app/services/__init__.py are
# docstring-only), so this import works without fastapi installed.
from app.services.lunar import moon_phase

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
PASS, FAIL = 0, 0

# Hermetic community parser/matching checks (pure functions only — no
# server, no network, no live Reddit calls; repo root already on sys.path).
from app.services.community import (  # noqa: E402
    match_water,
    normalize_reddit_child,
    parse_fishbrain_export,
)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


def req(method, path, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def req_raw(method, path, text, ctype="text/plain", timeout=90):
    """Like req() but sends a RAW text body (FishBrain CSV/JSON paste)."""
    r = urllib.request.Request(
        BASE + path, data=text.encode("utf-8"), method=method,
        headers={"Content-Type": ctype},
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def as_dict(x):
    """Coerce a response body to dict (non-JSON error bodies arrive as str)."""
    return x if isinstance(x, dict) else {}


def test_conditions(base):
    """11. Live conditions: /api/conditions contract + pressure + recommend."""
    site_expect = {
        "new-bullards-bar": "11413515",
        "sacramento-river-westport": "11389500",
    }
    for slug in ("collins-lake", "new-bullards-bar", "loon-lake", "sacramento-river-westport"):
        st, body = req("GET", f"/api/conditions/{slug}")
        check(f"conditions {slug}: HTTP 200 (never 500)", st == 200, f"(got {st} {body!r:.120})")
        if st != 200:
            continue
        body = as_dict(body)
        usgs = body.get("usgs")
        alerts = body.get("alerts")
        check(f"conditions {slug}: alerts is a list (may be empty)", isinstance(alerts, list),
              f"(got {type(alerts).__name__})")
        for a in alerts or []:
            check(f"conditions {slug}: alert shape ({a.get('key')})",
                  isinstance(a, dict)
                  and all(k in a for k in ("key", "signature", "severity", "message")),
                  f"(got {a!r})")
        if slug in site_expect:
            check(f"conditions {slug}: usgs block present", isinstance(usgs, dict),
                  f"(got {usgs!r:.120})")
            if isinstance(usgs, dict):
                check(f"conditions {slug}: site id {site_expect[slug]}",
                      usgs.get("site") == site_expect[slug], f"(got {usgs.get('site')!r})")
                if usgs.get("status") not in ("no_recent_reading", "no_data"):
                    check(f"conditions {slug}: at least one real reading",
                          any(usgs.get(f) is not None for f in ("stage_ft", "flow_cfs", "temp_f")),
                          f"(got {usgs!r:.160})")
                    check(f"conditions {slug}: as_of_iso + age_hours present",
                          isinstance(usgs.get("as_of_iso"), str) and usgs["as_of_iso"]
                          and isinstance(usgs.get("age_hours"), (int, float)),
                          f"(as_of={usgs.get('as_of_iso')!r} age={usgs.get('age_hours')!r})")
                if usgs.get("qualifiers") is not None:
                    check(f"conditions {slug}: qualifiers surfaced (displayed, not fatal)",
                          isinstance(usgs["qualifiers"], str) and usgs["qualifiers"],
                          f"(got {usgs['qualifiers']!r})")
        else:
            check(f"conditions {slug}: usgs is null (no gauge — never fabricated)",
                  usgs is None, f"(got {usgs!r:.120})")

    # Pressure block in the weather bundle (hourly + trend + inHg conversion).
    st, wb = req("GET", "/api/weather/sacramento-river-westport")
    if st == 200:
        om = as_dict(as_dict(wb).get("open_meteo"))
        p = om.get("pressure")
        check("weather bundle: pressure block present", isinstance(p, dict), f"(got {p!r:.120})")
        if isinstance(p, dict):
            check("pressure: trend in rising/falling/steady/unknown",
                  p.get("trend") in ("rising", "falling", "steady", "unknown"),
                  f"(got {p.get('trend')!r})")
            check("pressure: hPa/inHg numeric + conversion consistent",
                  isinstance(p.get("hpa"), (int, float)) and isinstance(p.get("inhg"), (int, float))
                  and abs(p["inhg"] - p["hpa"] * 0.02953) < 0.01, f"(got {p!r})")
    else:
        check("weather bundle reachable for pressure check", False, f"(got {st})")

    # Recommend stays healthy with the new live soft modifiers.
    st, plan = req("GET", "/api/recommend?water_slug=sacramento-river-westport&live_weather=true")
    check("recommend live (soft USGS/pressure modifiers): HTTP 200", st == 200,
          f"(got {st} {plan!r:.120})")
    if st == 200:
        check("recommend live: weather_notes is a list",
              isinstance(as_dict(plan).get("weather_notes"), list))


def run_conditions_hermetic():
    """Hermetic live-conditions checks (no network): IV parsing, forced-outage
    degradation, pressure trend classification, alert derivation + dedupe."""
    import asyncio
    import tempfile
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    import httpx

    import app.config as cfg
    from app.services import alerts as cond_alerts
    from app.services import usgs as usgs_svc
    from app.services import weather as wx

    # --- USGS IV payload parsing (real wire shape, verified 2026-11-26) ---
    def iv_fixture(points, code="00065", site="11389500"):
        return {"value": {"timeSeries": [{
            "sourceInfo": {"siteCode": [{"value": site}]},
            "variable": {"variableCode": [{"value": code}]},
            "values": [{
                "value": [{"value": v, "qualifiers": ["P"], "dateTime": t} for t, v in points],
                "qualifier": [{"qualifierCode": "P",
                               "qualifierDescription": "Provisional data subject to revision."}],
                "sample": [], "censorCode": [],
            }],
        }]}}

    now = datetime.now(timezone.utc)
    # Chronological: oldest (1000.0) -> newest (1030.0).
    pts = [((now - timedelta(minutes=15 * (3 - i))).strftime("%Y-%m-%dT%H:%M:%S.000-08:00"),
            str(1000.0 + i * 10.0)) for i in range(4)]
    parsed = usgs_svc.parse_iv_payload(iv_fixture(pts))
    check("usgs: IV fixture parses (4 chronological points)",
          "00065" in parsed and len(parsed["00065"]["points"]) == 4, f"(got {parsed!r:.160})")
    check("usgs: latest value wins + qualifiers kept",
          parsed["00065"]["points"][-1][1] == 1030.0 and parsed["00065"]["points"][-1][2] == ["P"],
          f"(got {parsed['00065']['points'][-1]!r})")
    check("usgs: junk payload tolerated (no raise)",
          usgs_svc.parse_iv_payload({"value": {"timeSeries": [None, {"variable": {}}]}}) == {})
    check("usgs: collins/loon have no site spec (null contract)",
          usgs_svc.SITE_SPECS.get("collins-lake") is None
          and usgs_svc.SITE_SPECS.get("loon-lake") is None)
    blk_empty = usgs_svc._assemble("11413515",
                                   {"site": "11413515", "name": "T", "label": "t", "params": ["00010"]},
                                   {}, "live", False, now)
    check("usgs: empty 7-day window -> no_recent_reading (never fabricates)",
          blk_empty["status"] == "no_recent_reading" and blk_empty["stage_ft"] is None
          and blk_empty["as_of_iso"] is None, f"(got {blk_empty!r:.160})")

    # --- Forced outage: stale cache served; no cache -> no_data (no raise) ---
    spec = {"site": "11413515", "name": "TEST SITE", "label": "test", "params": ["00010"]}
    spec2 = {"site": "99999999", "name": "EMPTY SITE", "label": "test2", "params": ["00010"]}

    class Boom(httpx.AsyncBaseTransport):
        async def handle_request(self, request):
            raise httpx.ConnectError("forced outage", request=request)

    with tempfile.TemporaryDirectory() as td:
        old_cache = cfg.CACHE_DIR
        cfg.CACHE_DIR = Path(td)
        try:
            key = "usgs_iv_11413515"
            wx._write_cache(key, iv_fixture([("2026-11-20T12:00:00.000-08:00", "1874.5")],
                                            code="00010"))
            cf = cfg.CACHE_DIR / f"{key}.json"
            data = json.loads(cf.read_text())
            data["_fetched_ts"] = time.time() - 7 * 3600  # epoch float (> STALE_AFTER_S)
            cf.write_text(json.dumps(data))

            async def fetch_boom(sp):
                async with httpx.AsyncClient(transport=Boom()) as client:
                    return await usgs_svc.fetch_site(sp, client=client)

            block = asyncio.run(fetch_boom(spec))
            check("usgs down: stale cache served (status=stale, stale=True)",
                  block["status"] == "stale" and block["stale"] is True, f"(got {block!r:.160})")
            check("usgs down: cached value intact (stage_ft=1874.5)",
                  block["stage_ft"] == 1874.5, f"(got {block!r:.160})")
            block2 = asyncio.run(fetch_boom(spec2))
            check("usgs down + no cache: status=no_data (no raise, no fabrication)",
                  block2["status"] == "no_data" and block2["stage_ft"] is None
                  and block2["as_of_iso"] is None, f"(got {block2!r:.160})")
        finally:
            cfg.CACHE_DIR = old_cache

    # --- Pressure trend classification (pure function over payloads) ---
    now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hist_times = [(now_utc - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in (4, 3, 2, 1, 0)]
    p = wx._pressure_summary({"utc_offset_seconds": 0, "hourly": {
        "time": hist_times, "pressure_msl": [1014.0, 1013.6, 1013.2, 1012.9, 1012.5]}})
    check("pressure: falling detected over ~4h window",
          p is not None and p["trend"] == "falling" and p["window_hours"] == 4, f"(got {p!r})")
    check("pressure: hPa->inHg conversion consistent",
          p is not None and abs(p["inhg"] - p["hpa"] * 0.02953) < 0.01, f"(got {p!r})")
    flat = wx._pressure_summary({"utc_offset_seconds": 0, "hourly": {
        "time": hist_times, "pressure_msl": [1013.0] * 5}})
    check("pressure: flat -> steady", flat is not None and flat["trend"] == "steady", f"(got {flat!r})")
    single = wx._pressure_summary({"utc_offset_seconds": 0, "hourly": {
        "time": hist_times[:1], "pressure_msl": [1013.0]}})
    check("pressure: single sample -> unknown (early morning)",
          single is not None and single["trend"] == "unknown", f"(got {single!r})")
    check("pressure: missing variable -> None (no crash)",
          wx._pressure_summary({"utc_offset_seconds": 0, "hourly": {"time": hist_times}}) is None)

    # --- Alert derivation (synthetic OM + USGS fixtures) ---
    times = [(now_utc + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(30)]
    press = [1013.0 if i < 10 else 1012.7 - 0.05 * (i - 10) for i in range(30)]
    probs = [10] * 30
    probs[6] = 80
    om = {"utc_offset_seconds": 0, "hourly": {
        "time": times, "pressure_msl": press, "precipitation_probability": probs}}
    usgs_blk = {"flow_cfs": 6000.0, "flow_prev_cfs": 4000.0, "stage_ft": None, "label": "test river"}
    a = cond_alerts.derive_alerts("sacramento-river-westport", om, usgs_blk)
    keys = {x["key"] for x in a}
    check("alerts: pressure_drop fires (24h low >= 0.5 hPa below current)",
          "pressure_drop" in keys, f"(got {sorted(keys)})")
    check("alerts: rain_incoming fires (80% within 12h)", "rain_incoming" in keys,
          f"(got {sorted(keys)})")
    check("alerts: flow_rising fires (+50% and +2000 cfs vs prior reading)",
          "flow_rising" in keys, f"(got {sorted(keys)})")
    check("alerts: quiet water -> no false positives",
          cond_alerts.derive_alerts("loon-lake", None, None) == [], "(got alerts on quiet scene)")
    a_stock = cond_alerts.derive_alerts("collins-lake", None, None, today=date(2026, 11, 22))
    check("alerts: stocking_tomorrow fires (Nov 23 seeded in knowledge)",
          any(x["key"] == "stocking_tomorrow" for x in a_stock), f"(got {a_stock!r})")
    a_nostock = cond_alerts.derive_alerts("collins-lake", None, None, today=date(2026, 11, 24))
    check("alerts: no stocking alert on a non-stock day",
          not any(x["key"] == "stocking_tomorrow" for x in a_nostock), f"(got {a_nostock!r})")
    a_again = cond_alerts.derive_alerts("sacramento-river-westport", om, usgs_blk)
    check("alerts: stable signatures while the condition persists (dedupe)",
          {x["key"]: x["signature"] for x in a} == {x["key"]: x["signature"] for x in a_again},
          f"({a!r} vs {a_again!r})")


def main():
    print(f"Chasing Tail(s) smoke test -> {BASE}")

    # 0. lunar: almanac vectors via direct import (no server needed).
    # Published UTC instants (timeanddate.com, nightskytoday.com, earthsky.org,
    # 13cal.net all agree):
    #   new moon  2026-11-09 07:02 UTC
    #   full moon 2026-11-24 14:53 UTC  (Beaver Moon)
    #   new moon  2026-12-09 00:52 UTC
    # The mean-lunation model must land each within +/-1 day; checked via
    # phase name + illumination at noon UTC of the almanac date.
    v_nm = moon_phase(date(2026, 11, 9))
    check("lunar: almanac new moon 2026-11-09 07:02 UTC -> 'new moon', illum <= 10%",
          v_nm["phase"] == "new moon" and v_nm["illumination_pct"] <= 10, f"(got {v_nm})")
    v_fm = moon_phase(date(2026, 11, 24))
    check("lunar: almanac full moon 2026-11-24 14:53 UTC -> 'full moon', illum >= 90%",
          v_fm["phase"] == "full moon" and v_fm["illumination_pct"] >= 90, f"(got {v_fm})")
    v_nm2 = moon_phase(date(2026, 12, 9))
    check("lunar: almanac new moon 2026-12-09 00:52 UTC -> 'new moon', illum <= 10%",
          v_nm2["phase"] == "new moon" and v_nm2["illumination_pct"] <= 10, f"(got {v_nm2})")

    # 0b. live conditions: hermetic (no network) — IV parsing, forced-outage
    # degradation, pressure trend, alert derivation + dedupe signatures.
    run_conditions_hermetic()

    # 1. healthz
    st, body = req("GET", "/healthz")
    check("GET /healthz -> 200", st == 200 and isinstance(body, dict) and body.get("ok") is True,
          f"(got {st} {body!r:.120})")

    # 2. second user
    uname = f"smoke-{int(time.time())}"
    st, body = req("POST", "/api/users", {"name": uname, "email": None})
    check("create second user -> 201", st == 201 and body.get("name") == uname, f"(got {st} {body!r:.120})")
    user_id = body.get("id")

    # 3. waters seeded
    st, waters = req("GET", "/api/waters")
    slugs = {w["slug"] for w in waters} if st == 200 else set()
    check("four waters seeded", st == 200 and {"collins-lake", "new-bullards-bar", "loon-lake",
                                               "sacramento-river-westport"} <= slugs, f"(slugs={sorted(slugs)})")
    collins = next(w for w in waters if w["slug"] == "collins-lake")

    # 4. trip CRUD
    st, trip = req("POST", "/api/trips", {
        "user_id": user_id, "water_id": collins["id"], "date": "2026-12-19",
        "target_species": "rainbow trout", "notes": "smoke test trip", "status": "planned",
    })
    check("create trip -> 201", st == 201 and trip.get("water_name", "").startswith("Collins Lake"), f"(got {st} {trip!r:.120})")
    trip_id = trip.get("id")
    check("create trip response includes water_slug",
          st == 201 and as_dict(trip).get("water_slug") == "collins-lake", f"(got {as_dict(trip).get('water_slug')!r})")

    st, trips = req("GET", f"/api/trips?user_id={user_id}")
    trip_rows = trips if isinstance(trips, list) else []
    listed = next((t for t in trip_rows if t["id"] == trip_id), {})
    check("list trips contains new trip", st == 200 and any(t["id"] == trip_id for t in trip_rows))
    check("list trip response includes water_slug",
          st == 200 and listed.get("water_slug") == "collins-lake", f"(got {listed.get('water_slug')!r})")

    st, trip = req("PATCH", f"/api/trips/{trip_id}", {"status": "completed", "notes": "edited"})
    check("update trip -> 200", st == 200 and trip.get("status") == "completed" and trip.get("notes") == "edited",
          f"(got {st} {trip!r:.120})")
    check("updated trip response still carries water_slug",
          st == 200 and as_dict(trip).get("water_slug") == "collins-lake", f"(got {as_dict(trip).get('water_slug')!r})")

    # inline plan panel data source: recommend with the trip's own water_slug+date
    st, plan_inline = req("GET", f"/api/recommend?water_slug={as_dict(trip).get('water_slug')}&date={as_dict(trip).get('date')}&live_weather=false")
    sugg_inline = as_dict(plan_inline).get("suggestions", []) if st == 200 else []
    check("inline plan: recommend with trip water_slug+date -> 200 with suggestions",
          st == 200 and len(sugg_inline) >= 1
          and sugg_inline[0].get("species") and sugg_inline[0].get("score") is not None,
          f"(got {st} top={sugg_inline[0].get('species') if sugg_inline else None})")

    # 5. catch CRUD
    st, catch = req("POST", "/api/catches", {
        "trip_id": trip_id, "species": "rainbow trout", "count": 3,
        "lure_or_method": "Panther Martin #3", "spot": "north bay",
    })
    check("create catch -> 201", st == 201 and catch.get("species") == "rainbow trout", f"(got {st} {catch!r:.120})")
    catch_id = catch.get("id")

    st, catches = req("GET", f"/api/catches?trip_id={trip_id}")
    check("list catches contains new catch", st == 200 and any(c["id"] == catch_id for c in catches))

    st, catch = req("PATCH", f"/api/catches/{catch_id}", {"count": 5, "notes": "big one!"})
    check("update catch -> 200", st == 200 and catch.get("count") == 5, f"(got {st} {catch!r:.120})")

    # 6. live NWS weather for Collins Lake
    st, wx = req("GET", "/api/weather/collins-lake")
    nws = as_dict(wx).get("nws", {}) if st == 200 else {}
    periods = nws.get("periods", [])
    check("weather: live NWS data for Collins Lake",
          st == 200 and nws.get("office") and len(periods) > 4
          and periods[0].get("shortForecast") and not nws.get("stale"),
          f"(st={st} office={nws.get('office')} periods={len(periods)} stale={nws.get('stale')} err={nws.get('error')})")
    if periods:
        print(f"      NWS sample: {periods[0]['name']} {periods[0]['temperature']}{periods[0].get('tempUnit', '')} {periods[0]['shortForecast']}")
    om = as_dict(wx).get("open_meteo", {})
    check("weather: Open-Meteo hourly present", st == 200 and len(om.get("hourly", {}).get("time", [])) >= 24)

    # Imperial units at the source + sunrise/sunset exposure (regression:
    # °C values cluster 0–25, °F for CA winter sits roughly 30–75).
    om_daily = om.get("daily", {}) if isinstance(om, dict) else {}
    sr, ss = om_daily.get("sunrise"), om_daily.get("sunset")
    iso_like = lambda v: isinstance(v, str) and len(v) >= 16 and v[4] == "-" and "T" in v
    check("weather: Open-Meteo daily.sunrise/sunset present (ISO local)",
          st == 200 and isinstance(sr, list) and len(sr) >= 1 and iso_like(sr[0])
          and isinstance(ss, list) and len(ss) >= 1 and iso_like(ss[0]),
          f"(sunrise={sr!r:.60} sunset={ss!r:.60})")
    om_temps = [t for t in (om.get("hourly", {}).get("temperature_2m") or [])
                if isinstance(t, (int, float))]
    check("weather: Open-Meteo hourly temps in °F plausibility range (0–120, CA winter)",
          st == 200 and len(om_temps) >= 24
          and all(0 <= t <= 120 for t in om_temps),
          f"(n={len(om_temps)} min={min(om_temps) if om_temps else None} "
          f"max={max(om_temps) if om_temps else None})")
    # Lunar: computed locally (no external API) — same date basis as the
    # rest of the bundle; renders on the Weather tab for every water.
    VALID_PHASES = {"new moon", "waxing crescent", "first quarter", "waxing gibbous",
                    "full moon", "waning gibbous", "last quarter", "waning crescent"}
    lu = as_dict(wx).get("lunar")
    check("weather: lunar object present (valid phase, illumination 0–100, day countdowns)",
          st == 200 and isinstance(lu, dict) and lu.get("phase") in VALID_PHASES
          and isinstance(lu.get("illumination_pct"), (int, float))
          and 0 <= lu["illumination_pct"] <= 100
          and isinstance(lu.get("next_new_moon_in_days"), int) and lu["next_new_moon_in_days"] >= 0
          and isinstance(lu.get("next_full_moon_in_days"), int) and lu["next_full_moon_in_days"] >= 0,
          f"(lunar={lu!r})")
    if isinstance(lu, dict):
        print(f"      lunar (Collins Lake): {lu}")
    usgs = as_dict(wx).get("usgs")
    print(f"      USGS (Collins Lake): {usgs!r:.160}")

    # NBB gauges (best-effort: USGS has been flaky; the bundle must always
    # contain the correct station IDs, whatever their live status is)
    st, wx2 = req("GET", "/api/weather/new-bullards-bar")
    usgs2 = as_dict(wx2).get("usgs") if st == 200 else None
    sites2 = {g.get("site") for g in (usgs2 or {}).get("gauges", [])} if isinstance(usgs2, dict) else set()
    check("weather: NBB USGS bundle has correct station IDs (11413515 stage, 11413520 outflow)",
          st == 200 and {"11413515", "11413520"} <= sites2,
          f"(sites={sorted(sites2)})")
    for g in (usgs2 or {}).get("gauges", []):
        print(f"      NBB gauge {g.get('site')}: value={g.get('value')} {g.get('unit')} status={g.get('status')} as_of={g.get('as_of')}")

    # Sacramento River gauges (Red Bluff primary + Yolo Bypass pair)
    st, wx3 = req("GET", "/api/weather/sacramento-river-westport")
    usgs3 = as_dict(wx3).get("usgs") if st == 200 else None
    sites3 = {g.get("site") for g in (usgs3 or {}).get("gauges", [])} if isinstance(usgs3, dict) else set()
    check("weather: Sacramento USGS bundle has correct station IDs (11377100, 11453000, 11453120)",
          st == 200 and {"11377100", "11453000", "11453120"} <= sites3,
          f"(sites={sorted(sites3)})")
    for g in (usgs3 or {}).get("gauges", []):
        print(f"      Sac gauge {g.get('site')}: value={g.get('value')} {g.get('unit')} status={g.get('status')} as_of={g.get('as_of')}")

    # Collins Lake: no gauge on the lake — nearest regional indicator 11413520
    usgs_c = as_dict(wx).get("usgs")
    gc = (usgs_c or {}).get("gauges", []) if isinstance(usgs_c, dict) else []
    check("weather: Collins USGS bundle uses regional-indicator gauge 11413520 (labeled)",
          st == 200 and {g.get("site") for g in gc} == {"11413520"}
          and any("regional indicator" in (g.get("label") or g.get("spec_note") or "").lower() for g in gc),
          f"(gauges={[(g.get('site'), g.get('label')) for g in gc]})")

    # Loon Lake: no public gauge — bundle explains why
    st, wx4 = req("GET", "/api/weather/loon-lake")
    usgs4 = as_dict(wx4).get("usgs") if st == 200 else None
    check("weather: Loon USGS layer explains no public gauge",
          st == 200 and isinstance(usgs4, dict) and not usgs4.get("gauges")
          and "no public" in (usgs4.get("note") or "").lower(),
          f"(got {usgs4!r:.160})")
    lu4 = as_dict(wx4).get("lunar")
    check("weather: lunar present for a second water (Loon Lake)",
          st == 200 and isinstance(lu4, dict) and lu4.get("phase") in VALID_PHASES
          and isinstance(lu4.get("illumination_pct"), (int, float)) and 0 <= lu4["illumination_pct"] <= 100,
          f"(lunar={lu4!r})")

    # ---- dossier integration: regs seeds vs dossier §4 ----
    def reg_entry(plan, species_prefix):
        regs = (plan.get("regs") or {}) if isinstance(plan, dict) else {}
        for r in regs.get("species", []):
            if r["species"].lower().startswith(species_prefix):
                return r
        return None

    st, pc = req("GET", "/api/recommend?water_slug=collins-lake&date=2026-12-15&live_weather=false")
    tr = reg_entry(pc, "inland trout") if st == 200 else None
    bb = reg_entry(pc, "black bass") if st == 200 else None
    check("regs: Collins trout 5/day, 10 possession, no size limit, all year",
          st == 200 and tr and tr["daily_bag"] == 5 and tr["possession"] == 10
          and tr["size_limit"] == "none" and tr["season"] == "all year",
          f"(got {tr})")
    check("regs: Collins bass 12-in min, 5/day, all year",
          st == 200 and bb and bb["daily_bag"] == 5 and "12 in" in (bb["size_limit"] or ""),
          f"(got {bb})")
    check("regs: Collins no special regs",
          st == 200 and "none for collins lake" in ((pc.get("regs") or {}).get("special_regs") or "").lower())
    stk = as_dict(pc).get("stocking") or {}
    check("stocking: Collins private weekly 1,000–2,000 lb + 'near a stocking weekend' advice",
          any("1,000–2,000 lb" in p["detail"] for p in stk.get("programs", []))
          and "stocking weekend" in (stk.get("advice") or "").lower(),
          f"(got {stk!r:.200})")

    st, pn = req("GET", "/api/recommend?water_slug=new-bullards-bar&date=2026-12-15&live_weather=false")
    kk = reg_entry(pn, "kokanee") if st == 200 else None
    sp = reg_entry(pn, "black bass") if st == 200 else None
    check("regs: NBB kokanee EXCEPTION 10/day, 20 possession, all year (§5.41)",
          st == 200 and kk and kk["daily_bag"] == 10 and kk["possession"] == 20
          and kk["season"] == "all year" and "exception" in (kk["authority"] or "").lower(),
          f"(got {kk})")
    check("regs: NBB spotted bass 12-in min, 5/day, all year",
          st == 200 and sp and sp["daily_bag"] == 5 and "12 in" in (sp["size_limit"] or ""),
          f"(got {sp})")
    wt = as_dict(pn).get("winter_targeting") or {}
    check("targeting: NBB winter focus = trophy spotted bass (world records Jan/Feb)",
          st == 200 and "spotted bass" in wt.get("focus", "").lower() and "record" in wt.get("why", "").lower(),
          f"(got {wt!r:.200})")

    st, pl = req("GET", "/api/recommend?water_slug=loon-lake&date=2026-12-15&live_weather=false")
    lt = reg_entry(pl, "inland trout") if st == 200 else None
    lb = reg_entry(pl, "black bass") if st == 200 else None
    check("regs: Loon trout 5/day, 10 possession, no size limit + bass 12-in min, 5/day",
          st == 200 and lt and lt["daily_bag"] == 5 and lt["possession"] == 10
          and lb and lb["daily_bag"] == 5 and "12 in" in (lb["size_limit"] or ""),
          f"(trout={lt} bass={lb})")
    lstk = as_dict(pl).get("stocking") or {}
    check("stocking: Loon — NO CDFW plants in past 13 months (no biweekly claim)",
          st == 200 and "13 months" in (lstk.get("advice") or "")
          and not any("bi-weekly" in p["detail"] for p in lstk.get("programs", [])),
          f"(got {lstk!r:.200})")
    kay = as_dict(pl).get("kayak") or {}
    reminds = as_dict(pl).get("reminders") or []
    check("loon: NO KAYAK flag + road-status reminder (fs.usda.gov/r05/eldorado/alerts)",
          st == 200 and kay.get("flag") == "NO KAYAK" and kay.get("level") == "no"
          and any("fs.usda.gov/r05/eldorado/alerts" in r for r in reminds)
          and "ice house rd" in kay.get("reason", "").lower(),
          f"(kayak={kay} reminders={reminds!r:.200})")

    # ---- mid-December Sacramento: chinook must be the top recommendation ----
    st, ps = req("GET", "/api/recommend?water_slug=sacramento-river-westport&date=2026-12-15&live_weather=false")
    sugg = as_dict(ps).get("suggestions", []) if st == 200 else []
    top = sugg[0] if sugg else {}
    check("mid-Dec Sacramento: top suggestion = chinook salmon with 2/day, 4 possession",
          st == 200 and top.get("species") == "chinook salmon"
          and "2/day" in (top.get("limits") or "") and "4 possession" in (top.get("limits") or ""),
          f"(top={top.get('species')} limits={top.get('limits')})")
    ch = reg_entry(ps, "chinook salmon") if st == 200 else None
    check("regs: Sac chinook Nov 1 – Dec 31, 2/day, 4 possession (sec 7.40(80))",
          st == 200 and ch and ch["daily_bag"] == 2 and ch["possession"] == 4
          and "nov 1" in (ch["season"] or "").lower() and "dec 31" in (ch["season"] or "").lower(),
          f"(got {ch})")
    hs = reg_entry(ps, "hatchery steelhead") if st == 200 else None
    check("regs: Sac hatchery steelhead all year, clipped-fin only + FG 682 card",
          st == 200 and hs and "clipped" in (hs.get("conditions") or "").lower()
          and "FG 682" in (hs.get("conditions") or ""),
          f"(got {hs})")
    ks = reg_entry(ps, "all fishing (keswick") if st == 200 else None
    check("regs: Sac Keswick→650 ft CLOSED all year",
          st == 200 and ks and "closed" in (ks["season"] or "").lower() and ks["daily_bag"] == 0,
          f"(got {ks})")
    stu = reg_entry(ps, "sturgeon") if st == 200 else None
    check("regs: Sac sturgeon C&R only + report card",
          st == 200 and stu and "catch & release" in (stu.get("conditions") or "").lower()
          and "report card" in (stu.get("conditions") or "").lower()
          and stu["daily_bag"] == 0,
          f"(got {stu})")

    # ---- input validation: bad date -> 422 ----
    st, _bad = req("GET", "/api/recommend?water_slug=collins-lake&date=2026-13-45&live_weather=false")
    check("validation: ?date=2026-13-45 -> 422", st == 422, f"(got {st})")
    st, _bad = req("GET", "/api/recommend?water_slug=collins-lake&date=bogus&live_weather=false")
    check("validation: ?date=bogus -> 422", st == 422, f"(got {st})")

    # ---- waters endpoint exposes gauge configs ----
    st, waters2 = req("GET", "/api/waters")
    by_slug = {w["slug"]: w for w in (waters2 or [])} if st == 200 else {}

    def gauge_sites(w):
        out = []
        for g in (w or {}).get("gauges") or []:
            out.append(g.get("site") if isinstance(g, dict) else str(g))
        return out

    gauge_summary = ", ".join(f"{k}: {gauge_sites(v)}" for k, v in by_slug.items())
    check("waters: gauge configs exposed (nbb=2, sac=3, collins=1 indicator, loon=0)",
          st == 200
          and sorted(gauge_sites(by_slug.get("new-bullards-bar"))) == ["11413515", "11413520"]
          and sorted(gauge_sites(by_slug.get("sacramento-river-westport"))) == ["11377100", "11453000", "11453120"]
          and gauge_sites(by_slug.get("collins-lake")) == ["11413520"]
          and gauge_sites(by_slug.get("loon-lake")) == [],
          f"(got {{{gauge_summary}}}")

    # 8. chat stub disabled

    # 7. kayak gate
    st, plan = req("GET", "/api/recommend?water_slug=loon-lake&live_weather=false")
    check("kayak gate: Loon Lake = NO KAYAK",
          st == 200 and plan.get("kayak", {}).get("level") == "no"
          and plan.get("kayak", {}).get("flag") == "NO KAYAK",
          f"(got {st} {plan.get('kayak') if st == 200 else '!'}!)")

    st, plan = req("GET", "/api/recommend?water_slug=collins-lake&live_weather=false&species=rainbow%20trout")
    sugg = plan.get("suggestions", []) if st == 200 else []
    check("recommend: target species ranked first",
          st == 200 and sugg and sugg[0]["species"] == "rainbow trout" and sugg[0]["lures"],
          f"(got {st} top={sugg[0]['species'] if sugg else None})")

    # 8. chat stub disabled
    st, chat = req("POST", "/api/chat", {"message": "hello"})
    check("chat stub: disabled notice when endpoint unset",
          st == 200 and chat.get("enabled") is False and "disabled" in chat.get("reply", "").lower(),
          f"(got {st} {chat!r:.120})")

    # ---- gear: DB-backed, editable (state restored before cleanup) ----
    st, orig_gear = req("GET", "/api/gear")
    check("gear: GET returns default shape (rods/reels/lures/extras)",
          st == 200 and isinstance(orig_gear, dict)
          and all(isinstance(orig_gear.get(k), list) for k in ("rods", "reels", "lures", "extras")),
          f"(got {st} {orig_gear!r:.120})")

    mod = json.loads(json.dumps(orig_gear))  # deep copy
    mod["rods"][0]["name"] = "Smoke Rod X"
    st, saved = req("PUT", "/api/gear", mod)
    check("gear: PUT modified payload -> 200 (echoes saved)",
          st == 200 and isinstance(saved, dict) and saved.get("rods", [{}])[0].get("name") == "Smoke Rod X",
          f"(got {st} {saved!r:.120})")
    st, g2 = req("GET", "/api/gear")
    check("gear: GET reflects the change", st == 200 and g2.get("rods", [{}])[0].get("name") == "Smoke Rod X",
          f"(got {st} {g2!r:.120})")

    bad = json.loads(json.dumps(mod))
    bad["rods"][0]["name"] = "x" * 101  # over the 100-char limit
    st, _ = req("PUT", "/api/gear", bad)
    check("gear: PUT oversize rod name -> 422", st == 422, f"(got {st})")
    st, _ = req("PUT", "/api/gear", {"rods": "not-a-list", "reels": [], "lures": [], "extras": []})
    check("gear: PUT bad shape -> 422", st == 422, f"(got {st})")
    st, _ = req("PUT", "/api/gear", {**mod, "bogus_top_level_key": 1})
    check("gear: PUT unknown top-level key -> 422", st == 422, f"(got {st})")
    st, g3 = req("GET", "/api/gear")
    check("gear: rejected PUTs leave state intact", st == 200 and g3.get("rods", [{}])[0].get("name") == "Smoke Rod X",
          f"(got {st} {g3!r:.120})")

    st, pe = req("GET", "/api/recommend?water_slug=collins-lake&date=2026-12-15&live_weather=false")
    check("gear: recommend 200 with edited gear (plan echoes it)",
          st == 200 and pe.get("gear", {}).get("rods", [{}])[0].get("name") == "Smoke Rod X",
          f"(got {st} gear_rods={(as_dict(pe).get('gear') or {}).get('rods')!r:.120})")

    st, _ = req("DELETE", "/api/gear")
    check("gear: DELETE -> 204", st == 204, f"(got {st})")
    st, g4 = req("GET", "/api/gear")
    check("gear: GET after DELETE back to defaults (edit gone)",
          st == 200 and all(r.get("name") != "Smoke Rod X" for r in g4.get("rods", []))
          and all(isinstance(g4.get(k), list) for k in ("rods", "reels", "lures", "extras")),
          f"(got {st} {g4!r:.120})")

    # Restore whatever was there before the suite ran (defaults on a fresh DB).
    st, _ = req("PUT", "/api/gear", orig_gear)
    st, g5 = req("GET", "/api/gear")
    check("gear: original payload restored (suite leaves DB as found)",
          st == 200 and g5 == orig_gear, f"(got {st})")

    # ---- community: FishBrain import + Reddit (disabled) ----
    # Snapshot so the suite can prove it leaves the DB as found.
    st, _snap = req("GET", "/api/community?days=3650")
    snap_fb = as_dict(_snap).get("fishbrain", {})
    prior_rows = len(snap_fb.get("rows", []))
    prior_batches = len(snap_fb.get("batches", []))

    # Hermetic water-matching checks (fixtures only — no live Reddit calls).
    # Disambiguation: Loon/Collins need CA context or a second alias; the
    # "Lake" inside the water's own name must not count as Lake County.
    check("match: 'Loon Lake, Crystal Basin' -> loon-lake (second alias)",
          match_water("Loon Lake, Crystal Basin", disambiguate=True) == "loon-lake")
    check("match: 'Loon Lake, Minnesota' -> other (no CA context)",
          match_water("Loon Lake, Minnesota", disambiguate=True) is None)
    check("match: 'Collins Lake, California' -> collins-lake (explicit CA)",
          match_water("Collins Lake, California", disambiguate=True) == "collins-lake")
    check("match: 'Collins Lake' alone (no CA context) -> other",
          match_water("Collins Lake", disambiguate=True) is None)
    check("match: 'New Bullards Bar kokanee' -> new-bullards-bar",
          match_water("New Bullards Bar kokanee", disambiguate=True) == "new-bullards-bar")
    check("match: 'Westport bridge' -> sacramento-river-westport",
          match_water("Westport bridge", disambiguate=True) == "sacramento-river-westport")
    check("match: 'random pond in Ohio' -> other",
          match_water("random pond in Ohio", disambiguate=True) is None)
    check("match: loose mode (FishBrain) 'Loon Lake' alone -> loon-lake",
          match_water("Loon Lake") == "loon-lake")

    # Hermetic Reddit parser checks against a FIXTURE (no network).
    _rd_fixture = [
        {"kind": "t3", "data": {
            "id": "fix1", "subreddit": "californiafishing",
            "title": "Morning bite at Loon Lake, Crystal Basin",
            "author": "fixture_angler", "created_utc": 1764000000,
            "permalink": "/r/californiafishing/comments/fix1/x/",
            "selftext": "Stocked browns were on."}},
        {"kind": "t3", "data": {
            "id": "fix2", "subreddit": "fishing",
            "title": "Anyone know Loon Lake in Minnesota?",
            "author": "fixture_two", "created_utc": 1764000100,
            "permalink": "/r/fishing/comments/fix2/x/", "selftext": ""}},
        {"kind": "t3", "data": {"id": ""}},  # unusable child
    ]
    _n1 = normalize_reddit_child(_rd_fixture[0])
    _n2 = normalize_reddit_child(_rd_fixture[1])
    _n3 = normalize_reddit_child(_rd_fixture[2])
    check("reddit fixture: Crystal Basin post -> loon-lake",
          _n1 is not None and _n1["matched_water"] == "loon-lake")
    check("reddit fixture: Minnesota post -> other (disambiguated)",
          _n2 is not None and _n2["matched_water"] is None)
    check("reddit fixture: empty child -> None (skipped)", _n3 is None)
    check("reddit fixture: permalink absolutized + excerpt capped",
          _n1 is not None and _n1["permalink"].startswith("https://www.reddit.com/")
          and _n1["sub"] == "californiafishing" and _n1["author"] == "fixture_angler")

    # Hermetic FishBrain parser checks (tolerant dates, fuzzy columns).
    _rows, _skipped = parse_fishbrain_export(
        "Fish Species,Date Caught,WT,LBS,Spot,Comments\n"
        "Rainbow,2026-11-20,4.5,North Bay,dawn bite\n"
        "Kokanee,11/22/2026,1.2,Bullards Bar,\n"
        "Salmon,Nov 23 2026,18.0,Westport,pm\n"
    )
    check("FB parser: fuzzy headers (Fish Species/Date Caught/WT/Spot) detected",
          len(_rows) == 3 and _skipped == 0
          and _rows[0]["species"] == "Rainbow" and _rows[0]["weight_lb"] == 4.5
          and _rows[1]["date"] == "2026-11-22" and _rows[2]["date"] == "2026-11-23",
          f"(rows={_rows!r:.200} skipped={_skipped})")
    _rows2, _skipped2 = parse_fishbrain_export("species,date\nTrout,gibberish\n")
    check("FB parser: unparseable date -> row skipped, counted",
          len(_rows2) == 0 and _skipped2 == 1, f"(rows={_rows2!r} skipped={_skipped2})")
    try:
        parse_fishbrain_export("foo,bar\n1,2\n")
        _bad_err = None
    except ValueError as e:
        _bad_err = str(e)
    check("FB parser: unrecognized columns -> ValueError",
          _bad_err is not None and "recognizable" in _bad_err, f"(got {_bad_err!r})")

    # Synthetic CSV fixture: 5 rows — 1 deliberately bad date (skipped),
    # 2 matching different waters, 1 more water, 1 unmatched ("Other").
    # Dates are generated relative to today so the recency window holds
    # whenever the suite runs; all three date FORMS are exercised.
    _t0 = date.today()
    _d_iso = (_t0 - timedelta(days=1)).isoformat()
    _d_us = (_t0 - timedelta(days=2)).strftime("%m/%d/%Y")
    _d_named = (_t0 - timedelta(days=3)).strftime("%b %d %Y")
    fb_csv = "\n".join([
        "species,date,weight,location,notes",
        f'Rainbow Trout,{_d_iso},4.5,Collins Lake north bay,"good bite at dawn"',
        f"Kokanee,{_d_us},1.2,New Bullards Bar,",
        f"Chinook Salmon,{_d_named},18.0,Sacramento River near Westport,late afternoon",
        "Largemouth Bass,not-a-real-date,2.1,Loon Lake,",
        f"Trout,{(_t0 - timedelta(days=4)).isoformat()},,Some Random Pond,",
    ]) + "\n"
    st, imp = req_raw("POST", "/api/community/fishbrain/import", fb_csv)
    imp = as_dict(imp)
    check("FB import: CSV 5 rows -> 200 imported=4 skipped=1",
          st == 200 and imp.get("imported") == 4 and imp.get("skipped") == 1,
          f"(got {st} {imp!r:.160})")
    csv_batch = imp.get("batch_id")
    _by_sp = {r.get("species"): r for r in imp.get("rows", [])}
    _rt = _by_sp.get("Rainbow Trout", {})
    check("FB import: ISO/US/named dates normalized to ISO + weight parsed",
          _rt.get("date") == _d_iso and _rt.get("weight_lb") == 4.5
          and _by_sp.get("Kokanee", {}).get("date") == (_t0 - timedelta(days=2)).isoformat()
          and _by_sp.get("Chinook Salmon", {}).get("date") == (_t0 - timedelta(days=3)).isoformat(),
          f"(got {_rt!r:.160})")
    check("FB import: water matching (collins / nbb / sacramento / other)",
          _rt.get("water") == "collins-lake"
          and _by_sp.get("Kokanee", {}).get("water") == "new-bullards-bar"
          and _by_sp.get("Chinook Salmon", {}).get("water") == "sacramento-river-westport"
          and _by_sp.get("Trout", {}).get("water") is None,
          f"(waters={[r.get('water') for r in imp.get('rows', [])]!r})")
    check("FB import: bad-date row skipped (not in rows)", "Largemouth Bass" not in _by_sp)

    # JSON-format variant with fuzzy (camelCase) keys.
    fb_json = json.dumps([
        {"speciesName": "Kokanee",
         "createdAt": f"{(_t0 - timedelta(days=1)).isoformat()}T09:30:00Z",
         "weightLbs": "2.4", "spot": "Bullards Bar marina", "comments": "json variant"},
        {"species": "Brown Trout", "date": "garbage-date", "notes": "should be skipped"},
    ])
    st, impj = req_raw("POST", "/api/community/fishbrain/import", fb_json, ctype="application/json")
    impj = as_dict(impj)
    check("FB import: JSON variant -> 200 imported=1 skipped=1",
          st == 200 and impj.get("imported") == 1 and impj.get("skipped") == 1,
          f"(got {st} {impj!r:.160})")
    json_batch = impj.get("batch_id")
    _jr = (impj.get("rows") or [{}])[0]
    check("FB import: JSON fuzzy keys mapped (speciesName/createdAt/weightLbs/spot)",
          _jr.get("species") == "Kokanee"
          and _jr.get("date") == (_t0 - timedelta(days=1)).isoformat()
          and _jr.get("weight_lb") == 2.4
          and _jr.get("location") == "Bullards Bar marina"
          and _jr.get("water") == "new-bullards-bar",
          f"(got {_jr!r:.160})")

    # Unified GET: both sections, recency + water filters, reddit disabled.
    st, com = req("GET", "/api/community?days=30")
    com = as_dict(com)
    fb = com.get("fishbrain", {})
    rd = com.get("reddit", {})
    check("community GET: 200 with fishbrain{batches,rows} + reddit{enabled,...}",
          st == 200 and "batches" in fb and "rows" in fb
          and "enabled" in rd and "stale" in rd and "fetched_at" in rd and "posts" in rd,
          f"(got {st} {com!r:.160})")

    def _has_row(rows, species, loc_frag):
        return any(r.get("species") == species and loc_frag in (r.get("location") or "")
                   for r in rows)

    _rows30 = fb.get("rows", [])
    check("community GET: all 5 imported rows visible in 30d window",
          _has_row(_rows30, "Rainbow Trout", "Collins Lake")
          and _has_row(_rows30, "Kokanee", "New Bullards Bar")
          and _has_row(_rows30, "Chinook Salmon", "Sacramento River")
          and _has_row(_rows30, "Trout", "Some Random Pond")
          and _has_row(_rows30, "Kokanee", "Bullards Bar marina"),
          f"(n={len(_rows30)})")
    _batch_ids = [b.get("batch_id") for b in fb.get("batches", [])]
    check("community GET: both import batches listed",
          csv_batch in _batch_ids and json_batch in _batch_ids, f"(batches={_batch_ids!r})")
    check("community GET: reddit disabled (env unset) -> enabled=false, posts=[]",
          rd.get("enabled") is False and rd.get("posts") == [] and rd.get("stale") is False,
          f"(got {rd!r:.160})")

    st, com_w = req("GET", "/api/community?water_slug=collins-lake&days=30")
    rows_w = as_dict(com_w).get("fishbrain", {}).get("rows", []) if st == 200 else []
    check("community GET: water filter -> only the Collins row",
          st == 200 and len(rows_w) == 1 and rows_w[0]["species"] == "Rainbow Trout"
          and rows_w[0]["water"] == "collins-lake",
          f"(got {st} n={len(rows_w)})")
    st, _ = req("GET", "/api/community?water_slug=nope&days=7")
    check("community GET: unknown water_slug -> 404", st == 404, f"(got {st})")

    # Batch undo: delete removes exactly that batch.
    st, delr = req("DELETE", f"/api/community/fishbrain/import/{csv_batch}")
    check("FB delete: CSV batch removed -> 200 (4 rows)",
          st == 200 and as_dict(delr).get("deleted_rows") == 4, f"(got {st} {delr!r:.120})")
    st, com2 = req("GET", "/api/community?days=30")
    rows2 = as_dict(com2).get("fishbrain", {}).get("rows", [])
    check("FB delete: CSV rows gone, JSON row remains",
          st == 200 and not _has_row(rows2, "Rainbow Trout", "Collins Lake")
          and not _has_row(rows2, "Chinook Salmon", "Sacramento River")
          and _has_row(rows2, "Kokanee", "Bullards Bar marina"),
          f"(n={len(rows2)})")
    st, _ = req("DELETE", f"/api/community/fishbrain/import/{json_batch}")
    check("FB delete: JSON batch removed -> 200", st == 200, f"(got {st})")
    st, com3 = req("GET", "/api/community?days=3650")
    fb3 = as_dict(com3).get("fishbrain", {})
    check("FB delete: DB back to as-found (row/batch counts restored)",
          st == 200 and len(fb3.get("rows", [])) == prior_rows
          and len(fb3.get("batches", [])) == prior_batches,
          f"(rows={len(fb3.get('rows', []))}/{prior_rows} batches={len(fb3.get('batches', []))}/{prior_batches})")
    st, _ = req("DELETE", "/api/community/fishbrain/import/nope123")
    check("FB delete: unknown batch -> 404", st == 404, f"(got {st})")
    st, _bad = req_raw("POST", "/api/community/fishbrain/import", "foo,bar\n1,2\n")
    check("FB import: unrecognized columns -> 400", st == 400, f"(got {st})")
    st, _bad = req_raw("POST", "/api/community/fishbrain/import", "   ")
    check("FB import: empty body -> 400", st == 400, f"(got {st})")

    # 11. live conditions (USGS IV + barometer + alerts).
    test_conditions(BASE)

    # 10. cleanup: delete catch + trip
    st, _ = req("DELETE", f"/api/catches/{catch_id}")
    check("delete catch -> 204", st == 204, f"(got {st})")
    st, _ = req("DELETE", f"/api/trips/{trip_id}")
    check("delete trip -> 204", st == 204, f"(got {st})")
    st, trips = req("GET", f"/api/trips?user_id={user_id}")
    check("deleted trip gone from list", st == 200 and all(t["id"] != trip_id for t in trips))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
