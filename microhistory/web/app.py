"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from microhistory.web.routes_api import router as api_router
from microhistory.web.routes_pages import router as pages_router

_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="MicroHistory", version="0.1.0")

    # API routes first (so /api/* takes priority)
    app.include_router(api_router)

    # Static files (CSS, JS)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # HTML page routes
    app.include_router(pages_router)

    return app
