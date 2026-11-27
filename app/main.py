"""Chasing Tail(s) entrypoint: FastAPI app, /healthz, API routers, single-page UI.

LAN-only by design (no auth in v1 — trusted network). Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import catches, chat, community, conditions, gear, photos, recommend, regs, spots, trips, users, waters, weather
from .services import species_icons

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Photo storage lives on the data volume next to the DB; make sure the
    # dir exists (best-effort — a read-only mount just disables uploads).
    try:
        config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("cannot create photo dir %s — uploads will fail with a clear error",
                    config.PHOTO_DIR)
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
app.include_router(photos.router)
app.include_router(spots.router)
app.include_router(weather.router)
app.include_router(conditions.router)
app.include_router(community.router)
app.include_router(regs.router)
app.include_router(recommend.router)
app.include_router(chat.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Compose healthcheck target: 200 when the app is up."""
    return JSONResponse({"ok": True, "tz": config.TZ, "chat_enabled": bool(config.HERMES_CHAT_ENDPOINT)})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    """Browser-tab icon: the fish tail (SVG). Served at the root so the
    <link rel=icon> href stays short; the same file is also under /static."""
    p = STATIC_DIR / "favicon.svg"
    if not p.is_file():  # defensive: 404 instead of a 500 if the asset is missing
        return JSONResponse({"detail": "favicon not found"}, status_code=404)
    return FileResponse(p, media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    """Legacy .ico probe (some browsers/tools ask before honoring <link>):
    redirect to the SVG tail so it never 404s in the logs."""
    return RedirectResponse("/favicon.svg", status_code=302)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """PWA service worker at the ROOT so its default scope is "/" (controlling
    the whole app, incl. the navigation to index.html). Served no-cache so a
    deploy with a bumped cache version is picked up on the next visit."""
    p = STATIC_DIR / "sw.js"
    if not p.is_file():  # defensive: 404 instead of a 500 if the asset is missing
        return JSONResponse({"detail": "service worker not found"}, status_code=404)
    return FileResponse(p, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    """PWA manifest (installability: name, standalone display, 192/512 icons).
    The same file is also reachable at /static/manifest.webmanifest via the
    static mount; the root URL keeps the <link rel=manifest> href canonical."""
    p = STATIC_DIR / "manifest.webmanifest"
    if not p.is_file():
        return JSONResponse({"detail": "manifest not found"}, status_code=404)
    return FileResponse(p, media_type="application/manifest+json")


@app.get("/api/species-icon/{name}")
def species_icon(name: str):
    """Resolve a species name to its pixel-art sprite (Plan tab icons).

    Mirrors the client-side table in app/static/app.js (the UI resolves
    sprites locally; this endpoint exists so the mapping is exercisable
    from the smoke test and future server-side consumers). Unrecognized
    names fall back to generic.png — always 200, never a broken image.
    """
    sprite = species_icons.resolve_sprite(name)
    return {
        "name": name,
        "sprite": sprite,
        "src": f"/static/{species_icons.SPRITE_DIR}/{sprite}",
    }


# Everything else under /static (app.js, style.css, sprites...).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Raster icons (fish-tail favicons/PWA icons) at /icons — backs the
# <link rel=icon> PNG fallback in index.html; same files live under /static.
app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons")
