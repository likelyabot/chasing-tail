#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING fishing-app server.

Usage: python3 scripts/smoke_test.py [BASE_URL]   (default http://localhost:8090)

Verifies the acceptance criteria:
  1. /healthz returns 200
  2. a second user can be created via API (multi-user capability)
  3. trip + catch CRUD round-trip (create/list/update/delete)
  4. weather endpoint returns real live NWS data for Collins Lake
  5. kayak gate: Loon Lake always NO KAYAK
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
    check("create trip -> 201", st == 201 and trip.get("water_name") == "Collins Lake", f"(got {st} {trip!r:.120})")
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
    nws = (wx or {}).get("nws", {}) if st == 200 else {}
    periods = nws.get("periods", [])
    check("weather: live NWS data for Collins Lake",
          st == 200 and nws.get("office") and len(periods) > 4
          and periods[0].get("shortForecast") and not nws.get("stale"),
          f"(st={st} office={nws.get('office')} periods={len(periods)} stale={nws.get('stale')} err={nws.get('error')})")
    if periods:
        print(f"      NWS sample: {periods[0]['name']} {periods[0]['temperature']}{periods[0]['temperatureUnit']} {periods[0]['shortForecast']}")
    om = (wx or {}).get("open_meteo", {})
    check("weather: Open-Meteo hourly present", st == 200 and len(om.get("hourly", {}).get("time", [])) >= 24)
    usgs = (wx or {}).get("usgs")
    print(f"      USGS (Collins Lake): {usgs!r:.160}")

    # NBB gauge (best-effort: USGS has been flaky; accept live OR flagged stale OR explicit error)
    st, wx2 = req("GET", "/api/weather/new-bullards-bar")
    usgs2 = (wx2 or {}).get("usgs") if st == 200 else None
    ok_usgs = isinstance(usgs2, dict) and (
        usgs2.get("stage_ft") is not None or "error" in usgs2 or "note" in usgs2
    )
    check("weather: NBB USGS layer responds (live/stale/explicit-error)", ok_usgs,
          f"(got {usgs2!r:.160})")

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
