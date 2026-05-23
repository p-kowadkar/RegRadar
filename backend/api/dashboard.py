"""Dashboard read API backed by the live `regradar` ClickHouse database.

Surfaces:
- KPIs: assets monitored, accounted for, out of compliance, suggested fixes,
  fixes completed.
- By-regulation breakdown for the chart.
- Regulations + data assets list for context panels.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.integrations.clickhouse_client import get_sync_client as get_client
from .datadog_metrics import emit_dashboard_gauges

router = APIRouter(prefix="/api", tags=["dashboard"])


# ── Pydantic shapes ────────────────────────────────────────────


class RegulationBucket(BaseModel):
    regulation_id: str
    reg_code: str
    compliant: int
    at_risk: int
    out_of_compliance: int


class DashboardSummary(BaseModel):
    monitored: int                    # data_assets count
    accountedFor: int                 # data_assets in scope (asset_regulation_map.in_scope=true)
    outOfCompliance: int              # OPEN violations
    fixesSuggested: int               # remediation steps for OPEN/IN_REMEDIATION violations
    fixesCompleted: int               # RESOLVED violations
    byPolicy: list[RegulationBucket]


class Regulation(BaseModel):
    regulation_id: str
    regulation_name: str
    act: str
    reg_code: str
    control_name: str
    trigger_type: str
    threshold_days: Optional[int] = None
    threshold_label: str
    effective_date: Optional[datetime] = None
    last_crawled_at: Optional[datetime] = None


class DataAsset(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    system: str
    table_name: str
    owner_team: str
    data_classification: str
    row_count_est: int
    refresh_cadence: str


# ── Endpoints ──────────────────────────────────────────────────


@router.get("/health")
def health() -> dict:
    try:
        get_client().command("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"clickhouse: {e}") from e


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary() -> DashboardSummary:
    client = get_client()

    # Asset counts
    monitored = int(client.query("SELECT count() FROM data_assets").result_rows[0][0])
    accounted_for = int(
        client.query(
            "SELECT count(DISTINCT asset_id) FROM asset_regulation_map "
            "WHERE in_scope = true"
        ).result_rows[0][0]
    )

    # Violation counts
    rows = client.query(
        "SELECT status, count() FROM compliance_violations GROUP BY status"
    ).result_rows
    by_status = {r[0]: int(r[1]) for r in rows}
    out_of_compliance = by_status.get("OPEN", 0) + by_status.get("IN_REMEDIATION", 0)
    fixes_completed = by_status.get("RESOLVED", 0)

    # Suggested-fix count: distinct remediation steps tied to live violations
    fixes_suggested = int(
        client.query(
            """
            SELECT count(DISTINCT (cv.violation_id, rs.step_id))
            FROM compliance_violations AS cv
            INNER JOIN remediation_steps AS rs
              ON rs.regulation_id = cv.regulation_id
             AND rs.violation_type = cv.violation_type
            WHERE cv.status IN ('OPEN', 'IN_REMEDIATION')
            """
        ).result_rows[0][0]
    )

    # Per-regulation rollup: compliant assets vs. out-of-compliance ones
    bucket_rows = client.query(
        """
        SELECT r.regulation_id,
               r.reg_code,
               countDistinctIf(arm.asset_id, arm.in_scope = true)                          AS in_scope_assets,
               countDistinctIf(cv.asset_id, cv.status IN ('OPEN','IN_REMEDIATION'))        AS breached_assets,
               countDistinctIf(cv.asset_id, cv.severity IN ('MEDIUM','HIGH','CRITICAL') AND cv.status = 'OPEN') AS at_risk_assets
        FROM regulations AS r
        LEFT JOIN asset_regulation_map AS arm ON arm.regulation_id = r.regulation_id
        LEFT JOIN compliance_violations AS cv ON cv.regulation_id = r.regulation_id
        GROUP BY r.regulation_id, r.reg_code
        ORDER BY r.regulation_id
        """
    ).result_rows

    by_policy: list[RegulationBucket] = []
    for reg_id, reg_code, in_scope, breached, at_risk in bucket_rows:
        in_scope = int(in_scope or 0)
        breached = int(breached or 0)
        at_risk = int(at_risk or 0)
        compliant = max(in_scope - breached, 0)
        by_policy.append(
            RegulationBucket(
                regulation_id=reg_id,
                reg_code=reg_code,
                compliant=compliant,
                at_risk=at_risk,
                out_of_compliance=breached,
            )
        )

    summary = DashboardSummary(
        monitored=monitored,
        accountedFor=accounted_for,
        outOfCompliance=out_of_compliance,
        fixesSuggested=fixes_suggested,
        fixesCompleted=fixes_completed,
        byPolicy=by_policy,
    )

    emit_dashboard_gauges(
        monitored=monitored,
        accounted_for=accounted_for,
        out_of_compliance=out_of_compliance,
        fixes_suggested=fixes_suggested,
        fixes_completed=fixes_completed,
    )
    return summary


@router.get("/regulations", response_model=list[Regulation])
def list_regulations() -> list[Regulation]:
    rows = get_client().query(
        "SELECT regulation_id, regulation_name, act, reg_code, control_name,"
        " trigger_type, threshold_days, threshold_label, effective_date, last_crawled_at"
        " FROM regulations ORDER BY regulation_id"
    ).result_rows
    return [
        Regulation(
            regulation_id=r[0], regulation_name=r[1], act=r[2], reg_code=r[3],
            control_name=r[4], trigger_type=r[5], threshold_days=r[6],
            threshold_label=r[7], effective_date=r[8], last_crawled_at=r[9],
        )
        for r in rows
    ]


@router.get("/data-assets", response_model=list[DataAsset])
def list_data_assets() -> list[DataAsset]:
    rows = get_client().query(
        "SELECT asset_id, asset_name, asset_type, system, table_name, owner_team,"
        " data_classification, row_count_est, refresh_cadence"
        " FROM data_assets ORDER BY asset_id"
    ).result_rows
    return [
        DataAsset(
            asset_id=r[0], asset_name=r[1], asset_type=r[2], system=r[3],
            table_name=r[4], owner_team=r[5], data_classification=r[6],
            row_count_est=int(r[7] or 0), refresh_cadence=r[8],
        )
        for r in rows
    ]
