"""Chasing Tail(s) entrypoint: FastAPI app, /healthz, API routers, single-page UI.

LAN-only by design (no auth in v1 — trusted network). Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import catches, chat, community, conditions, gear, recommend, trips, users, waters, weather

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    log.info("database ready at %s (tz=%s, chat_endpoint=%s)",
             config.DATABASE_PATH, config.TZ,
             "set" if config.HERMES_CHAT_ENDPOINT else "unset")
    yield
    from .services.usgs import aclose as usgs_aclose
    from .services.weather import aclose
    await aclose()
    await usgs_aclose()


app = FastAPI(
    title="Chasing Tail(s)",
    version="0.1.0",
    description="LAN-only fishing trip planner (FastAPI + SQLite).",
    lifespan=lifespan,
)

# LAN-friendly CORS (harmless on a trusted network; helps local dev tooling).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(waters.router)
app.include_router(trips.router)
app.include_router(catches.router)
app.include_router(gear.router)
app.include_router(weather.router)
app.include_router(conditions.router)
app.include_router(community.router)
app.include_router(recommend.router)
app.include_router(chat.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Compose healthcheck target: 200 when the app is up."""
    return JSONResponse({"ok": True, "tz": config.TZ, "chat_enabled": bool(config.HERMES_CHAT_ENDPOINT)})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


# Everything else under /static (app.js, style.css, icons...).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
