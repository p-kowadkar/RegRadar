"""FastAPI entrypoint. Mounts the dashboard API and CORS for local dev."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.dashboard import router as dashboard_router
from .api.violations import router as violations_router
from .api.agents import router as agents_router

app = FastAPI(title="RegRadar API", version="0.1.0")

origins = os.environ.get(
    "APP_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(violations_router)
app.include_router(agents_router)


@app.get("/")
def root() -> dict:
    return {"service": "regradar-backend", "status": "ok"}
