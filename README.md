# Chasing Tail(s)

LAN-only fishing trip planner: FastAPI + SQLite, single container, no build
step. Plan trips, check live weather and reservoir levels, get rule-based
tackle recommendations (with a kayak safety gate), and log catches.

## Quick start (local)

```bash
# Option A: Docker (mirrors production)
docker build -t chasing-tail:latest .
docker run --rm -p 8090:8000 \
  -v fishing_app_data:/app/data \
  chasing-tail:latest
# open http://localhost:8090

# Option B: bare Python (dev)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_PATH=./data/fishing.db
uvicorn app.main:app --reload --port 8000
```

Production deploy: Portainer stack in the `likelyabot/docker-compose` repo,
folder `fishing/` (image built from this repo). The compose file consumes
the GHCR image with `pull_policy: always` — see that repo's
`fishing/README.md` for the stack variables.

## Configuration (env)

| Var | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `/app/data/fishing.db` | SQLite file (put it on a volume) |
| `HERMES_CHAT_ENDPOINT` | *(empty)* | Chat-pane upstream; empty = chat disabled |
| `LOG_LEVEL` | `info` | Logging level |
| `TZ` | `America/Los_Angeles` | Display timezone |
| `CACHE_DIR` | `<db dir>/cache` | Weather/gauge response cache |
| `REDDIT_CLIENT_ID` | *(empty)* | Reddit OAuth2 client id (free personal "script" app). Feature is **disabled** unless both `REDDIT_*` vars are set — e.g. `REDDIT_CLIENT_ID=my-client-id` |
| `REDDIT_CLIENT_SECRET` | *(empty)* | Reddit OAuth2 client secret — e.g. `REDDIT_CLIENT_SECRET=your-secret-here` (env only, never in the repo) |
| `REDDIT_SUBREDDITS` | `californiafishing,fishing` | Comma-separated subreddits to poll (≤4 per poll) |

## API overview

- `GET /healthz` — liveness (compose healthcheck)
- `GET/POST /api/users` — list / create users (multi-user capable)
- `GET /api/waters` — the four seeded waters
- `GET/POST/PATCH/DELETE /api/trips[/{id}]` — trip CRUD
- `GET/POST/PATCH/DELETE /api/catches[/{id}]` — catch CRUD (nested under trips)
- `GET/PUT/DELETE /api/gear` — tackle list (editable in UI; resets to repo defaults)
- `GET /api/weather/{water_slug}` — NWS forecast + Open-Meteo hourly + USGS gauge + lunar phase (computed locally)
- `GET /api/community?water_slug=&days=7` — Community tab: FishBrain imports + Reddit feed (both water/recency-filtered)
- `POST /api/community/fishbrain/import` — paste a FishBrain CSV/JSON export (fuzzy column detection, tolerant dates; unparseable rows skipped + counted)
- `DELETE /api/community/fishbrain/import/{batch_id}` — undo an import batch
- `GET /api/recommend?water_slug=&date=&species=&live_weather=` — rule-based plan
- `POST /api/chat` — **stub**: proxies to `HERMES_CHAT_ENDPOINT` if set, else "disabled"

Interactive docs: `http://localhost:8000/docs`.

## Weather sources & degradation

- **NWS** (`api.weather.gov`): points → gridpoint forecast. Cached 30 min
  (grid mapping 7 d).
- **Open-Meteo**: 48 h hourly temp/wind/gusts/precip-prob. Cached 30 min.
- **USGS** (reservoir/river levels; e.g. New Bullards Bar = gages **11413515**
  stage + **11413520** outflow): OGC API (`api.waterdata.usgs.gov/ogcapi/v1`)
  per station — `latest-continuous` first, falling back to `latest-daily` for
  stations that only publish daily (NBB's pair, verified 2026-11-23).
  Dormant stations are labeled, not silently dropped. Cached 15 min.
- **Lunar phase**: computed locally in-process (fixed almanac-verified
  new-moon epoch + mean synodic month — `app/services/lunar.py`, validated
  against published 2026 almanac dates in the smoke test). No external API;
  the Weather tab shows a 🌑–🌘 line beside sunrise/sunset for every water.
- Every source degrades gracefully: on fetch failure the last cached payload
  is served with `stale: true` and its `fetched_at` timestamp; with no cache
  at all the panel shows an explicit error instead of crashing.

## Community tab (FishBrain + Reddit)

- **FishBrain (manual):** the user exports his own journal/catches on his
  phone and pastes the CSV/JSON into the Community tab. `POST
  /api/community/fishbrain/import` detects columns fuzzily (case-insensitive,
  punctuation-stripped variants: `species|fish|species_name`, `date|time|created`,
  `weight|wt|lbs`, `length|inches`, `location|spot|water|area`, `notes|comments|details`,
  `photo|image|url`…), tolerates ISO / US m/d/y / "Mon DD YYYY" dates and epoch
  values; unparseable rows are skipped and counted, never fatal. Locations are
  keyword-matched against the four waters + aliases (Collins Lake/Merle
  Collins/Virginia Ranch; New Bullards Bar/Bullards Bar; Loon Lake/Crystal
  Basin; Sacramento River/Westport/Red Bluff/Colusa); unmatched rows show
  under "Other". Each import is a batch — `DELETE …/{batch_id}` undoes it.
- **Reddit (optional, official API):** enabled only when `REDDIT_CLIENT_ID`
  + `REDDIT_CLIENT_SECRET` are both set (OAuth2 client_credentials, free
  personal "script" app). Otherwise the API reports `reddit.enabled: false`
  and the UI shows a muted configure notice — disabled, not errored.
  Fetch-on-request with the weather-style file cache: 15-min TTL, ≤4 feed
  requests per poll (`/r/{sub}/hot`), 429 + Retry-After honored, Reddit down
  ⇒ last good feed served with `stale: true`, never a 500. Posts are stored
  in `reddit_posts` (dedupe by `reddit_id`, 30-day prune per poll) and
  water-classified with the same alias set, plus disambiguation: "Loon Lake"
  / "Collins Lake" only match on public posts when accompanied by CA context
  (a county name or an explicit California/CA mention) or a second alias.
  Secrets only ever via env vars — the repo contains no credentials.

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
trips), `gear` (single row — user-edited tackle, seeded once from the repo
defaults and never refreshed on boot; `DELETE /api/gear` drops it back to
defaults), `fishbrain_batches` + `fishbrain_rows` (user-imported FishBrain
exports; rows cascade-delete with their batch), `reddit_posts` (polled Reddit
feed; dedupe by `reddit_id`, 30-day prune). One user (Angler) is seeded on
first start; anyone can create trips and catches. No auth in v1 — trusted LAN
only.

## Smoke test

Against a running server:

```bash
python3 scripts/smoke_test.py http://localhost:8090
```

Covers: healthz, user creation, trip+catch CRUD round-trip, live NWS weather
for Collins Lake, the kayak gate, the gear edit round-trip (PUT/422/
DELETE + restore), and the Community tab (FishBrain CSV/JSON import with
fuzzy columns + tolerant dates + water matching + batch undo, unified GET
filters, Reddit disabled path, hermetic parser/matching fixtures — no live
Reddit calls). Leaves the DB as found.
