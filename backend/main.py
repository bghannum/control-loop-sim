"""FastAPI app: CORS for the future Vite dev server, lifespan-managed
SimulationService (one instance, background tick task started on boot),
control + stream routers mounted. Local-only -- no auth, no deployment
config (see CLAUDE.md's Phase 9 decisions).
"""

import os
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import control, stream
from backend.service import SimulationService
from config_schema import load_config

VITE_DEV_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config("config.yaml")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    ai_client = anthropic.Anthropic(api_key=api_key) if api_key else None

    service = SimulationService(config, ai_client=ai_client)
    app.state.service = service
    # Starts paused, matching app.py's default -- a client hits
    # POST /session/run {"running": true} to begin ticking.
    try:
        yield
    finally:
        await service.shutdown()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[VITE_DEV_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(control.router)
app.include_router(stream.router)
