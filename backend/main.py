"""Plimsoll FastAPI app.

Startup contract (architecture-decisions-A-B.md §24): only reads local
files, never calls a database. Everything under `data/store/` is created
on demand by the storage layer itself.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.agent import router as agent_router
from backend.api.aliases import router as aliases_router
from backend.api.chains import router as chains_router
from backend.api.demo_auth import demo_password_gate
from backend.api.sessions import router as sessions_router
from backend.api.system import router as system_router
from backend.config import FRONTEND_DIST

app = FastAPI(
    title="Plimsoll API",
    version="0.1.0",
    description="船舶技術文件版本差異比對 — local-first backend.",
)

# Registered before CORS so CORS stays the outermost layer (Starlette runs
# the last-added middleware first). No-op unless PLIMSOLL_DEMO_PASSWORD is set.
app.middleware("http")(demo_password_gate)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(sessions_router)
app.include_router(chains_router)
app.include_router(aliases_router)
app.include_router(agent_router)


class _SpaStaticFiles(StaticFiles):
    """`index.html`'s filename never changes across a rebuild, but its
    content does (it references the new build's hashed asset filenames) —
    with no Cache-Control, a browser that already has it cached may never
    ask the server again, so a `docker compose up --build` can ship new
    code that a returning browser silently never sees (confirmed live,
    2026-09-28: rebuilt image had the new bundle, only a hard-refresh
    revealed it). Every other file under dist/ lives under assets/ with a
    content hash in its own filename (Vite's default), so those are safe to
    cache forever — a changed file simply gets a new name instead of
    invalidating an old one."""

    def file_response(self, full_path, stat_result, scope, status_code: int = 200):
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        is_hashed_asset = f"{os.sep}assets{os.sep}" in str(full_path)
        response.headers["cache-control"] = (
            "public, max-age=31536000, immutable" if is_hashed_asset else "no-store"
        )
        return response


# Static SPA mount must come after all /api routes.
if FRONTEND_DIST.exists():
    app.mount("/", _SpaStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def fallback_root():
        return {
            "message": "Plimsoll API running. frontend/dist missing.",
            "hint": "cd frontend && npm install && npm run build",
        }
