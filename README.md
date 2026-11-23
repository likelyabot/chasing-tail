# fishing-app

LAN-only fishing trip planner: FastAPI + SQLite, single container, no build
step. Plan trips, check live weather and reservoir levels, get rule-based
tackle recommendations (with a kayak safety gate), and log catches.

## Quick start (local)

```bash
# Option A: Docker (mirrors production)
docker build -t fishing-app:latest .
docker run --rm -p 8090:8000 \
  -v fishing_app_data:/app/data \
  fishing-app:latest
# open http://localhost:8090

# Option B: bare Python (dev)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_PATH=./data/fishing.db
uvicorn app.main:app --reload --port 8000
```

Production deploy: Portainer stack in the `likelyabot/docker-compose` repo,
folder `fishing/` (image built from this repo). See that repo's
`fishing/README.md` for the required `FISHING_APP_BIND_IP` variable — the
compose file fails fast if it's unset (LAN-only by design, no 0.0.0.0 bind).

## Configuration (env)

| Var | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `/app/data/fishing.db` | SQLite file (put it on a volume) |
| `HERMES_CHAT_ENDPOINT` | *(empty)* | Chat-pane upstream; empty = chat disabled |
| `LOG_LEVEL` | `info` | Logging level |
| `TZ` | `America/Los_Angeles` | Display timezone |
| `CACHE_DIR` | `<db dir>/cache` | Weather/gauge response cache |

## API overview

- `GET /healthz` — liveness (compose healthcheck)
- `GET/POST /api/users` — list / create users (multi-user capable)
- `GET /api/waters` — the four seeded waters
- `GET/POST/PATCH/DELETE /api/trips[/{id}]` — trip CRUD
- `GET/POST/PATCH/DELETE /api/catches[/{id}]` — catch CRUD (nested under trips)
- `GET /api/gear` — Angler's tackle
- `GET /api/weather/{water_slug}` — NWS forecast + Open-Meteo hourly + USGS gauge
- `GET /api/recommend?water_slug=&date=&species=&live_weather=` — rule-based plan
- `POST /api/chat` — **stub**: proxies to `HERMES_CHAT_ENDPOINT` if set, else "disabled"

Interactive docs: `http://localhost:8000/docs`.

## Weather sources & degradation

- **NWS** (`api.weather.gov`): points → gridpoint forecast. Cached 30 min
  (grid mapping 7 d).
- **Open-Meteo**: 48 h hourly temp/wind/gusts/precip-prob. Cached 30 min.
- **USGS** (reservoir levels; New Bullards Bar = gage **11413515**):
  layered fetch — instantaneous (`/nwis/iv/`) → daily (`/nwis/dv/`) → legacy
  updated-values (`waterdata.usgs.gov/nwis/uv`). Cached 15 min.
- Every source degrades gracefully: on fetch failure the last cached payload
  is served with `stale: true` and its `fetched_at` timestamp; with no cache
  at all the panel shows an explicit error instead of crashing.

## Recommendation engine (v1, rules)

Seeded species-per-water monthly activity curves + weather modifiers
(cold/warm fronts, wind bands, rain, reservoir level deltas) → ranked species
with tactics mapped to the actual tackle (Dobyns CL693SF + Sahara 2500J,
Abu Garcia Vendetta med/fast; Kastmasters, Panther Martins, trout bugs,
spoons, Carolina-rig weights, wacky worms).

**Kayak safety gate:** Angler owns a kayak and has never used it —
Loon Lake is always flagged **NO KAYAK**; other waters flag **KAYAK CAUTION**
when sustained wind ≥ 10 mph or gusts ≥ 15 mph.

## Data

Schema: `users`, `waters` (static seed), `trips`, `catches` (cascades with
trips). One user (Angler) is seeded on first start; anyone can create trips
and catches. No auth in v1 — trusted LAN only.

## Smoke test

Against a running server:

```bash
python3 scripts/smoke_test.py http://localhost:8090
```

Covers: healthz, user creation, trip+catch CRUD round-trip, live NWS weather
for Collins Lake, and the kayak gate.
