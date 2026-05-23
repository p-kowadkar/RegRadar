# AGENTS.md

Complete specifications for all 6 agents.

Every agent must conform to `BaseAgent` (see Section 1). The 5 LLM-based agents each have their own Section (3-7) with input/output Pydantic models, eval logic, system prompt reference, and error handling.

---

## 1. The Base Agent Pattern

All agents inherit from `BaseAgent` in `backend/agents/base.py`.

### The Abstract Base Class

```python
# backend/agents/base.py
from abc import ABC, abstractmethod
from typing import Optional
import structlog
from pydantic import BaseModel
from backend.orchestrator.blackboard import Blackboard, AgentClaim

log = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base for all agents."""

    agent_id: str                           # set in subclass class var
    display_name: str                       # set in subclass
    model: str                              # e.g. "gemini-3.5-flash"
    primary_threshold: float = 0.85
    supporting_threshold: float = 0.65
    cross_talk_threshold: float = 0.50
    primary_dependencies: list[str] = []    # other agent_ids
    supporting_dependencies: list[str] = []

    def hard_filter(self, blackboard: Blackboard) -> bool:
        """
        Phase 1: Rule-based filter. Return True to STAY SILENT.
        No LLM call. Override in subclass.
        Default: never filter.
        """
        return False

    @abstractmethod
    async def score_relevance(self, blackboard: Blackboard) -> float:
        """
        Phase 2: Soft scoring via cheap LLM call.
        Return float 0.0 - 1.0.
        """
        ...

    def classify_claim_type(
        self, score: float, blackboard: Blackboard
    ) -> Optional[AgentClaim]:
        """
        Phase 3: Deterministic claim classification.
        Returns None if agent stays silent.
        """
        if score < self.cross_talk_threshold:
            return None
        if score >= self.primary_threshold:
            response_type = "primary"
            deps = self.primary_dependencies
        elif score >= self.supporting_threshold:
            response_type = "supporting"
            deps = self.supporting_dependencies
        else:
            response_type = "cross_talk"
            deps = []

        return AgentClaim(
            agent_id=self.agent_id,
            relevance_score=score,
            response_type=response_type,
            depends_on=deps,
            reasoning=f"score={score:.2f}",
        )

    async def evaluate_relevance(
        self, blackboard: Blackboard
    ) -> Optional[AgentClaim]:
        """
        Full 3-phase eval. Called by orchestrator in parallel for all agents.
        """
        log_ctx = log.bind(
            agent_id=self.agent_id,
            task_id=blackboard.task_id,
        )
        # Phase 1
        if self.hard_filter(blackboard):
            log_ctx.debug("agent_silent_hard_filter")
            return None
        # Phase 2
        try:
            score = await self.score_relevance(blackboard)
        except Exception as e:
            log_ctx.warning("agent_score_failed", error=str(e))
            return None
        # Phase 3
        claim = self.classify_claim_type(score, blackboard)
        if claim:
            log_ctx.info("agent_claims_turn",
                         score=score,
                         response_type=claim.response_type)
        else:
            log_ctx.debug("agent_silent_low_score", score=score)
        return claim

    @abstractmethod
    async def execute(self, blackboard: Blackboard) -> BaseModel:
        """
        Actually generate output. Called by orchestrator AFTER resolution,
        only for agents whose claims survived. Returns the agent's output
        as a Pydantic model.
        """
        ...

    def load_prompt(self) -> str:
        """Load system prompt from backend/agents/prompts/<agent_id>.txt"""
        from pathlib import Path
        prompt_path = Path(__file__).parent / "prompts" / f"{self.agent_id}.txt"
        return prompt_path.read_text()
```

### Agent Lifecycle

```
Orchestrator picks up task
        │
        ▼
For each registered agent (PARALLEL):
    └─ agent.evaluate_relevance(blackboard) → AgentClaim | None
        ├─ Phase 1: hard_filter (sync, no LLM)
        ├─ Phase 2: score_relevance (small LLM call)
        └─ Phase 3: classify_claim_type (sync)
        │
        ▼
Orchestrator resolves claims → ordered list
        │
        ▼
For each claim in order (SEQUENTIAL):
    └─ agent.execute(blackboard) → Pydantic output
        ├─ Loads system prompt
        ├─ Builds context from blackboard
        ├─ Calls Vertex AI Gemini
        ├─ Parses to Pydantic model
        └─ Returns
        │
        ▼
Auditor runs LAST
        │
        ▼
Stream to WebSocket
```

---

## 2. The Watcher

### Identity

```python
agent_id = "the_watcher"
display_name = "The Watcher"
model = None  # Pure Python, no LLM
```

### Role

Monitors regulatory sources and detects changes. Does NOT participate in the standard 3-phase eval -- runs on its own scheduler (Heartbeat).

### Special: This agent does NOT inherit from BaseAgent

Instead, it's a separate `WatcherService` registered with the Heartbeat:

```python
# backend/agents/watcher.py

class WatcherService:
    """Polls regulatory sources, detects changes, posts to Blackboard."""

    SOURCES = [
        {"name": "sec_edgar", "type": "api", "interval_min": 15,
         "url": "https://data.sec.gov/...", "parser": parse_edgar},
        {"name": "federal_register", "type": "api", "interval_min": 15,
         "url": "https://www.federalregister.gov/api/v1/...",
         "parser": parse_fedreg},
        {"name": "regulations_gov", "type": "api", "interval_min": 15,
         "url": "https://api.regulations.gov/v4/...",
         "parser": parse_regsgov},
        {"name": "finra_notices", "type": "scrape", "interval_min": 60,
         "url": "https://www.finra.org/rules-guidance/notices",
         "scraper": "nimble"},
        {"name": "occ_bulletins", "type": "scrape", "interval_min": 60,
         "url": "https://www.occ.gov/news-issuances/bulletins/index-bulletins.html",
         "scraper": "nimble"},
        # ... 9 more
    ]

    async def poll_source(self, source: dict) -> list[Document]:
        """Fetch + parse one source."""

    async def detect_changes(self, docs: list[Document]) -> list[Document]:
        """Hash docs, compare against reg_versions table, return new/changed."""

    async def post_to_blackboard(self, doc: Document):
        """Create new blackboard with trigger_type='new_regulation' or 'reg_amended'."""
```

### Change Detection Algorithm

```python
# backend/utils/hashing.py

import hashlib

def normalize_text(text: str) -> str:
    """Strip whitespace variation, lowercase, remove HTML tags."""
    ...

def hash_document(text: str) -> str:
    """SHA256 of normalized text."""
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


# In WatcherService
async def detect_changes(self, docs: list[Document]) -> list[Document]:
    changes = []
    for doc in docs:
        new_hash = hash_document(doc.text)
        existing = await self.reg_repo.get_latest_version(doc.source_url)
        if existing is None:
            doc.change_type = "new_regulation"
            changes.append(doc)
            await self.reg_repo.insert_version(doc, new_hash)
        elif existing.text_hash != new_hash:
            doc.change_type = "reg_amended"
            doc.diff = self.compute_diff(existing.text, doc.text)
            changes.append(doc)
            await self.reg_repo.insert_version(doc, new_hash)
    return changes
```

### Error Handling

- If a source returns 5xx → log warning, retry in next interval
- If Nimble rate-limited → fall back to Firecrawl for that source
- If parser raises → log error with raw response, skip source for this cycle
- Coverage gap: if any source hasn't returned data in 24h → trigger `coverage_gap` blackboard event

---

## 3. The Classifier

### Identity

```python
agent_id = "the_classifier"
display_name = "The Classifier"
model = "gemini-3.5-flash"
primary_threshold = 0.85
supporting_threshold = 0.65
cross_talk_threshold = 0.50
primary_dependencies = []  # Classifier never depends on anything
```

### Input Pydantic Model

```python
# Reads from blackboard.trigger_payload (a Document object)

class Document(BaseModel):
    source_url: str
    source_name: str          # e.g. "sec_edgar", "finra_notices"
    fetched_at: datetime
    title: str
    text: str                  # full plain text
    metadata: dict[str, Any]   # source-specific
    change_type: Literal["new_regulation", "reg_amended"]
    diff: Optional[str] = None
```

### Output Pydantic Model

```python
# backend/data/schema.py

class ThresholdChange(BaseModel):
    metric: str                # e.g. "initial_margin"
    old_value: float | None
    new_value: float
    unit: str                  # "percent_notional", "days", "usd"

class ClassifierOutput(BaseModel):
    jurisdiction: list[str]    # ["us_federal", "us_state_ny", ...]
    regulator: list[str]       # ["SEC", "CFTC", ...]
    topic: list[str]           # controlled list
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    document_type: str
    deadlines: dict[str, Optional[str]]  # {"effective_date": "2026-07-21", ...}
    title: str
    summary: str               # 2-3 sentences
    threshold_changes: list[ThresholdChange] = []
    confidence: float          # 0.0 - 1.0

    class Config:
        json_schema_extra = {
            "example": {
                "jurisdiction": ["us_federal"],
                "regulator": ["CFTC"],
                "topic": ["margin_collateral", "swap_reporting"],
                "severity": "HIGH",
                "document_type": "final_rule",
                "deadlines": {
                    "effective_date": "2026-07-21",
                    "comment_close": None,
                    "compliance_deadline": "2026-07-21"
                },
                "title": "Amendments to Margin Requirements for Uncleared Swaps",
                "summary": "CFTC raises initial margin requirement from 6% to 8% on uncleared interest rate swaps. Effective in 60 days.",
                "threshold_changes": [
                    {"metric": "initial_margin",
                     "old_value": 0.06,
                     "new_value": 0.08,
                     "unit": "percent_notional"}
                ],
                "confidence": 0.95
            }
        }
```

### Hard Filter Logic

```python
def hard_filter(self, blackboard: Blackboard) -> bool:
    """Classifier ONLY fires for trigger types involving regulatory text."""
    return blackboard.trigger_type not in [
        "new_regulation", "reg_amended", "user_message"
    ]
```

### Score Relevance Logic

```python
async def score_relevance(self, blackboard: Blackboard) -> float:
    """For reg events, always 1.0 (Classifier is mandatory first step).
    For user messages, score based on whether intent involves a regulation."""
    if blackboard.trigger_type in ["new_regulation", "reg_amended"]:
        return 1.0
    
    # For user_message, check intent
    user_msg = blackboard.trigger_payload.get("message", "")
    prompt = f"""Rate 0.0-1.0: does this question relate to a specific regulation
that needs classification?

User message: {user_msg}

Return ONLY a float, no explanation."""
    
    response = await vertex_ai.generate(
        model="gemini-3.5-flash",
        prompt=prompt,
        max_tokens=8,
        temperature=None,  # Gemini 3.x: don't set temperature
    )
    return parse_float_safe(response.text, default=0.0)
```

### Execute Logic

```python
async def execute(self, blackboard: Blackboard) -> ClassifierOutput:
    log_ctx = log.bind(agent_id=self.agent_id, task_id=blackboard.task_id)
    
    document = Document(**blackboard.trigger_payload)
    system_prompt = self.load_prompt()
    
    user_content = f"""Classify this regulatory document:

TITLE: {document.title}
SOURCE: {document.source_name}
CHANGE TYPE: {document.change_type}

TEXT:
{document.text[:8000]}

{"DIFF (vs previous version):" if document.diff else ""}
{document.diff or ""}
"""

    log_ctx.info("classifier_executing", doc_title=document.title)
    
    response = await vertex_ai.generate_structured(
        model=self.model,
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=ClassifierOutput,
        max_tokens=2000,
    )
    
    log_ctx.info("classifier_complete",
                 severity=response.severity,
                 jurisdictions=response.jurisdiction,
                 confidence=response.confidence)
    
    return response
```

### System Prompt Reference

See `backend/agents/prompts/classifier.txt`. Full text in [SEED_DATA.md Section 5](SEED_DATA.md#5-agent-system-prompts) or copy from Master Plan PDF Part VII.

### Error Handling

| Error | Action |
|---|---|
| LLM returns invalid JSON | Retry with stricter "JSON only" instruction (max 2 retries) |
| LLM returns confidence < 0.4 | Lower severity to LOW, add uncertainty note to summary |
| LLM call times out (> 10s) | Raise `AgentTimeoutError`, orchestrator handles |
| Document text > 8000 chars | Truncate to 8000, log warning |

---

## 4. The Mapper

### Identity

```python
agent_id = "the_mapper"
display_name = "The Mapper"
model = "gemini-3.1-pro"  # Needs reasoning depth
primary_threshold = 0.85
supporting_threshold = 0.65
cross_talk_threshold = 0.55
primary_dependencies = ["the_classifier"]
supporting_dependencies = ["the_classifier"]
```

### Output Pydantic Model

```python
class AffectedDataObject(BaseModel):
    data_object_id: str
    impact_type: Literal["direct", "indirect"]
    regulation_section: str
    obligation: str
    confidence: float
    reasoning: str

class PortfolioScanResult(BaseModel):
    table: str                       # "derivatives_portfolio", etc.
    filter_sql: str                  # the WHERE clause used
    affected_positions: int
    total_notional_usd: Optional[float] = None
    total_outstanding_usd: Optional[float] = None
    sample_positions: list[dict[str, Any]] = []  # up to 10 examples

class ProposedEdge(BaseModel):
    source_id: str
    target_id: str
    edge_type: str
    confidence: float

class MapperOutput(BaseModel):
    affected_data_objects: list[AffectedDataObject]
    portfolio_scan: Optional[PortfolioScanResult] = None
    affected_products: list[str] = []
    affected_jurisdictions: list[str] = []
    new_edges_proposed: list[ProposedEdge] = []
    graph_query_used: str           # SQL actually run
    uncertainty_notes: str = ""
```

### Hard Filter Logic

```python
def hard_filter(self, blackboard: Blackboard) -> bool:
    """Mapper requires Classifier output and high enough confidence."""
    if blackboard.classifier_output is None:
        return True
    if blackboard.classifier_output.confidence < 0.5:
        return True
    if blackboard.classifier_output.severity == "LOW":
        return True   # Don't bother mapping low-severity stuff
    return False
```

### Score Relevance Logic

```python
async def score_relevance(self, blackboard: Blackboard) -> float:
    """High score if classification touches portfolio-relevant topics."""
    cls = blackboard.classifier_output
    
    # Topics that ALWAYS need portfolio mapping
    portfolio_topics = {
        "margin_collateral", "swap_reporting", "recordkeeping",
        "cross_border_payments", "lending_credit", "sanctions_screening",
        "capital_reserves", "reporting_disclosure"
    }
    
    overlap = set(cls.topic) & portfolio_topics
    if overlap:
        return 0.95
    if cls.severity in ["CRITICAL", "HIGH"]:
        return 0.80
    return 0.60
```

### Execute Logic

```python
async def execute(self, blackboard: Blackboard) -> MapperOutput:
    log_ctx = log.bind(agent_id=self.agent_id, task_id=blackboard.task_id)
    cls = blackboard.classifier_output
    
    # 1. Graph traversal (deterministic, no LLM)
    candidate_objects = await self.kg_repo.find_candidates(
        topics=cls.topic,
        jurisdictions=cls.jurisdiction,
        regulators=cls.regulator,
    )
    
    # 2. LLM reasoning to filter + propose edges
    system_prompt = self.load_prompt()
    user_content = self._build_mapper_context(
        cls, candidate_objects, blackboard.company_profile
    )
    
    output = await vertex_ai.generate_structured(
        model=self.model,
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=MapperOutput,
        max_tokens=4000,
    )
    
    # 3. If affected_data_objects includes a portfolio, run the scan
    portfolio_table = self._infer_portfolio_table(output.affected_data_objects)
    if portfolio_table and cls.threshold_changes:
        scan = await self.portfolio_repo.scan_against_threshold(
            table=portfolio_table,
            threshold_changes=cls.threshold_changes,
        )
        output.portfolio_scan = scan
    
    log_ctx.info("mapper_complete",
                 affected_count=len(output.affected_data_objects),
                 portfolio_positions=output.portfolio_scan.affected_positions if output.portfolio_scan else None)
    
    return output
```

### The `_build_mapper_context` Function

This is the most context-heavy prompt builder. Include:
- Classifier output (full)
- Company profile data_objects list
- Candidate matches from graph (top 20)
- Available portfolio tables and their schemas
- Existing edges to consider when proposing new ones

### Error Handling

| Error | Action |
|---|---|
| `affected_data_objects` empty but severity HIGH | Auditor will flag -- pass through |
| Portfolio scan times out | Set `portfolio_scan=None`, log warning |
| Proposed edges duplicate existing | Filter out before persisting (graph layer's job) |
| LLM cites a non-existent data_object | Auditor catches this |

---

## 5. The Analyst

### Identity

```python
agent_id = "the_analyst"
display_name = "The Analyst"
model = "gemini-3.1-pro"
primary_threshold = 0.85
supporting_threshold = 0.65
cross_talk_threshold = 0.55
primary_dependencies = ["the_classifier", "the_mapper"]
supporting_dependencies = ["the_classifier", "the_mapper"]
```

### Output Pydantic Model

```python
class PositionClassification(BaseModel):
    BREACH: int
    AT_RISK: int
    MONITORING: int

class PrecedentCase(BaseModel):
    name: str                    # e.g. "CFTC v. JPMorgan (2020)"
    fine_usd: int
    year: int
    relevance: str

class RiskExposure(BaseModel):
    estimated_fine_range_usd: tuple[int, int]
    precedent_cases: list[PrecedentCase]
    reputational_risk: Literal["high", "medium", "low"]
    operational_disruption_risk: Literal["high", "medium", "low"]

class GapAnalysis(BaseModel):
    current_state: str
    required_state: str
    gap_severity: Literal["high", "medium", "low"]

class OperationalImpact(BaseModel):
    affected_teams: list[str]
    affected_systems: list[str]
    effort_estimate: Literal["small", "medium", "large"]
    effort_reasoning: str

class TimelineAssessment(BaseModel):
    days_until_deadline: int | None
    recommended_start_date: str | None  # ISO 8601
    critical_path_items: list[str]

class AnalystOutput(BaseModel):
    position_classification: Optional[PositionClassification] = None
    gap_analysis: GapAnalysis
    risk_exposure: RiskExposure
    operational_impact: OperationalImpact
    timeline: TimelineAssessment
    confidence: float
    confidence_reasoning: str
```

### Hard Filter Logic

```python
def hard_filter(self, blackboard: Blackboard) -> bool:
    """Analyst requires Mapper output."""
    if blackboard.mapper_output is None:
        return True
    if not blackboard.mapper_output.affected_data_objects:
        return True   # Nothing to analyze
    return False
```

### Execute Logic

```python
async def execute(self, blackboard: Blackboard) -> AnalystOutput:
    log_ctx = log.bind(agent_id=self.agent_id, task_id=blackboard.task_id)
    
    cls = blackboard.classifier_output
    mapper = blackboard.mapper_output
    
    # If there's a portfolio scan, classify each position via SQL
    position_class = None
    if mapper.portfolio_scan and cls.threshold_changes:
        position_class = await self.portfolio_repo.classify_positions(
            table=mapper.portfolio_scan.table,
            threshold_changes=cls.threshold_changes,
        )
    
    # Then LLM for qualitative impact + precedent recall
    system_prompt = self.load_prompt()
    user_content = self._build_analyst_context(
        cls, mapper, position_class, blackboard.company_profile
    )
    
    output = await vertex_ai.generate_structured(
        model=self.model,
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=AnalystOutput,
        max_tokens=4000,
    )
    
    # Attach the deterministic position classification (don't trust LLM here)
    if position_class:
        output.position_classification = position_class
    
    log_ctx.info("analyst_complete",
                 breach_count=position_class.BREACH if position_class else None,
                 gap_severity=output.gap_analysis.gap_severity,
                 confidence=output.confidence)
    
    return output
```

### Position Classification SQL Template

```python
# backend/data/portfolio_repo.py

async def classify_positions(
    self, table: str, threshold_changes: list[ThresholdChange]
) -> PositionClassification:
    """Classify each position as BREACH / AT_RISK / MONITORING."""
    
    # Build threshold expression
    if table == "derivatives_portfolio":
        thresh_change = next(
            (t for t in threshold_changes if t.metric == "initial_margin"),
            None,
        )
        if thresh_change is None:
            return PositionClassification(BREACH=0, AT_RISK=0, MONITORING=0)
        
        new_thresh = thresh_change.new_value
        at_risk_floor = new_thresh * 0.80  # within 20% margin
        
        query = f"""
        SELECT
            countIf(margin_ratio < {new_thresh}) AS breach,
            countIf(margin_ratio >= {new_thresh} AND margin_ratio < {at_risk_floor + new_thresh}) AS at_risk,
            countIf(margin_ratio >= {at_risk_floor + new_thresh}) AS monitoring
        FROM derivatives_portfolio
        WHERE instrument_type='IR_SWAP' AND cleared=false
        """
        result = await self.client.query(query)
        row = result.result_rows[0]
        return PositionClassification(BREACH=row[0], AT_RISK=row[1], MONITORING=row[2])
    
    # Similar branches for bonds_portfolio, lending_portfolio
    ...
```

### Error Handling

| Error | Action |
|---|---|
| LLM invents a precedent case | Auditor catches; on rejection, retry with stricter prompt |
| Position classification query fails | Set `position_classification=None`, lower confidence |
| `confidence < 0.5` | Auditor flags as "low confidence" warning |
| Estimated fine range absurd (e.g. > $1B for minor violation) | Auditor flags |

---

## 6. The Advisor

### Identity

```python
agent_id = "the_advisor"
display_name = "The Advisor"
model = "gemini-3.5-flash"  # Action generation, simpler than reasoning
primary_threshold = 0.80
supporting_threshold = 0.60
cross_talk_threshold = 0.45
primary_dependencies = ["the_analyst"]
supporting_dependencies = ["the_analyst"]
```

### Output Pydantic Model

```python
class ControlUpdate(BaseModel):
    control_id: str                 # "CTRL-001"
    field: Literal["threshold", "frequency", "owner", "description", "status"]
    old_value: Any
    new_value: Any
    new_status_after_retest: Optional[
        Literal["PASSING", "AT_RISK", "FAILING", "NOT_APPLICABLE"]
    ] = None

class ActionPlanItem(BaseModel):
    id: str                          # "action_1"
    title: str
    description: str
    owner: str                       # "compliance_team", "legal_team", etc.
    deadline: Optional[str] = None   # ISO 8601
    priority: int                    # 1 = highest
    estimated_effort_hours: int
    workflow_execution: bool
    luminai_sop: Optional[list[str]] = None
    reason_not_automatable: Optional[str] = None
    human_step_description: Optional[str] = None

class DatadogAlert(BaseModel):
    severity: Literal["info", "warning", "error", "critical"]
    control_id: Optional[str] = None
    title: str
    message: str
    owner_team: str

class AdvisorOutput(BaseModel):
    control_updates: list[ControlUpdate] = []
    action_plan: list[ActionPlanItem]
    datadog_alert: Optional[DatadogAlert] = None
    summary_for_user: str            # 2-3 friendly sentences
```

### Hard Filter Logic

```python
def hard_filter(self, blackboard: Blackboard) -> bool:
    """Advisor requires Analyst output."""
    return blackboard.analyst_output is None
```

### Execute Logic

```python
async def execute(self, blackboard: Blackboard) -> AdvisorOutput:
    log_ctx = log.bind(agent_id=self.agent_id, task_id=blackboard.task_id)
    
    # Load relevant existing controls
    existing_controls = await self.controls_repo.find_by_topic(
        topics=blackboard.classifier_output.topic,
    )
    
    system_prompt = self.load_prompt()
    user_content = self._build_advisor_context(blackboard, existing_controls)
    
    output = await vertex_ai.generate_structured(
        model=self.model,
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=AdvisorOutput,
        max_tokens=3000,
    )
    
    # CRITICAL: Apply control updates to the controls table
    for update in output.control_updates:
        await self.controls_repo.apply_update(update)
        log_ctx.info("control_updated",
                     control_id=update.control_id,
                     field=update.field,
                     new_value=update.new_value)
    
    # Re-test affected controls
    for update in output.control_updates:
        new_status = await self.controls_repo.retest_control(update.control_id)
        update.new_status_after_retest = new_status
    
    # Send Datadog alert if generated
    if output.datadog_alert:
        await self.datadog_client.send_alert(output.datadog_alert)
        log_ctx.info("datadog_alert_sent",
                     severity=output.datadog_alert.severity,
                     control_id=output.datadog_alert.control_id)
    
    return output
```

### Error Handling

| Error | Action |
|---|---|
| Advisor tries to update non-existent control | Auditor catches via existence check |
| `action_plan` empty when Analyst flagged BREACH | Auditor flags as incomplete |
| Luminai SOP missing for `workflow_execution=true` | Auditor flags |
| Datadog alert send fails | Log error, surface in UI notification, continue |

---

## 7. The Auditor

### Identity

```python
agent_id = "the_auditor"
display_name = "The Auditor"
model = "gemini-3.1-pro"  # Reasoning model for deep validation
# ALWAYS RUNS LAST -- doesn't participate in claim resolution
```

### Output Pydantic Model

```python
class CitationVerification(BaseModel):
    claim: str
    source_reference: str    # e.g. "cftc_23_154_para_3"
    verified: bool
    grounding_score: float | None
    notes: str = ""

class AuditorChecks(BaseModel):
    citations_grounded: bool
    logical_consistency: bool
    no_fabrication: bool
    no_scope_drift: bool
    completeness: bool

class AuditorOutput(BaseModel):
    verdict: Literal["approved", "approved_with_warnings", "rejected"]
    checks: AuditorChecks
    warnings: list[str] = []
    blocking_issues: list[str] = []
    grounded_citations: list[CitationVerification] = []
    rejection_routes_to: Optional[str] = None  # agent_id to retry
```

### Execute Logic

The Auditor has TWO sub-systems:

1. **Vertex AI Check Grounding API** -- automated citation verification
2. **Gemini 3.1 Pro reasoning** -- everything else

```python
async def execute(self, blackboard: Blackboard) -> AuditorOutput:
    log_ctx = log.bind(agent_id=self.agent_id, task_id=blackboard.task_id)
    
    # Step 1: Extract all citation-worthy claims
    claims_with_sources = self._extract_claims(blackboard)
    
    # Step 2: Verify each via Check Grounding API
    citations = []
    for claim in claims_with_sources:
        verification = await vertex_ai.check_grounding(
            claim_text=claim.text,
            grounding_source=await self.reg_repo.get_text(claim.source_id),
        )
        citations.append(CitationVerification(
            claim=claim.text,
            source_reference=claim.source_id,
            verified=verification.is_grounded,
            grounding_score=verification.score,
            notes=verification.notes or "",
        ))
    
    # Step 3: LLM-as-judge for non-citation checks
    system_prompt = self.load_prompt()
    user_content = self._build_auditor_context(blackboard, citations)
    
    output = await vertex_ai.generate_structured(
        model=self.model,
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=AuditorOutput,
        max_tokens=3000,
    )
    output.grounded_citations = citations  # attach raw verification
    
    # Final verdict logic
    if not output.checks.no_fabrication or not output.checks.citations_grounded:
        output.verdict = "rejected"
        output.rejection_routes_to = self._determine_retry_target(output)
    elif output.warnings:
        output.verdict = "approved_with_warnings"
    else:
        output.verdict = "approved"
    
    log_ctx.info("auditor_complete",
                 verdict=output.verdict,
                 citations_verified=sum(1 for c in citations if c.verified),
                 warnings=len(output.warnings),
                 blocking_issues=len(output.blocking_issues))
    
    return output
```

### Routing on Rejection

| Issue | Routes To |
|---|---|
| Citation not grounded | Whichever agent made the claim (usually Mapper or Analyst) |
| Fabricated case name | The Analyst |
| Fabricated control ID | The Advisor |
| Logical inconsistency | The Mapper (re-derive) |
| Incomplete action plan | The Advisor |

Max retries: 2. After that, surface to user with "low confidence" disclaimer.

---

## 8. Token Budgets Per Agent

To stay within Gemini quota and Datadog LLM Obs cost ceiling:

| Agent | Phase 2 (score) | Phase 3 (execute) | Avg per task |
|---|---|---|---|
| Classifier | 8 out | 1500 out | 1500 |
| Mapper | 8 out | 3000 out | 3000 |
| Analyst | 8 out | 3500 out | 3500 |
| Advisor | 8 out | 2500 out | 2500 |
| Auditor | 0 (always runs) | 2500 out | 2500 |
| **TOTAL** | | | **~13,000 out per full chain** |

Input tokens vary based on context size. Plan for ~30,000 input + 13,000 output per chain.

---

## 9. Testing Each Agent

Each agent must have unit tests in `backend/tests/agents/test_<agent>.py`:

1. **Hard filter test** -- mock blackboard with each trigger type, verify pass/fail
2. **Score relevance test** -- mock blackboard, verify score range
3. **Output schema test** -- run with sample input, verify output validates against Pydantic model
4. **Failure mode test** -- mock LLM error, verify proper exception
5. **Citation grounding test (Auditor only)** -- mock Check Grounding response, verify verdict

See [TESTING.md](TESTING.md) for full testing strategy.

---

Read [DATA_MODEL.md](DATA_MODEL.md) next for the complete ClickHouse schema.
