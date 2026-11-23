#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING fishing-app server.

Usage: python3 scripts/smoke_test.py [BASE_URL]   (default http://localhost:8090)

Verifies the acceptance criteria:
  1. /healthz returns 200
  2. a second user can be created via API (multi-user capability)
  3. trip + catch CRUD round-trip (create/list/update/delete)
  4. weather endpoint returns real live NWS data for Collins Lake
  5. kayak gate: Loon Lake always NO KAYAK
  6. dossier integration (2026-11-23 research-scout dossiers):
     - regs seeds match dossier §4 exactly (all four waters)
     - weather panel queries the correct USGS station IDs via OGC API
     - mid-Dec Sacramento trip recommends chinook (2/day, 4 possession)
     - Loon trip shows NO KAYAK flag AND road-status reminder
     - invalid ?date= -> 422
Exit code 0 = all pass.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
PASS, FAIL = 0, 0


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


def as_dict(x):
    """Coerce a response body to dict (non-JSON error bodies arrive as str)."""
    return x if isinstance(x, dict) else {}


def main():
    print(f"fishing-app smoke test -> {BASE}")

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

    st, trips = req("GET", f"/api/trips?user_id={user_id}")
    check("list trips contains new trip", st == 200 and any(t["id"] == trip_id for t in trips))

    st, trip = req("PATCH", f"/api/trips/{trip_id}", {"status": "completed", "notes": "edited"})
    check("update trip -> 200", st == 200 and trip.get("status") == "completed" and trip.get("notes") == "edited",
          f"(got {st} {trip!r:.120})")

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

    # 9. cleanup: delete catch + trip
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
