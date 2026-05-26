"""FastAPI entrypoint. Mounts the dashboard API and CORS for local dev."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Optional Logfire instrumentation. No-op if LOGFIRE_TOKEN isn't set.
# Free 10M spans/mo from Pydantic, first-party support for Pydantic AI.
if os.environ.get("LOGFIRE_TOKEN"):
    import logfire
    logfire.configure(
        token=os.environ["LOGFIRE_TOKEN"],
        service_name=os.environ.get("LOGFIRE_SERVICE_NAME", "regradar-backend"),
        environment=os.environ.get("APP_ENV", "development"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_pydantic_ai()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from .api.dashboard import router as dashboard_router
from .api.violations import router as violations_router
from .api.agents import router as agents_router
from .api.trigger import router as trigger_router
from .api.security import limiter

app = FastAPI(title="RegRadar API", version="0.1.0")

# SlowAPI wiring. `limiter` is defined in backend/api/security.py and uses a
# smart key_func: per-request UUID for BYOK users (never throttled), per-IP
# for demo-pool users (throttled by DEMO_API_RATE_LIMIT).
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": str(exc.detail),
            "hint": "Bring your own LLM key via X-User-LLM-Key header to bypass.",
        },
    )

# Wire Logfire FastAPI instrumentation now that `app` exists.
if os.environ.get("LOGFIRE_TOKEN"):
    import logfire
    logfire.instrument_fastapi(app, capture_headers=False)

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
app.include_router(trigger_router)


@app.get("/")
def root() -> dict:
    return {"service": "regradar-backend", "status": "ok"}


@app.get("/health")
def health() -> dict:
    """Liveness probe. Used by HF Spaces healthcheck and UptimeRobot keep-warm pings."""
    return {"status": "ok"}
