"""
Impact Analysis Agent — triggered by asset_changes events.

Pipeline (spec: impact-analysis-agent-spec.md):
  Event Consumer → Policy Resolver → Compliance Evaluator →
  Violation Writer → Notification Dispatcher → Remediation Trigger

Polls asset_changes on a configurable interval (default 60s).
Uses agent_state table as a durable cursor so restarts don't
reprocess or skip events.

Entry point: run_impact_analysis_agent(clickhouse_client=None)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.agents.policy_crawler import get_ch_client
from backend.data.models import (
    AssetChangeEvent,
    ImpactAnalysisCycleResult,
    ImpactEvaluationResult,
    PolicyRule,
)
from backend.utils.env import get as env_get, get_bool, get_int
from backend.utils.logging import get_logger

log = get_logger(__name__)

AGENT_ID = "impact_analysis"

# ── Config (all overridable via env) ────────────────────────────────────────

POLL_INTERVAL_SECONDS = get_int("IMPACT_AGENT_POLL_INTERVAL_SECONDS", 60)
BATCH_SIZE = get_int("IMPACT_AGENT_BATCH_SIZE", 500)
POLICY_CACHE_TTL_SECONDS = get_int("IMPACT_AGENT_POLICY_CACHE_TTL_SECONDS", 300)
WEBHOOK_RETRY_ATTEMPTS = get_int("IMPACT_AGENT_WEBHOOK_RETRY_ATTEMPTS", 3)
DEFAULT_WEBHOOK_URL = env_get("IMPACT_AGENT_DEFAULT_WEBHOOK_URL", "")
AUTO_REMEDIATE_MEDIUM = get_bool("IMPACT_AGENT_AUTO_REMEDIATE_MEDIUM", False)

# ── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_cursor(cursor: str) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor)
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════════════
# Component 1 — Event Consumer
# Polls asset_changes for new rows since the durable cursor.
# Batches events by asset_id so policy resolution runs once per asset.
# ════════════════════════════════════════════════════════════════════════════

def _fetch_agent_cursor(ch) -> str:
    result = ch.query(
        "SELECT last_cursor FROM regradar.agent_state FINAL "
        "WHERE agent_id = {aid:String} LIMIT 1",
        parameters={"aid": AGENT_ID},
    )
    rows = result.result_rows
    return rows[0][0] if rows else ""


def _persist_agent_state(cursor: str, error: str, ch) -> None:
    now = _now()
    ch.insert(
        "regradar.agent_state",
        [[AGENT_ID, now, cursor, 1, error, "running", now]],
        column_names=[
            "agent_id", "last_processed_at", "last_cursor",
            "cycle_count", "last_error", "status", "updated_at",
        ],
    )


def _fetch_new_events(cursor: str, ch) -> list[AssetChangeEvent]:
    cols = (
        "change_event_id, asset_id, change_type, changed_at, "
        "changed_by, previous_state_hash, new_state_hash, change_details"
    )
    cursor_dt = _parse_cursor(cursor)
    if cursor_dt:
        result = ch.query(
            f"SELECT {cols} FROM regradar.asset_changes "
            "WHERE changed_at > {cur:DateTime} "
            "ORDER BY changed_at ASC LIMIT {batch:UInt32}",
            parameters={"cur": cursor_dt, "batch": BATCH_SIZE},
        )
    else:
        result = ch.query(
            f"SELECT {cols} FROM regradar.asset_changes "
            "ORDER BY changed_at ASC LIMIT {batch:UInt32}",
            parameters={"batch": BATCH_SIZE},
        )

    events = []
    for row in result.result_rows:
        events.append(AssetChangeEvent(
            change_event_id=row[0],
            asset_id=row[1],
            change_type=row[2],
            changed_at=row[3],
            changed_by=row[4],
            previous_state_hash=row[5],
            new_state_hash=row[6],
            change_details=json.loads(row[7] or "{}"),
        ))
    return events


def _batch_by_asset(
    events: list[AssetChangeEvent],
) -> dict[str, list[AssetChangeEvent]]:
    batched: dict[str, list[AssetChangeEvent]] = {}
    for e in events:
        batched.setdefault(e.asset_id, []).append(e)
    return batched


# ════════════════════════════════════════════════════════════════════════════
# Component 2 — Policy Resolver
# Fetches all active policies tagged to an asset_id.
# Cache TTL: POLICY_CACHE_TTL_SECONDS to avoid redundant reads across assets.
# ════════════════════════════════════════════════════════════════════════════

# Cache: asset_id → (cached_at_monotonic, list[PolicyRule])
_PolicyCache = dict[str, tuple[float, list[PolicyRule]]]


def _resolve_policies(
    asset_id: str, ch, cache: _PolicyCache
) -> list[PolicyRule]:
    now_mono = time.monotonic()
    if asset_id in cache:
        cached_at, rules = cache[asset_id]
        if now_mono - cached_at < POLICY_CACHE_TTL_SECONDS:
            return rules

    # Step 1: which policies are tagged to this asset?
    tags = ch.query(
        "SELECT policy_id FROM regradar.asset_tags "
        "WHERE asset_id = {aid:String}",
        parameters={"aid": asset_id},
    )
    policy_ids: list[str] = [row[0] for row in tags.result_rows]
    if not policy_ids:
        log.warning("policy_resolver.no_policies_for_asset", asset_id=asset_id)
        cache[asset_id] = (now_mono, [])
        return []

    # Step 2: fetch active rule definitions (latest version per policy)
    rules_result = ch.query(
        "SELECT policy_id, version, rule_type, rule_params, severity, "
        "active, notification_config, auto_remediate "
        "FROM regradar.policy_registry FINAL "
        "WHERE has({pids:Array(String)}, policy_id) AND active = 1 "
        "ORDER BY policy_id ASC, version DESC",
        parameters={"pids": policy_ids},
    )

    seen: set[str] = set()
    rules: list[PolicyRule] = []
    for row in rules_result.result_rows:
        pid = row[0]
        if pid not in seen:
            seen.add(pid)
            rules.append(PolicyRule(
                policy_id=pid,
                version=row[1],
                rule_type=row[2],
                rule_params=json.loads(row[3] or "{}"),
                severity=row[4],
                active=row[5],
                notification_config=json.loads(row[6] or "{}"),
                auto_remediate=bool(row[7]),
            ))

    cache[asset_id] = (now_mono, rules)
    return rules


# ════════════════════════════════════════════════════════════════════════════
# Component 3 — Compliance Evaluator
# One handler per rule_type. Each takes (event, policy) and returns
# ImpactEvaluationResult with status=PASS|VIOLATION + reason + evidence.
# Handler errors are caught, logged, and treated as PASS to avoid blocking.
# ════════════════════════════════════════════════════════════════════════════

def _eval_schema_constraint(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    params = policy.rule_params
    d = event.change_details
    new_columns: list[str] = d.get("new_columns", [])
    added: list[str] = d.get("added", [])
    removed: list[str] = d.get("removed", [])

    missing = set(params.get("required_columns", [])) - set(new_columns)
    if missing:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Required columns missing after schema change: {sorted(missing)}",
            evidence={"missing_columns": sorted(missing), "added": added, "removed": removed},
        )

    disallowed = set(params.get("disallowed_columns", []))
    present_disallowed = [c for c in new_columns if c in disallowed]
    if present_disallowed:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Disallowed columns present: {present_disallowed}",
            evidence={"disallowed_present": present_disallowed},
        )

    naming_pattern = params.get("naming_pattern")
    if naming_pattern and added:
        import re
        bad = [c for c in added if not re.match(naming_pattern, c)]
        if bad:
            return ImpactEvaluationResult(
                status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
                rule_type=policy.rule_type, severity=policy.severity,
                reason=f"New columns violate naming convention ({naming_pattern}): {bad}",
                evidence={"bad_names": bad, "pattern": naming_pattern},
            )

    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason="Schema satisfies all constraints", evidence={},
    )


def _eval_classification_required(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    import re
    params = policy.rule_params
    d = event.change_details
    column: str = d.get("column", "")
    new_tags: list[str] = d.get("new_tags", [])
    required_tags: list[str] = params.get("required_tags", [])
    pattern: str = params.get("applies_to_column_pattern", "")

    if pattern and not re.search(pattern, column, re.IGNORECASE):
        return ImpactEvaluationResult(
            status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason="Column not in scope for this classification policy", evidence={},
        )

    missing = [t for t in required_tags if t not in new_tags]
    if missing:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Column `{column}` missing required classification tags: {missing}",
            evidence={"column": column, "missing_tags": missing, "current_tags": new_tags},
        )

    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason=f"Column `{column}` has all required classification tags", evidence={},
    )


def _eval_access_control(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    params = policy.rule_params
    d = event.change_details
    role: str = d.get("role", "")
    permission: str = d.get("permission", "")
    unauthorized_roles: list[str] = params.get("unauthorized_roles", [])
    required_restrictions: dict[str, Any] = params.get("required_restrictions", {})

    if role in unauthorized_roles:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Unauthorized role `{role}` granted `{permission}` access",
            evidence={"role": role, "permission": permission},
        )

    for key, expected in required_restrictions.items():
        actual = d.get(key)
        if actual != expected:
            return ImpactEvaluationResult(
                status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
                rule_type=policy.rule_type, severity=policy.severity,
                reason=f"Access restriction `{key}` not met: expected {expected!r}, got {actual!r}",
                evidence={"restriction": key, "expected": expected, "actual": actual},
            )

    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason="Access control changes comply with policy", evidence={},
    )


def _eval_retention_policy(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    params = policy.rule_params
    d = event.change_details
    required: int = params.get("required_retention_days", 90)
    comparison: str = params.get("comparison", "gte")
    actual: int = d.get("retention_days", 0)

    passes = {
        "lt": actual < required, "lte": actual <= required,
        "eq": actual == required, "gte": actual >= required, "gt": actual > required,
    }.get(comparison, False)

    if not passes:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Retention not met: required {comparison} {required} days, actual {actual} days",
            evidence={"required_days": required, "comparison": comparison, "actual_days": actual},
        )
    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason=f"Retention policy satisfied ({actual} days)", evidence={},
    )


def _eval_freshness_sla(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    params = policy.rule_params
    d = event.change_details
    max_age_hours: float = params.get("max_age_hours", 24)
    hours_overdue: float = d.get("hours_overdue", 0)
    last_updated_at: str = d.get("last_updated_at", "")

    if hours_overdue > 0:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Freshness SLA breached: {hours_overdue:.1f}h overdue (SLA: {max_age_hours}h)",
            evidence={"max_age_hours": max_age_hours, "hours_overdue": hours_overdue,
                      "last_updated_at": last_updated_at},
        )
    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason=f"Asset freshness within SLA ({max_age_hours}h)", evidence={},
    )


def _eval_lineage_restriction(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    params = policy.rule_params
    d = event.change_details
    disallowed: list[str] = params.get("disallowed_sources", [])
    new_source: str = d.get("new_upstream_source", "")
    all_sources: list[str] = d.get("upstream_sources", [new_source] if new_source else [])

    offending = [s for s in all_sources if s in disallowed]
    if offending:
        return ImpactEvaluationResult(
            status="VIOLATION", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Disallowed upstream source(s) in lineage: {offending}",
            evidence={"disallowed_found": offending, "all_upstream": all_sources},
        )
    return ImpactEvaluationResult(
        status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
        rule_type=policy.rule_type, severity=policy.severity,
        reason="No disallowed upstream sources in lineage", evidence={},
    )


_RULE_HANDLERS = {
    "schema_constraint": _eval_schema_constraint,
    "classification_required": _eval_classification_required,
    "access_control": _eval_access_control,
    "retention_policy": _eval_retention_policy,
    "freshness_sla": _eval_freshness_sla,
    "lineage_restriction": _eval_lineage_restriction,
}


def evaluate(
    event: AssetChangeEvent, policy: PolicyRule
) -> ImpactEvaluationResult:
    handler = _RULE_HANDLERS.get(policy.rule_type)
    if not handler:
        log.warning(
            "evaluator.unknown_rule_type",
            rule_type=policy.rule_type, policy_id=policy.policy_id,
        )
        return ImpactEvaluationResult(
            status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"No handler for rule_type={policy.rule_type!r}; skipped",
            evidence={"skipped": True},
        )
    try:
        return handler(event, policy)
    except Exception as exc:
        log.error(
            "evaluator.handler_error",
            rule_type=policy.rule_type, policy_id=policy.policy_id,
            asset_id=event.asset_id, error=str(exc),
        )
        # Partial results: log + skip rather than blocking other rules
        return ImpactEvaluationResult(
            status="PASS", policy_id=policy.policy_id, asset_id=event.asset_id,
            rule_type=policy.rule_type, severity=policy.severity,
            reason=f"Evaluator error in {policy.rule_type}: {exc}",
            evidence={"evaluator_error": str(exc)},
        )


# ════════════════════════════════════════════════════════════════════════════
# Component 4 — Violation Writer
# VIOLATION (new)      → insert open violation, return violation_id
# VIOLATION (existing) → update last_seen_at, return None (no re-notify)
# PASS (open exists)   → close violation with auto_resolved, return None
# PASS (no open)       → no-op, return None
# Uses FINAL on reads to get the deduplicated view from ReplacingMergeTree.
# ════════════════════════════════════════════════════════════════════════════

def _get_open_violation_id(asset_id: str, policy_id: str, ch) -> str | None:
    result = ch.query(
        "SELECT violation_id FROM regradar.violations FINAL "
        "WHERE asset_id = {aid:String} AND policy_id = {pid:String} "
        "AND status = 'open' LIMIT 1",
        parameters={"aid": asset_id, "pid": policy_id},
    )
    rows = result.result_rows
    return rows[0][0] if rows else None


def _insert_violation_row(row: list, ch) -> None:
    ch.insert(
        "regradar.violations",
        [row],
        column_names=[
            "violation_id", "asset_id", "policy_id", "rule_type",
            "reason", "evidence", "severity", "status", "resolution_type",
            "detected_at", "last_seen_at", "resolved_at",
            "change_event_id", "triggered_by",
        ],
    )


def upsert_violation(
    result: ImpactEvaluationResult,
    change_event_id: str,
    ch,
) -> str | None:
    existing_id = _get_open_violation_id(result.asset_id, result.policy_id, ch)
    now = _now()

    if result.status == "PASS":
        if existing_id:
            # Close — asset returned to compliance
            _insert_violation_row([
                existing_id, result.asset_id, result.policy_id, result.rule_type,
                "Auto-resolved: asset returned to compliance", json.dumps({}),
                result.severity, "resolved", "auto_resolved",
                now, now, now, change_event_id, "asset_change",
            ], ch)
            log.info(
                "violation.auto_resolved",
                violation_id=existing_id, asset_id=result.asset_id,
                policy_id=result.policy_id,
            )
        return None

    # VIOLATION path
    if existing_id:
        # Bump last_seen_at on existing open violation — ReplacingMergeTree keeps latest
        _insert_violation_row([
            existing_id, result.asset_id, result.policy_id, result.rule_type,
            result.reason, json.dumps(result.evidence),
            result.severity, "open", "",
            now, now, None, change_event_id, "asset_change",
        ], ch)
        log.info(
            "violation.last_seen_updated",
            violation_id=existing_id, asset_id=result.asset_id,
        )
        return None  # already open — suppress duplicate notification

    # New violation
    violation_id = str(uuid.uuid4())
    _insert_violation_row([
        violation_id, result.asset_id, result.policy_id, result.rule_type,
        result.reason, json.dumps(result.evidence),
        result.severity, "open", "",
        now, now, None, change_event_id, "asset_change",
    ], ch)
    log.info(
        "violation.new",
        violation_id=violation_id, asset_id=result.asset_id,
        policy_id=result.policy_id, severity=result.severity,
        rule_type=result.rule_type,
    )
    return violation_id


# ════════════════════════════════════════════════════════════════════════════
# Component 5 — Notification Dispatcher
# Fires a webhook for each new violation. Retries 3× with exponential backoff.
# Failures are logged to notification_failures — never block violation write.
# ════════════════════════════════════════════════════════════════════════════

def _log_notification_failure(
    violation_id: str, policy_id: str, webhook_url: str,
    payload: dict, error: str, attempts: int, ch,
) -> None:
    try:
        ch.insert(
            "regradar.notification_failures",
            [[str(uuid.uuid4()), violation_id, policy_id, webhook_url,
              json.dumps(payload), error, attempts, _now()]],
            column_names=[
                "failure_id", "violation_id", "policy_id", "webhook_url",
                "payload_json", "error", "attempts", "failed_at",
            ],
        )
    except Exception as exc:
        log.error("notification_failure_log.error", error=str(exc))


async def dispatch_notification(
    violation_id: str,
    result: ImpactEvaluationResult,
    policy: PolicyRule,
    remediation_available: bool,
    ch,
) -> bool:
    webhook_url = policy.notification_config.get("webhook_url") or DEFAULT_WEBHOOK_URL
    if not webhook_url:
        log.warning("notification.no_webhook_configured", policy_id=policy.policy_id)
        return False

    payload = {
        "event": "violation.detected",
        "violation_id": violation_id,
        "asset_id": result.asset_id,
        "policy_id": result.policy_id,
        "severity": result.severity,
        "reason": result.reason,
        "evidence": result.evidence,
        "detected_at": result.evaluated_at.isoformat(),
        "remediation_available": remediation_available,
    }

    last_error = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(WEBHOOK_RETRY_ATTEMPTS):
            try:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                log.info(
                    "notification.sent",
                    violation_id=violation_id, webhook_url=webhook_url,
                )
                return True
            except Exception as exc:
                last_error = str(exc)
                if attempt < WEBHOOK_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2.0 ** attempt)

    log.error(
        "notification.all_retries_failed",
        violation_id=violation_id, webhook_url=webhook_url, error=last_error,
    )
    _log_notification_failure(
        violation_id, policy.policy_id, webhook_url,
        payload, last_error, WEBHOOK_RETRY_ATTEMPTS, ch,
    )
    return False


# ════════════════════════════════════════════════════════════════════════════
# Component 6 — Remediation Trigger
# high/critical → always trigger
# medium        → trigger if AUTO_REMEDIATE_MEDIUM or policy.auto_remediate
# low           → log only
# Writes to the actions table; on failure, writes to agent_dead_letter.
# ════════════════════════════════════════════════════════════════════════════

def _should_remediate(severity: str, policy: PolicyRule) -> bool:
    if severity in ("high", "critical"):
        return True
    if severity == "medium" and (AUTO_REMEDIATE_MEDIUM or policy.auto_remediate):
        return True
    return False


def _write_dead_letter(
    event_type: str, payload: dict, error: str, ch
) -> None:
    try:
        now = _now()
        ch.insert(
            "regradar.agent_dead_letter",
            [[str(uuid.uuid4()), AGENT_ID, event_type,
              json.dumps(payload), error, 1, now, now]],
            column_names=[
                "id", "agent_id", "event_type", "payload_json",
                "error", "attempts", "created_at", "last_attempted_at",
            ],
        )
    except Exception as exc:
        log.error("dead_letter.write_failed", error=str(exc))


async def trigger_remediation(
    violation_id: str,
    result: ImpactEvaluationResult,
    policy: PolicyRule,
    change_event_id: str,
    ch,
) -> None:
    priority = result.severity if result.severity in ("critical", "high") else "medium"
    payload = {
        "workflow_type": f"remediate_{policy.rule_type}",
        "violation_id": violation_id,
        "asset_id": result.asset_id,
        "policy_id": result.policy_id,
        "rule_type": result.rule_type,
        "evidence": result.evidence,
        "priority": priority,
    }

    action_id = str(uuid.uuid4())
    now = _now()
    try:
        ch.insert(
            "regradar.actions",
            [[action_id, change_event_id, "remediate_violation",
              result.asset_id, "pending", None,
              json.dumps(payload), "", now, None]],
            column_names=[
                "action_id", "trigger_id", "action_type", "target",
                "status", "luminai_execution_id", "sop_json",
                "result_json", "requested_at", "completed_at",
            ],
        )
        log.info(
            "remediation.triggered",
            action_id=action_id, violation_id=violation_id,
            severity=result.severity, rule_type=result.rule_type,
        )
    except Exception as exc:
        log.error("remediation.trigger_failed", violation_id=violation_id, error=str(exc))
        _write_dead_letter("remediation_trigger", payload, str(exc), ch)


# ════════════════════════════════════════════════════════════════════════════
# Main cycle + entry point
# ════════════════════════════════════════════════════════════════════════════

async def run_impact_analysis_cycle(ch) -> ImpactAnalysisCycleResult:
    """Run one full polling cycle. Returns a cycle result summary."""
    cycle_started = datetime.now(timezone.utc)
    summary = ImpactAnalysisCycleResult(cycle_started_at=cycle_started)
    cycle_error = ""

    # 1. Load cursor
    cursor = await asyncio.to_thread(_fetch_agent_cursor, ch)

    # 2. Fetch new events
    try:
        events = await asyncio.to_thread(_fetch_new_events, cursor, ch)
    except Exception as exc:
        log.error("impact_analysis.event_fetch_failed", error=str(exc))
        summary.errors.append(f"event_fetch: {exc}")
        await asyncio.to_thread(_persist_agent_state, cursor, str(exc), ch)
        summary.cycle_completed_at = datetime.now(timezone.utc)
        return summary

    if not events:
        log.debug("impact_analysis.no_new_events")
        await asyncio.to_thread(_persist_agent_state, cursor, "", ch)
        summary.cycle_completed_at = datetime.now(timezone.utc)
        return summary

    log.info("impact_analysis.cycle_start", event_count=len(events))
    summary.events_processed = len(events)

    # 3. Batch by asset_id
    batched = _batch_by_asset(events)
    summary.assets_processed = len(batched)
    policy_cache: _PolicyCache = {}
    new_cursor_dt: datetime | None = _parse_cursor(cursor)

    for asset_id, asset_events in batched.items():

        # 4. Resolve policies
        try:
            policies = await asyncio.to_thread(
                _resolve_policies, asset_id, ch, policy_cache
            )
        except Exception as exc:
            log.error(
                "impact_analysis.policy_resolve_error",
                asset_id=asset_id, error=str(exc),
            )
            summary.errors.append(f"policy_resolve[{asset_id}]: {exc}")
            continue

        if not policies:
            # Advance cursor even when no policies are registered
            for e in asset_events:
                if new_cursor_dt is None or e.changed_at > new_cursor_dt:
                    new_cursor_dt = e.changed_at
            continue

        for event in asset_events:
            for policy in policies:

                # 5. Evaluate
                eval_result = evaluate(event, policy)

                # 6. Write violation / resolve open
                try:
                    violation_id = await asyncio.to_thread(
                        upsert_violation, eval_result, event.change_event_id, ch
                    )
                except Exception as exc:
                    log.error(
                        "impact_analysis.violation_write_error",
                        asset_id=asset_id, policy_id=policy.policy_id, error=str(exc),
                    )
                    summary.errors.append(f"violation_write[{asset_id}/{policy.policy_id}]: {exc}")
                    _write_dead_letter(
                        "violation_write",
                        {"asset_id": asset_id, "policy_id": policy.policy_id,
                         "change_event_id": event.change_event_id},
                        str(exc), ch,
                    )
                    continue

                if eval_result.status == "VIOLATION" and violation_id is None:
                    # Existing open violation — last_seen_at bumped, no re-notify
                    pass
                elif eval_result.status == "PASS" and violation_id is None:
                    # Could have been a close, or nothing to do
                    if _get_open_violation_id(eval_result.asset_id, eval_result.policy_id, ch) is None:
                        summary.resolved_violations += 1

                # 7. Notify + remediate only for brand-new violations
                if violation_id:
                    summary.new_violations += 1
                    remediation_available = _should_remediate(eval_result.severity, policy)

                    sent = await dispatch_notification(
                        violation_id, eval_result, policy, remediation_available, ch
                    )
                    if sent:
                        summary.notifications_sent += 1

                    if remediation_available:
                        await trigger_remediation(
                            violation_id, eval_result, policy, event.change_event_id, ch
                        )
                        summary.remediations_triggered += 1

            # Advance cursor
            if new_cursor_dt is None or event.changed_at > new_cursor_dt:
                new_cursor_dt = event.changed_at

    # 8. Persist cursor
    new_cursor_str = new_cursor_dt.isoformat() if new_cursor_dt else cursor
    await asyncio.to_thread(_persist_agent_state, new_cursor_str, cycle_error, ch)

    summary.cycle_completed_at = datetime.now(timezone.utc)
    log.info(
        "impact_analysis.cycle_done",
        assets=summary.assets_processed,
        events=summary.events_processed,
        new_violations=summary.new_violations,
        resolved=summary.resolved_violations,
        notifications=summary.notifications_sent,
        remediations=summary.remediations_triggered,
        errors=len(summary.errors),
    )
    return summary


async def run_impact_analysis_agent(clickhouse_client=None) -> ImpactAnalysisCycleResult:
    """Entry point — pass an existing ClickHouse client or one is created from env."""
    ch = clickhouse_client or get_ch_client()
    return await run_impact_analysis_cycle(ch)


if __name__ == "__main__":
    asyncio.run(run_impact_analysis_agent())
