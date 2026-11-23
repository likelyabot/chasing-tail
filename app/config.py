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
USER_AGENT = "fishing-app/0.1 (LAN trip planner; contact: likelyabot@users.noreply.github.com)"

# Cache TTLs (seconds).
TTL_NWS_POINTS = 7 * 24 * 3600   # lat/lon -> grid mapping rarely changes
TTL_NWS_FORECAST = 30 * 60
TTL_OPEN_METEO = 30 * 60
TTL_USGS = 15 * 60

# Staleness threshold: older than this, cached data is labelled stale.
STALE_AFTER_S = 6 * 3600
