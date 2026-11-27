"""main.py - Job Offer Hunter: the API (FastAPI) and, once built, the React pages it serves.

Run (from the repository):  python -m uvicorn backend.app.main:app --port 8600     then open http://127.0.0.1:8600
The API is documented at /docs. Keep it on 127.0.0.1: there is no login."""
from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core import ROOT, launch
from .routes_offers import router as offers_router
from .routes_search import router as search_router
from .routes_settings import router as settings_router

DIST = ROOT / "frontend" / "dist"
# Python takes the files' types from the Windows registry, where '.js' is often 'text/plain': the browser then refuses
# to run the pages' script and shows an empty page. The types of the files served here are set, whatever the registry says.
for _type, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg"), ("font/otf", ".otf"),
                    ("application/json", ".json"), ("text/html", ".html")):
    mimetypes.add_type(_type, _ext)


@asynccontextmanager
async def lifespan(_app):
    launch()  # a fresh session, unless the last search waits to be resumed
    yield


app = FastAPI(title="Job Offer Hunter", version="1.0", lifespan=lifespan,
              description="Career websites read every day; every offer dated, placed and ranked against your CV or keywords.")
for r in (search_router, offers_router, settings_router):
    app.include_router(r)
app.mount("/fonts", StaticFiles(directory=ROOT / "static" / "fonts"), name="fonts")  # PP Telegraf, the app's typeface
app.mount("/brand", StaticFiles(directory=ROOT / "assets"), name="brand")  # logo and icon

if DIST.is_dir():  # the built React pages; any other path is a page of the single-page app
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str):
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
