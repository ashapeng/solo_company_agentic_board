"""FastAPI application assembly for the Agentic Board API."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .routes import board, execution, harness, memory, system
from .state import UI_DIST_ASSETS


app = FastAPI(
    title="Agentic Board API",
    description="A council of world-expert AI agents that deliberate as a company board",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_local_only(request: Request, call_next):
    """Keep the board API local by default until auth is added."""
    if os.getenv("AGENTIC_BOARD_ALLOW_REMOTE") == "1":
        return await call_next(request)

    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        return JSONResponse(
            status_code=403,
            content={
                "code": "remote_access_disabled",
                "message": "Agentic Board API is local-only by default.",
            },
        )
    return await call_next(request)


app.include_router(system.router)
app.include_router(board.router)
app.include_router(execution.router)
app.include_router(memory.router)
app.include_router(harness.router)

if UI_DIST_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST_ASSETS), name="frontend-assets")
app.mount("/ui", StaticFiles(directory="ui"), name="ui")
