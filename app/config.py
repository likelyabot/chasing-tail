"""Runtime configuration from environment (see docker-compose contract)."""
import os
from pathlib import Path

# SQLite file. Compose sets /app/data/fishing.db (named volume). Local dev can
# point anywhere writable.
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/app/data/fishing.db")

# Optional Hermes gateway URL for the chat pane. Empty = chat disabled.
HERMES_CHAT_ENDPOINT = os.environ.get("HERMES_CHAT_ENDPOINT", "").rstrip("/")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").lower()

# Timezone label for display (compose sets America/Los_Angeles).
TZ = os.environ.get("TZ", "America/Los_Angeles")

# Where fetched weather/gauge responses are cached (next to the DB by default).
CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(Path(DATABASE_PATH).parent / "cache")))

# Upstream fetch policy.
UPSTREAM_TIMEOUT_S = float(os.environ.get("UPSTREAM_TIMEOUT_S", "20"))
USER_AGENT = "chasing-tail/0.1 (LAN trip planner; contact: likelyabot@users.noreply.github.com)"

# Reddit poller (OFFICIAL API, optional feature). Disabled unless BOTH
# credentials are set — the API then reports reddit.enabled=false and the UI
# shows a configure notice. Secrets only ever arrive via env vars (Portainer);
# never in code or the repo. Free personal "script"-type OAuth2 app.
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_SUBREDDITS = [
    s.strip() for s in os.environ.get("REDDIT_SUBREDDITS", "californiafishing,fishing").split(",")
    if s.strip()
]

# Cache TTLs (seconds).
TTL_NWS_POINTS = 7 * 24 * 3600   # lat/lon -> grid mapping rarely changes
TTL_NWS_FORECAST = 30 * 60
TTL_OPEN_METEO = 30 * 60
TTL_USGS = 15 * 60
TTL_REDDIT = 15 * 60

# Staleness threshold: older than this, cached data is labelled stale.
STALE_AFTER_S = 6 * 3600

# Reddit poller tuning.
REDDIT_LIMIT = 25            # posts per subreddit per poll (/hot?limit=)
REDDIT_MAX_SUBS = 4          # politeness: at most 4 feed requests per poll
REDDIT_RETRY_AFTER_CAP_S = 30
REDDIT_PRUNE_DAYS = 30       # drop stored posts older than this on each poll
