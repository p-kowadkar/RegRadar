"""
Central Pydantic v2 models catalog.

Every agent I/O, every integration return, every API request/response uses
a model from this file. If you find yourself defining a Pydantic model
elsewhere, move it here -- having a single catalog prevents drift.

Organized by domain:
  1. Regulations & Scraping
  2. Knowledge Graph
  3. Portfolios
  4. Controls & Test Results
  5. Agent I/O
  6. Auditor / Grounding
  7. Luminai SOPs
  8. API Requests / Responses
  9. WebSocket Messages
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Useful type aliases
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
PositionStatus = Literal["BREACH", "AT_RISK", "MONITORING", "PASSING"]
ControlStatus = Literal["PASSING", "WARNING", "FAILING", "UNTESTED"]


# ════════════════════════════════════════════════════════════════
# 1. Regulations & Scraping
# ════════════════════════════════════════════════════════════════


class ScrapedDocument(BaseModel):
    """Returned by Nimble or Firecrawl."""

    source_url: str
    content: str
    content_hash: str
    scraped_at: datetime
    scraper_used: Literal["nimble", "firecrawl"]


class Regulation(BaseModel):
    """A regulation as stored in reg_versions."""

    reg_id: str
    version_id: str
    title: str
    regulator: str
    jurisdiction: str
    topics: list[str] = Field(default_factory=list)
    severity: Severity
    effective_date: date
    deadline_date: Optional[date] = None
    source_url: str
    content_markdown: str
    content_hash: str
    embedding: Optional[list[float]] = None         # 768-dim
    scraped_at: datetime


class RegulationEvent(BaseModel):
    """A trigger event for a new or amended regulation."""

    reg_id: str
    title: str
    content: str
    source_url: str
    regulator: str
    jurisdiction: str = "us_federal"
    topics: list[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════
# 2. Knowledge Graph
# ════════════════════════════════════════════════════════════════


class KGNode(BaseModel):
    node_id: str
    node_type: Literal[
        "regulation", "regulator", "jurisdiction", "data_object",
        "control", "portfolio_segment", "topic"
    ]
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None


class KGEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: Literal[
        "GOVERNS", "APPLIES_TO", "REQUIRES", "CONFLICTS_WITH",
        "DERIVED_FROM", "SUPERSEDES", "AMENDS", "TRIGGERS_CONTROL"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    created_by_agent: str


# ════════════════════════════════════════════════════════════════
# 3. Portfolios
# ════════════════════════════════════════════════════════════════


class DerivativePosition(BaseModel):
    position_id: str
    instrument_type: Literal["IRS", "CDS", "FRA", "FX_swap", "Equity_swap"]
    notional_usd: float
    counterparty: str
    counterparty_jurisdiction: str
    booking_jurisdiction: str
    trade_date: date
    maturity_date: date
    is_cleared: bool
    initial_margin_pct: float
    attributes: dict[str, Any] = Field(default_factory=dict)


class BondPosition(BaseModel):
    position_id: str
    bond_type: Literal["treasury", "corporate", "muni", "sovereign"]
    issuer: str
    cusip: str
    par_value_usd: float
    coupon_rate: float
    maturity_date: date
    credit_rating: str
    is_callable: bool
    attributes: dict[str, Any] = Field(default_factory=dict)


class LendingAccount(BaseModel):
    account_id: str
    product_type: Literal["bnpl", "personal_loan", "credit_card"]
    customer_id: str
    customer_jurisdiction: str
    principal_usd: float
    interest_rate: float
    origination_date: date
    term_months: int
    status: Literal["current", "delinquent_30", "delinquent_60", "charged_off"]
    customer_fico: int
    attributes: dict[str, Any] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# 4. Controls
# ════════════════════════════════════════════════════════════════


class Control(BaseModel):
    control_id: str
    name: str
    description: str
    related_regulation_id: str
    threshold_value: float
    threshold_unit: str
    threshold_comparison: Literal["lt", "lte", "eq", "gte", "gt"]
    owner_team: str
    test_frequency: str
    status: ControlStatus = "UNTESTED"
    last_tested_at: Optional[datetime] = None


class ControlTestResult(BaseModel):
    test_id: str
    control_id: str
    tested_at: datetime
    result: Literal["PASS", "WARN", "FAIL"]
    observed_value: float
    threshold_value: float
    breach_position_count: int = 0
    breach_notional_usd: float = 0.0
    notes: str = ""


class ControlUpdate(BaseModel):
    """The Advisor's request to update a control."""

    control_id: str
    new_threshold_value: Optional[float] = None
    new_threshold_unit: Optional[str] = None
    new_status: Optional[ControlStatus] = None
    rationale: str
    related_regulation_id: str


# ════════════════════════════════════════════════════════════════
# 5. Agent I/O
# ════════════════════════════════════════════════════════════════


class ClassifierOutput(BaseModel):
    """The Classifier's structured output."""

    reg_id: str
    jurisdiction: str
    regulator: str
    topics: list[str]
    severity: Severity
    deadline_date: Optional[date] = None
    threshold_changes: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class PortfolioMatch(BaseModel):
    """One match from the Mapper's portfolio scan."""

    portfolio: Literal["derivatives", "bonds", "lending"]
    position_id: str
    match_reason: str
    relevant_attributes: dict[str, Any]


class MapperOutput(BaseModel):
    """The Mapper's KG + portfolio scan output."""

    reg_id: str
    relevant_kg_nodes: list[str]                    # node_ids
    new_kg_edges: list[KGEdge]
    portfolio_matches: list[PortfolioMatch]
    affected_positions_count: int
    affected_notional_usd: float
    affected_jurisdictions: list[str]


class PositionClassification(BaseModel):
    """The Analyst's per-position classification breakdown."""

    BREACH: int
    AT_RISK: int
    MONITORING: int
    PASSING: int


class PositionDetail(BaseModel):
    position_id: str
    status: PositionStatus
    current_value: float
    required_value: float
    notional_usd: float
    days_to_deadline: Optional[int] = None
    suggested_action: str


class AnalystOutput(BaseModel):
    """The Analyst's impact analysis."""

    reg_id: str
    position_classification: PositionClassification
    position_details: list[PositionDetail]          # capped at top 50
    total_notional_at_risk_usd: float
    estimated_fine_range_usd: tuple[float, float]
    precedent_cases: list[dict[str, str]]           # historical similar actions
    days_to_compliance: int


class AdvisorAction(BaseModel):
    """One action proposed by The Advisor."""

    action_id: str
    action_type: Literal[
        "update_control", "file_sar", "send_notification",
        "update_policy_doc", "schedule_review", "amend_contract"
    ]
    target: str                                      # e.g. CTRL-001
    description: str
    workflow_execution: bool                         # if True, dispatch to Luminai
    sop_steps: list[str] = Field(default_factory=list)
    assignee_team: str
    deadline_date: Optional[date] = None
    priority: Literal["low", "medium", "high", "critical"]


class AdvisorOutput(BaseModel):
    """The Advisor's complete output."""

    reg_id: str
    control_updates: list[ControlUpdate]
    actions: list[AdvisorAction]
    rationale: str


# ════════════════════════════════════════════════════════════════
# 6. Auditor / Grounding
# ════════════════════════════════════════════════════════════════


class GroundingCitation(BaseModel):
    source_id: str                                   # reg_id or url
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_text: str


class GroundingResult(BaseModel):
    claim: str
    is_grounded: bool
    overall_confidence: float
    citations: list[GroundingCitation]


class AuditorVerdict(BaseModel):
    """The Auditor's final verdict on the chain."""

    trigger_id: str
    verdict: Literal["approved", "approved_with_warnings", "rejected"]
    agents_reviewed: list[str]
    grounding_results: dict[str, GroundingResult]    # keyed by agent_id
    warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    overall_confidence: float


# ════════════════════════════════════════════════════════════════
# 7. Luminai SOPs
# ════════════════════════════════════════════════════════════════


class LuminaiSOPStep(BaseModel):
    step_number: int
    action: str
    target: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class LuminaiSOP(BaseModel):
    name: str
    description: str
    steps: list[LuminaiSOPStep]
    context: dict[str, Any] = Field(default_factory=dict)


class LuminaiExecutionResult(BaseModel):
    execution_id: str
    status: Literal["running", "succeeded", "failed", "needs_human_review"]
    preview_url: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    error_message: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# 8. API Requests / Responses
# ════════════════════════════════════════════════════════════════


class TriggerRequest(BaseModel):
    """POST /api/internal/trigger body."""

    trigger_type: Literal[
        "user_message", "new_regulation", "reg_amended",
        "deadline_near", "coverage_gap"
    ]
    regulator: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    source_url: Optional[str] = None
    jurisdiction: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    effective_date_offset_days: Optional[int] = None
    user_message: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TriggerResponse(BaseModel):
    trigger_id: str
    state: Literal["received", "in_progress", "completed", "failed"]


class TriggerStatusResponse(BaseModel):
    trigger_id: str
    state: Literal["received", "in_progress", "completed", "failed"]
    agents_completed: list[str] = Field(default_factory=list)
    agents_pending: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None
    elapsed_ms: Optional[int] = None


class DashboardSummary(BaseModel):
    """GET /api/dashboard/summary"""

    controls: dict[str, int]                         # {total, passing, warning, failing}
    positions: dict[str, int]                        # {derivatives, bonds, lending}
    regulations_tracked: int
    recent_triggers: int                             # last 24h
    last_trigger_at: Optional[datetime] = None


# ════════════════════════════════════════════════════════════════
# 9. WebSocket Messages
# ════════════════════════════════════════════════════════════════


class WSMessage(BaseModel):
    """All WebSocket messages share this envelope."""

    type: Literal[
        "trigger_started",
        "agent_claim_posted",
        "agent_started",
        "agent_output",
        "auditor_verdict",
        "trigger_completed",
        "control_status_changed",
        "alert_sent",
        "heartbeat",
        "error",
    ]
    trigger_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    payload: dict[str, Any] = Field(default_factory=dict)


class WSAgentOutputMessage(WSMessage):
    """Specialization for when type='agent_output'."""

    model_config = ConfigDict(extra="allow")


# ════════════════════════════════════════════════════════════════
# 10. Impact Analysis Agent
# ════════════════════════════════════════════════════════════════

ImpactSeverity = Literal["low", "medium", "high", "critical"]
ImpactRuleType = Literal[
    "schema_constraint",
    "classification_required",
    "access_control",
    "retention_policy",
    "freshness_sla",
    "lineage_restriction",
]
AssetChangeType = Literal[
    "schema_change",
    "classification_change",
    "access_control_change",
    "location_change",
    "freshness_drift",
    "lineage_change",
]


class AssetChangeEvent(BaseModel):
    """One row from asset_changes — the trigger for impact analysis."""

    change_event_id: str
    asset_id: str
    change_type: AssetChangeType
    changed_at: datetime
    changed_by: str
    previous_state_hash: str
    new_state_hash: str
    change_details: dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    """One active rule from policy_registry."""

    policy_id: str
    version: int
    rule_type: ImpactRuleType
    rule_params: dict[str, Any] = Field(default_factory=dict)
    severity: ImpactSeverity
    active: bool
    notification_config: dict[str, Any] = Field(default_factory=dict)
    auto_remediate: bool = False


class ImpactEvaluationResult(BaseModel):
    """Output of the Compliance Evaluator for one (asset_change, policy_rule) pair."""

    status: Literal["PASS", "VIOLATION"]
    policy_id: str
    asset_id: str
    rule_type: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    severity: ImpactSeverity
    evaluated_at: datetime = Field(default_factory=datetime.now)


class ViolationRecord(BaseModel):
    """One row in the violations table."""

    violation_id: str
    asset_id: str
    policy_id: str
    rule_type: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    severity: ImpactSeverity
    status: Literal["open", "resolved", "suppressed"]
    resolution_type: str = ""
    detected_at: datetime
    last_seen_at: datetime
    resolved_at: Optional[datetime] = None
    change_event_id: str
    triggered_by: str = "asset_change"


class ImpactAnalysisCycleResult(BaseModel):
    """Summary returned after each polling cycle."""

    assets_processed: int = 0
    events_processed: int = 0
    new_violations: int = 0
    resolved_violations: int = 0
    notifications_sent: int = 0
    remediations_triggered: int = 0
    cycle_started_at: datetime
    cycle_completed_at: Optional[datetime] = None
    errors: list[str] = Field(default_factory=list)
