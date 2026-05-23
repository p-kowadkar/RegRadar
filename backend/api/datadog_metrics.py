"""Push dashboard KPIs to Datadog as gauges. Best-effort; never raises."""
from __future__ import annotations

import os
from typing import Iterable

try:
    from datadog import initialize, statsd  # type: ignore
    _DD_OK = True
except Exception:  # pragma: no cover
    _DD_OK = False

_INITIALIZED = False


def _ensure_init() -> None:
    global _INITIALIZED
    if _INITIALIZED or not _DD_OK:
        return
    api_key = os.environ.get("DD_API_KEY")
    if not api_key:
        # No key configured -- silently disable.
        return
    initialize(
        api_key=api_key,
        api_host=f"https://api.{os.environ.get('DD_SITE', 'datadoghq.com')}",
        statsd_host="127.0.0.1",
        statsd_port=8125,
    )
    _INITIALIZED = True


def emit_dashboard_gauges(
    monitored: int,
    accounted_for: int,
    out_of_compliance: int,
    fixes_suggested: int,
    fixes_completed: int,
    extra_tags: Iterable[str] | None = None,
) -> None:
    """Emit one gauge per KPI. Tags are stable so panels keep working."""
    if not _DD_OK:
        return
    _ensure_init()
    if not _INITIALIZED:
        return

    tags = [
        f"service:{os.environ.get('DD_SERVICE', 'regradar-backend')}",
        f"env:{os.environ.get('DD_ENV', 'hackathon')}",
    ]
    if extra_tags:
        tags.extend(extra_tags)

    try:
        statsd.gauge("regradar.assets.monitored", monitored, tags=tags)
        statsd.gauge("regradar.assets.accounted_for", accounted_for, tags=tags)
        statsd.gauge("regradar.assets.out_of_compliance", out_of_compliance, tags=tags)
        statsd.gauge("regradar.fixes.suggested", fixes_suggested, tags=tags)
        statsd.gauge("regradar.fixes.completed", fixes_completed, tags=tags)
    except Exception:
        # statsd over UDP shouldn't fail, but never let metrics break the API
        pass
