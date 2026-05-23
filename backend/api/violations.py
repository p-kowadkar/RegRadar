"""Read-only violations API backed by the live `regradar` ClickHouse database.

The agents own writes to compliance_violations, remediation_steps, policy_changes
and schema_events. The dashboard just reads and joins.

Endpoints:
    GET /api/violations                    list with computed steps
    GET /api/violations/{id}               single violation + remediation step plan
    GET /api/policy-changes                latest crawler-detected changes
    GET /api/schema-events                 schema enrichment trigger feed
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.integrations.clickhouse_client import get_sync_client as get_client

router = APIRouter(prefix="/api", tags=["violations"])


# ── Shapes ────────────────────────────────────────────────────


class RemediationStep(BaseModel):
    step_id: str
    step_number: int
    step_title: str
    step_description: str
    action_type: str
    automated: bool
    requires_approval: bool
    estimated_minutes: int


class Violation(BaseModel):
    violation_id: str
    regulation_id: str
    reg_code: Optional[str] = None
    control_name: Optional[str] = None
    asset_id: str
    asset_name: Optional[str] = None
    cde_id: str
    field_name: Optional[str] = None
    account_id: str
    violation_type: str
    trigger_type: str
    breach_detail: str
    days_in_breach: int
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    steps: list[RemediationStep] = []


class PolicyChange(BaseModel):
    change_id: str
    regulation_id: str
    reg_code: Optional[str] = None
    detected_at: datetime
    change_type: str
    prior_version: str
    new_version: str
    change_summary: str
    material: bool
    source_url: str


class SchemaEvent(BaseModel):
    event_id: str
    asset_id: str
    asset_name: Optional[str] = None
    event_type: str
    field_name: str
    detected_at: datetime
    rows_affected: int
    triggered_impact_analysis: bool


# ── Helpers ───────────────────────────────────────────────────


_VIOLATION_COLUMNS = (
    "v.violation_id, v.regulation_id, r.reg_code, r.control_name,"
    " v.asset_id, da.asset_name, v.cde_id, cde.field_name, v.account_id,"
    " v.violation_type, v.trigger_type, v.breach_detail, v.days_in_breach,"
    " v.severity, v.status, v.detected_at, v.resolved_at"
)

_VIOLATION_FROM = (
    " FROM compliance_violations AS v"
    " LEFT JOIN regulations AS r ON r.regulation_id = v.regulation_id"
    " LEFT JOIN data_assets AS da ON da.asset_id = v.asset_id"
    " LEFT JOIN critical_data_elements AS cde ON cde.cde_id = v.cde_id"
)


def _row_to_violation(r: tuple) -> Violation:
    return Violation(
        violation_id=r[0], regulation_id=r[1], reg_code=r[2], control_name=r[3],
        asset_id=r[4], asset_name=r[5], cde_id=r[6], field_name=r[7],
        account_id=r[8], violation_type=r[9], trigger_type=r[10],
        breach_detail=r[11], days_in_breach=int(r[12] or 0),
        severity=r[13], status=r[14], detected_at=r[15], resolved_at=r[16],
    )


def _steps_for(regulation_id: str, violation_type: str) -> list[RemediationStep]:
    rows = get_client().query(
        "SELECT step_id, step_number, step_title, step_description, action_type,"
        " automated, requires_approval, estimated_minutes"
        " FROM remediation_steps"
        " WHERE regulation_id = {rid:String} AND violation_type = {vt:String}"
        " ORDER BY step_number",
        parameters={"rid": regulation_id, "vt": violation_type},
    ).result_rows
    return [
        RemediationStep(
            step_id=r[0], step_number=int(r[1]), step_title=r[2],
            step_description=r[3], action_type=r[4], automated=bool(r[5]),
            requires_approval=bool(r[6]), estimated_minutes=int(r[7] or 0),
        )
        for r in rows
    ]


# ── Endpoints ─────────────────────────────────────────────────


@router.get("/violations", response_model=list[Violation])
def list_violations(limit: int = 50) -> list[Violation]:
    rows = get_client().query(
        f"SELECT {_VIOLATION_COLUMNS}{_VIOLATION_FROM}"
        " ORDER BY v.detected_at DESC LIMIT {lim:UInt32}",
        parameters={"lim": limit},
    ).result_rows
    out = []
    for r in rows:
        v = _row_to_violation(r)
        v.steps = _steps_for(v.regulation_id, v.violation_type)
        out.append(v)
    return out


@router.get("/violations/{violation_id}", response_model=Violation)
def get_violation(violation_id: str) -> Violation:
    rows = get_client().query(
        f"SELECT {_VIOLATION_COLUMNS}{_VIOLATION_FROM}"
        " WHERE v.violation_id = {vid:String} LIMIT 1",
        parameters={"vid": violation_id},
    ).result_rows
    if not rows:
        raise HTTPException(status_code=404, detail="violation not found")
    v = _row_to_violation(rows[0])
    v.steps = _steps_for(v.regulation_id, v.violation_type)
    return v


@router.get("/policy-changes", response_model=list[PolicyChange])
def list_policy_changes(limit: int = 25) -> list[PolicyChange]:
    rows = get_client().query(
        "SELECT pc.change_id, pc.regulation_id, r.reg_code, pc.detected_at,"
        " pc.change_type, pc.prior_version, pc.new_version, pc.change_summary,"
        " pc.material, pc.source_url"
        " FROM policy_changes AS pc"
        " LEFT JOIN regulations AS r ON r.regulation_id = pc.regulation_id"
        " ORDER BY pc.detected_at DESC LIMIT {lim:UInt32}",
        parameters={"lim": limit},
    ).result_rows
    return [
        PolicyChange(
            change_id=r[0], regulation_id=r[1], reg_code=r[2], detected_at=r[3],
            change_type=r[4], prior_version=r[5], new_version=r[6],
            change_summary=r[7], material=bool(r[8]), source_url=r[9],
        )
        for r in rows
    ]


@router.get("/schema-events", response_model=list[SchemaEvent])
def list_schema_events(limit: int = 25) -> list[SchemaEvent]:
    rows = get_client().query(
        "SELECT se.event_id, se.asset_id, da.asset_name, se.event_type,"
        " se.field_name, se.detected_at, se.rows_affected, se.triggered_impact_analysis"
        " FROM schema_events AS se"
        " LEFT JOIN data_assets AS da ON da.asset_id = se.asset_id"
        " ORDER BY se.detected_at DESC LIMIT {lim:UInt32}",
        parameters={"lim": limit},
    ).result_rows
    return [
        SchemaEvent(
            event_id=r[0], asset_id=r[1], asset_name=r[2], event_type=r[3],
            field_name=r[4], detected_at=r[5], rows_affected=int(r[6] or 0),
            triggered_impact_analysis=bool(r[7]),
        )
        for r in rows
    ]
