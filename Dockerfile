# RegRadar backend — Hugging Face Spaces Docker image.
# Free CPU-basic tier sleeps after 48h idle; UptimeRobot ping every 5 min keeps it warm.

FROM python:3.11-slim

# System deps needed by pyarrow + cryptography wheels on slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (HF Spaces convention — uid 1000)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"
WORKDIR /home/user/app

# Install Python deps first for layer caching
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy backend + seeds (frontend lives on Cloudflare Pages, not in this image)
COPY --chown=user backend/ ./backend/
COPY --chown=user seed/ ./seed/

# Default to HF Spaces' 7860; DO App Platform sets $PORT=8080 at runtime,
# Railway/Fly.io set their own. Shell-form CMD expands the variable.
ENV PORT=7860 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

# Lightweight health endpoint at GET /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-7860}/health" || exit 1

CMD python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}
