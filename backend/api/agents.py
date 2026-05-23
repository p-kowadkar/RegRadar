"""Read-only endpoints describing agent activity and asset coverage.

These power three dashboard panels:
  - Recent agent runs   ← agent_outputs (defensive: table may not exist yet)
  - Asset registry      ← data_assets
  - Coverage matrix     ← asset_regulation_map joined with regulations + data_assets
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.integrations.clickhouse_client import get_sync_client as get_client

router = APIRouter(prefix="/api", tags=["agents"])


# ── Shapes ────────────────────────────────────────────────────


class AgentRun(BaseModel):
    trigger_id: str
    agent_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int = 0
    response_type: Optional[str] = None
    auditor_verdict: Optional[str] = None
    error: Optional[str] = None


class AgentState(BaseModel):
    agent_id: str
    last_processed_at: Optional[datetime] = None
    last_cursor: str = ""
    cycle_count: int = 0
    last_error: str = ""
    status: str = "unknown"
    updated_at: Optional[datetime] = None


class CoverageRow(BaseModel):
    asset_id: str
    asset_name: str
    regulation_id: str
    reg_code: str
    in_scope: bool
    compliance_owner: str
    cde_count: int
    open_violations: int


# ── Helpers ───────────────────────────────────────────────────


def _table_exists(client, name: str) -> bool:
    rows = client.query(
        "SELECT count() FROM system.tables WHERE database = currentDatabase()"
        " AND name = {name:String}",
        parameters={"name": name},
    ).result_rows
    return bool(rows and int(rows[0][0]) > 0)


# ── Endpoints ─────────────────────────────────────────────────


@router.get("/agent-runs", response_model=list[AgentRun])
def list_agent_runs(limit: int = 25) -> list[AgentRun]:
    """Recent agent_outputs entries.

    Returns an empty list if the table doesn't exist yet (the team's schema
    is still landing in cloud), so the UI shows an empty panel rather than
    a 500.
    """
    client = get_client()
    if not _table_exists(client, "agent_outputs"):
        return []

    rows = client.query(
        "SELECT trigger_id, agent_id, started_at, completed_at, duration_ms,"
        " response_type, auditor_verdict, error"
        " FROM agent_outputs"
        " ORDER BY started_at DESC LIMIT {lim:UInt32}",
        parameters={"lim": limit},
    ).result_rows

    return [
        AgentRun(
            trigger_id=r[0], agent_id=r[1], started_at=r[2], completed_at=r[3],
            duration_ms=int(r[4] or 0), response_type=r[5] or None,
            auditor_verdict=r[6] or None, error=r[7] or None,
        )
        for r in rows
    ]


@router.get("/agent-state", response_model=list[AgentState])
def list_agent_state() -> list[AgentState]:
    """Live cursor state for each agent.

    Reads the agent_state table introduced for the Impact Analysis Agent.
    Returns an empty list if the table doesn't exist yet so the dashboard
    can render a placeholder until the schema lands in cloud.
    """
    client = get_client()
    if not _table_exists(client, "agent_state"):
        return []

    rows = client.query(
        "SELECT agent_id, last_processed_at, last_cursor, cycle_count,"
        " last_error, status, updated_at"
        " FROM agent_state FINAL ORDER BY agent_id"
    ).result_rows
    return [
        AgentState(
            agent_id=r[0],
            last_processed_at=r[1],
            last_cursor=r[2] or "",
            cycle_count=int(r[3] or 0),
            last_error=r[4] or "",
            status=r[5] or "unknown",
            updated_at=r[6],
        )
        for r in rows
    ]


@router.get("/coverage", response_model=list[CoverageRow])
def list_coverage() -> list[CoverageRow]:
    """Coverage matrix: every (asset, regulation) pair that's been mapped.

    Joins asset_regulation_map → data_assets → regulations and counts the
    CDEs and open violations per pair so the UI can flag gaps.
    """
    client = get_client()
    rows = client.query(
        """
        SELECT
            arm.asset_id,
            da.asset_name,
            arm.regulation_id,
            r.reg_code,
            arm.in_scope,
            arm.compliance_owner,
            length(splitByString(',', arm.cde_ids)) AS cde_count,
            (
                SELECT count()
                FROM compliance_violations AS cv
                WHERE cv.asset_id = arm.asset_id
                  AND cv.regulation_id = arm.regulation_id
                  AND cv.status IN ('OPEN', 'IN_REMEDIATION')
            ) AS open_violations
        FROM asset_regulation_map AS arm
        LEFT JOIN data_assets AS da ON da.asset_id = arm.asset_id
        LEFT JOIN regulations AS r ON r.regulation_id = arm.regulation_id
        ORDER BY arm.regulation_id, arm.asset_id
        """
    ).result_rows

    return [
        CoverageRow(
            asset_id=r[0],
            asset_name=r[1] or r[0],
            regulation_id=r[2],
            reg_code=r[3] or r[2],
            in_scope=bool(r[4]),
            compliance_owner=r[5] or "",
            cde_count=int(r[6] or 0),
            open_violations=int(r[7] or 0),
        )
        for r in rows
    ]
