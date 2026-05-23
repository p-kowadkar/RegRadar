# AGENTS.md

Complete specifications for all 4 agents. Read this before writing any agent code.

Every agent uses **Pydantic AI** with typed inputs and outputs. Every LLM call goes through `backend/integrations/vertex_ai.py`. Every agent writes to the blackboard `TriggerContext` and to ClickHouse.

---

## Table of Contents

1. [Pydantic AI Setup](#1-pydantic-ai-setup)
2. [Agent 1: Policy Crawler](#2-agent-1-policy-crawler)
3. [Agent 2: Impact Analysis](#3-agent-2-impact-analysis)
4. [Agent 3: Auditor (LLM-as-Judge)](#4-agent-3-auditor-llm-as-judge)
5. [Agent 4: Monitoring (Zero LLM)](#5-agent-4-monitoring-zero-llm)
6. [Inter-Agent Communication](#6-inter-agent-communication)
7. [Error Handling and Retries](#7-error-handling-and-retries)
8. [Datadog Instrumentation](#8-datadog-instrumentation)

---

## 1. Pydantic AI Setup

### Vertex AI model wrapper

```python
# backend/integrations/vertex_ai.py
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_vertex import GoogleVertexProvider
import os

_PROVIDER: GoogleVertexProvider | None = None


def _get_provider() -> GoogleVertexProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = GoogleVertexProvider(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
    return _PROVIDER


def vertex_model(model_name: str) -> GoogleModel:
    """Returns a Pydantic AI GoogleModel for a Vertex AI Gemini model.

    Valid names: 'gemini-3.5-flash', 'gemini-3.1-pro'
    """
    return GoogleModel(model_name=model_name, provider=_get_provider())
```

### Check Grounding API helper

```python
# backend/integrations/vertex_ai.py (continued)
from google.cloud import discoveryengine_v1
from pydantic import BaseModel


class GroundingCitation(BaseModel):
    source_id: str
    confidence: float
    supporting_text: str


class GroundingResult(BaseModel):
    claim: str
    is_grounded: bool
    overall_confidence: float
    citations: list[GroundingCitation]


_GROUNDING_CLIENT: discoveryengine_v1.GroundedGenerationServiceAsyncClient | None = None


async def check_grounding(*, claim: str, sources: list[str]) -> GroundingResult:
    """Call Vertex AI Check Grounding to verify a claim against sources."""
    global _GROUNDING_CLIENT
    if _GROUNDING_CLIENT is None:
        _GROUNDING_CLIENT = discoveryengine_v1.GroundedGenerationServiceAsyncClient()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    parent = f"projects/{project}/locations/global"

    request = discoveryengine_v1.CheckGroundingRequest(
        grounding_config=f"{parent}/groundingConfigs/default_grounding_config",
        answer_candidate=claim,
        facts=[
            discoveryengine_v1.GroundingFact(fact_text=src, attributes={"source_id": f"src_{i}"})
            for i, src in enumerate(sources)
        ],
        grounding_spec=discoveryengine_v1.CheckGroundingSpec(citation_threshold=0.6),
    )

    response = await _GROUNDING_CLIENT.check_grounding(request=request)

    return GroundingResult(
        claim=claim,
        is_grounded=response.support_score >= 0.65,
        overall_confidence=response.support_score,
        citations=[
            GroundingCitation(
                source_id=c.sources[0].source_id if c.sources else "unknown",
                confidence=c.score if hasattr(c, "score") else 0.0,
                supporting_text=c.text if hasattr(c, "text") else "",
            )
            for c in response.cited_chunks
        ],
    )
```

---

## 2. Agent 1: Policy Crawler

`backend/agents/policy_crawler.py`

### Inputs

```python
# backend/data/models.py
class PolicyCrawlInput(BaseModel):
    """Input passed to a single Policy Crawler run."""
    source_url: str                          # one regulatory source URL
    expected_regulator: str                  # "CFPB", "FRB", "FDIC", "FTC", etc.
    last_seen_content_hash: str | None       # for diff detection
```

### Outputs

```python
class ComplianceCondition(BaseModel):
    """One testable compliance condition extracted from regulation text."""
    condition_id: str                        # auto: f"cond_{uuid4()[:8]}"
    regulation_id: str                       # "tila_1026_9g"
    regulation_section: str                  # "12 CFR 1026.9(g)"
    condition_kind: Literal[
        "advance_notice",        # X days notice required before Y event
        "time_window",           # action must happen within X days of Y
        "field_match",           # bureau_status must match payment_status
        "stale_data_limit",      # value must be < X years/days old
        "dispute_flag_required", # field must be true when condition Y
    ]
    field_required: str                      # column on credit_card_accounts
    operator: Literal["lt", "lte", "eq", "gte", "gt", "exists", "matches"]
    threshold_value: float | str | int
    threshold_unit: Literal[
        "days", "years", "boolean", "string_match", "field_equality"
    ]
    account_scope: dict[str, Any] = Field(default_factory=dict)
    citation_text: str                       # exact quote from the regulation
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class PolicyExtractionResult(BaseModel):
    regulation_id: str
    title: str
    regulator: str
    version_id: str                          # content hash
    content_markdown: str
    content_chunks: list[str]                # for embedding
    extracted_conditions: list[ComplianceCondition]
    is_material_change: bool                 # True if updated vs. clarification
    change_summary: str | None
```

### Agent definition

```python
# backend/agents/policy_crawler.py
from pydantic_ai import Agent, RunContext
from backend.integrations.vertex_ai import vertex_model
from backend.integrations.nimble import NimbleClient
from backend.data.models import PolicyCrawlInput, PolicyExtractionResult
from backend.utils.logging import get_logger, annotate_llm_span

log = get_logger(__name__)


POLICY_CRAWLER_SYSTEM_PROMPT = """\
You are the Policy Crawler agent for RegRadar, a compliance monitoring system
for consumer credit card portfolios. Your job is to extract structured
compliance conditions from raw regulatory text.

You work exclusively on TWO federal regimes:
- TILA / Regulation Z (12 CFR 1026) — Truth in Lending Act
- FCRA (15 USC 1681) — Fair Credit Reporting Act

For every regulation you process, you must:

1. Identify the specific section number (e.g., "12 CFR 1026.9(g)" or "FCRA Section 605").
2. Extract every testable compliance condition the regulation imposes.
3. For each condition, specify EXACTLY:
   - The credit_card_accounts column that must satisfy the condition
   - The operator (lt, lte, eq, gte, gt, exists, matches)
   - The threshold value (numeric, string, or boolean)
   - The unit (days, years, boolean, string_match, field_equality)
   - The account_scope (which accounts this applies to — JSON dict)
   - The exact quote from the regulation supporting your extraction
   - The severity (LOW / MEDIUM / HIGH / CRITICAL)

If the regulation text is unclear or ambiguous, DO NOT INVENT CONDITIONS.
Return an empty extracted_conditions list and set is_material_change=false.

NEVER:
- Invent a regulation citation that does not exist in the source text
- Round numerical thresholds (e.g., "about 30 days" — extract the exact number)
- Generalize across regulations (each condition references exactly one section)
- Add severity ratings beyond what the text itself supports

If asked about a regulation outside TILA or FCRA, return an empty result.

For policy diffs: compare the new text against the prior version and determine
whether the change is MATERIAL (new threshold, new field, expanded scope) or
NON-MATERIAL (clarification, formatting, editorial). Set is_material_change
accordingly.

Your output is consumed downstream by deterministic SQL — precision matters
more than coverage. Better to extract zero conditions than to extract a
wrong condition.
"""


policy_crawler = Agent(
    model=vertex_model("gemini-3.5-flash"),
    input_type=PolicyCrawlInput,
    output_type=PolicyExtractionResult,
    system_prompt=POLICY_CRAWLER_SYSTEM_PROMPT,
)


@policy_crawler.tool
async def fetch_regulation_text(
    ctx: RunContext,
    source_url: str,
) -> str:
    """Scrape the regulation text from the source URL using Nimble (or Firecrawl fallback)."""
    nimble = NimbleClient.get()
    doc = await nimble.scrape_url(url=source_url, parsing_type="markdown")
    return doc.content


@policy_crawler.tool
async def search_related_guidance(
    ctx: RunContext,
    regulator: str,
    section: str,
) -> list[str]:
    """Search via Nimble for official guidance or interpretive bulletins on a section.

    Uses Nimble's grounded search for higher-quality results. Returns a list of
    excerpts that may help disambiguate the section's requirements.
    """
    nimble = NimbleClient.get()
    results = await nimble.search(
        query=f"{regulator} {section} interpretation guidance",
        num_results=5,
        deep_search=True,
    )
    return [r.content[:2000] for r in results]


async def run_crawler(input: PolicyCrawlInput) -> PolicyExtractionResult:
    """Top-level entry. Called by the scheduled task in main.py."""
    annotate_llm_span(agent_id="policy_crawler", trigger_id=f"crawl_{input.source_url[-20:]}")
    log.info("policy_crawler.start", url=input.source_url, regulator=input.expected_regulator)
    result = await policy_crawler.run(input)
    log.info(
        "policy_crawler.complete",
        url=input.source_url,
        conditions_extracted=len(result.output.extracted_conditions),
        material=result.output.is_material_change,
    )
    return result.output
```

### Scheduled execution

```python
# backend/main.py (lifespan startup)
import asyncio
from backend.agents.policy_crawler import run_crawler
from backend.data.models import PolicyCrawlInput
from backend.data.repositories import write_reg_version, write_policy_change


SCRAPE_TARGETS = [
    ("https://www.consumerfinance.gov/rules-policy/", "CFPB"),
    ("https://www.federalregister.gov/agencies/consumer-financial-protection-bureau", "CFPB"),
    ("https://www.federalreserve.gov/supervisionreg/srletters/srletters.htm", "FRB"),
    # ... ~10 sources total
]


async def policy_crawler_loop():
    while True:
        for url, regulator in SCRAPE_TARGETS:
            try:
                last_hash = await get_last_content_hash(url)
                input = PolicyCrawlInput(
                    source_url=url,
                    expected_regulator=regulator,
                    last_seen_content_hash=last_hash,
                )
                result = await run_crawler(input)
                if result.is_material_change:
                    await write_reg_version(result)
                    await write_policy_change(result)
            except Exception as e:
                log.error("policy_crawler.target_failed", url=url, error=str(e))
        await asyncio.sleep(3600)                       # 1 hour
```

---

## 3. Agent 2: Impact Analysis

`backend/agents/impact_analysis.py`

### Inputs

```python
class ImpactAnalysisInput(BaseModel):
    trigger_id: str
    trigger_type: Literal["policy_change", "schema_event", "behavior_event"]
    payload: dict                            # the source event row
    relevant_conditions: list[ComplianceCondition]   # pre-fetched from DB
```

### Outputs

```python
class AccountClassification(BaseModel):
    account_id: str
    status: Literal["BREACH", "AT_RISK", "MONITORING", "PASSING"]
    observed_value: float | str | bool
    required_value: float | str | bool
    days_to_deadline: int | None             # if time-based
    field_breached: str


class ControlUpdate(BaseModel):
    control_id: str
    new_status: Literal["PASSING", "WARNING", "FAILING"]
    affected_account_count: int
    affected_balance_usd: float
    rationale: str
    related_regulation_section: str


class ImpactReport(BaseModel):
    trigger_id: str
    affected_controls: list[ControlUpdate]
    classifications: dict[str, AccountClassification]   # account_id -> classification
    sample_account_ids: list[str]            # up to 20, for UI display
    total_breach_count: int
    total_at_risk_count: int
    total_balance_at_risk_usd: float
    citations: list[str]                     # regulation citations used
    suggested_remediation: list[str]
    reasoning: str                           # the agent's narrative explanation
```

### Agent definition

```python
# backend/agents/impact_analysis.py
from pydantic_ai import Agent, RunContext
from backend.integrations.vertex_ai import vertex_model
from backend.data.models import ImpactAnalysisInput, ImpactReport
from backend.data import repositories as repo


IMPACT_ANALYSIS_SYSTEM_PROMPT = """\
You are the Impact Analysis agent for RegRadar. You react to ONE event at a time
and determine which accounts on the credit card portfolio are affected.

You see three trigger types:

1. policy_change — a regulation was added or updated. You must scan ALL
   accounts against the new/changed conditions.

2. schema_event — a column was populated or added (e.g., original_delinquency_date
   backfilled from a migration). You must determine which existing
   ComplianceConditions are NOW evaluable because of the new data, and scan.

3. behavior_event — a discrete event on one account (e.g., dispute_filed=true,
   penalty_rate_applied=true). You must determine which controls fire as a
   result and start the appropriate clocks.

For each trigger, you produce an ImpactReport containing:

- Affected controls (which of the 6 controls move to WARNING or FAILING)
- Per-account classification (BREACH / AT_RISK / MONITORING / PASSING)
- Total breach count and notional balance exposure
- Exact regulatory citations supporting your decisions
- Suggested remediation steps (cite the regulation for each)

You have ONE tool: query_accounts(sql_template, params). Use it to execute
deterministic SQL against ClickHouse. Do NOT speculate about account counts —
always query.

NEVER:
- Estimate breach counts without querying
- Invent a regulation citation
- Round numerical thresholds in the SQL (use exact values from the condition)
- Skip the citation field — every claim must reference a regulatory section

For ambiguous account scoping (pre-effective-date accounts, partial documentation,
bankruptcy status): include them in the AT_RISK bucket with a clear reason in
the classification.field_breached field. Better to flag for human review than
to silently exclude.
"""


impact_analysis = Agent(
    model=vertex_model("gemini-3.5-flash"),
    input_type=ImpactAnalysisInput,
    output_type=ImpactReport,
    system_prompt=IMPACT_ANALYSIS_SYSTEM_PROMPT,
)


@impact_analysis.tool
async def query_accounts(
    ctx: RunContext,
    where_clause: str,
    params: dict,
) -> dict:
    """Execute a parameterized SQL query against credit_card_accounts.

    Args:
        where_clause: SQL WHERE clause (without the 'WHERE' keyword).
        params: Parameters to bind. Use ClickHouse parameter syntax: {param_name:Type}

    Returns:
        {
          "count": int,
          "total_balance_usd": float,
          "sample_account_ids": list[str]  (up to 20),
          "by_status": dict[str, int]
        }
    """
    return await repo.query_accounts_summary(where_clause, params)


@impact_analysis.tool
async def get_control_definition(
    ctx: RunContext,
    control_id: str,
) -> dict:
    """Fetch a control's current definition (threshold, scope, etc.)."""
    return await repo.get_control(control_id)


async def run_impact_analysis(input: ImpactAnalysisInput) -> ImpactReport:
    annotate_llm_span(
        agent_id="impact_analysis",
        trigger_id=input.trigger_id,
        trigger_type=input.trigger_type,
    )
    log.info("impact_analysis.start", trigger_id=input.trigger_id, trigger_type=input.trigger_type)
    result = await impact_analysis.run(input)
    log.info(
        "impact_analysis.complete",
        trigger_id=input.trigger_id,
        breaches=result.output.total_breach_count,
        at_risk=result.output.total_at_risk_count,
    )
    return result.output
```

### Event polling worker

```python
# backend/orchestrator/event_poller.py
import asyncio
from backend.data import repositories as repo
from backend.agents.impact_analysis import run_impact_analysis
from backend.agents.auditor import run_auditor


async def event_poller_loop(poll_interval_ms: int = 500):
    """Continuously polls schema_events + behavior_events + policy_changes."""
    while True:
        events = await repo.get_unprocessed_events(limit=10)
        for event in events:
            try:
                conditions = await repo.get_active_conditions_for_event(event)
                input = ImpactAnalysisInput(
                    trigger_id=event["trigger_id"],
                    trigger_type=event["event_type"],
                    payload=event["payload"],
                    relevant_conditions=conditions,
                )
                report = await run_impact_analysis(input)
                await repo.write_impact_report(report)

                # Hand off to Auditor
                verdict = await run_auditor(report)
                await repo.write_auditor_verdict(verdict)

                # If approved, publish + alert (orchestrated in main pipeline)
                if verdict.verdict in ("approved", "approved_with_warnings"):
                    asyncio.create_task(publish_and_alert(report, verdict))

                await repo.mark_event_processed(event["trigger_id"])
            except Exception as e:
                log.error("event_poller.failed", trigger_id=event["trigger_id"], error=str(e))
                await repo.mark_event_failed(event["trigger_id"], str(e))
        await asyncio.sleep(poll_interval_ms / 1000)
```

---

## 4. Agent 3: Auditor (LLM-as-Judge)

`backend/agents/auditor.py`

### Inputs

```python
class AuditorInput(BaseModel):
    impact_report: ImpactReport
    source_regulations: dict[str, str]       # regulation_section -> content_markdown
```

### Outputs

```python
class ClaimAudit(BaseModel):
    claim: str
    cited_section: str | None
    confidence: float
    supporting_text: str | None
    flagged_reason: str | None


class AuditorVerdict(BaseModel):
    trigger_id: str
    verdict: Literal["approved", "approved_with_warnings", "rejected"]
    overall_confidence: float
    claims_audited: list[ClaimAudit]
    warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    safe_to_publish: bool
    safe_to_alert: bool
```

### Agent definition

```python
# backend/agents/auditor.py
from pydantic_ai import Agent, RunContext
from backend.integrations.vertex_ai import vertex_model, check_grounding
from backend.data.models import AuditorInput, AuditorVerdict, ClaimAudit
from backend.data import repositories as repo


AUDITOR_SYSTEM_PROMPT = """\
You are the Auditor agent for RegRadar. You are an LLM-as-Judge that verifies
the grounding of every claim made by the Impact Analysis Agent before any
output is published externally or used for alerting.

Your job is to FAIL CLOSED. When in doubt, reject. The cost of a published
hallucination (fabricated case citation, wrong dollar amount, invented
section number) in a compliance system is catastrophic.

For each ImpactReport, you must:

1. Decompose the report into individual factual claims. A claim is anything that
   asserts a number, a regulatory citation, a case reference, a deadline, or a
   prescriptive recommendation.

2. For each claim, use the grounding_check tool to verify it against the
   provided source_regulations.

3. Aggregate verdict:
   - If every claim has confidence >= 0.85 → approved, safe_to_publish=true, safe_to_alert=true
   - If any claim has confidence in [0.65, 0.85) → approved_with_warnings,
     safe_to_publish=true, safe_to_alert=true, list each warning
   - If any claim has confidence < 0.65 → rejected, safe_to_publish=false,
     safe_to_alert=false, list each rejection reason with the failing text

4. Be especially strict about:
   - Case citations (e.g., "Citi was fined $1.975M") — every dollar amount, every party name
   - Section numbers (e.g., "12 CFR 1026.9(g)") — must match the regulation_section field
   - Deadlines (e.g., "30 days", "45 days") — must match the threshold_value
   - Prescriptive language ("must", "required to") — must be supported by the citation

5. NEVER add your own claims. NEVER invent additional support for a flagged claim.
   You exist to verify, not generate.

Your verdict is final for publishing decisions. The downstream Senso publisher
and Datadog alerter both check safe_to_publish and safe_to_alert.
"""


auditor = Agent(
    model=vertex_model("gemini-3.1-pro"),   # use Pro for deeper reasoning
    input_type=AuditorInput,
    output_type=AuditorVerdict,
    system_prompt=AUDITOR_SYSTEM_PROMPT,
)


@auditor.tool
async def grounding_check(
    ctx: RunContext,
    claim: str,
    cited_section: str,
) -> dict:
    """Run Vertex AI Check Grounding for a single claim against the source regulation."""
    sources_dict = ctx.deps["source_regulations"]
    source_text = sources_dict.get(cited_section, "")
    if not source_text:
        return {
            "is_grounded": False,
            "confidence": 0.0,
            "reason": f"No source text available for {cited_section}",
        }
    result = await check_grounding(claim=claim, sources=[source_text])
    return {
        "is_grounded": result.is_grounded,
        "confidence": result.overall_confidence,
        "supporting_text": result.citations[0].supporting_text if result.citations else None,
    }


async def run_auditor(report: ImpactReport) -> AuditorVerdict:
    annotate_llm_span(agent_id="auditor", trigger_id=report.trigger_id)
    log.info("auditor.start", trigger_id=report.trigger_id)

    # Fetch source regulations for every citation in the report
    source_regulations = {}
    for citation in report.citations:
        text = await repo.get_regulation_text(citation)
        if text:
            source_regulations[citation] = text

    input = AuditorInput(
        impact_report=report,
        source_regulations=source_regulations,
    )
    result = await auditor.run(
        input,
        deps={"source_regulations": source_regulations},
    )

    log.info(
        "auditor.complete",
        trigger_id=report.trigger_id,
        verdict=result.output.verdict,
        confidence=result.output.overall_confidence,
    )
    return result.output
```

### Publishing and alerting gates

```python
# backend/orchestrator/publish_alert.py
from backend.integrations.senso import publish_brief
from backend.integrations.datadog import DatadogAlerter


async def publish_and_alert(report: ImpactReport, verdict: AuditorVerdict):
    if not verdict.safe_to_publish:
        log.warning("publish_skipped.audit_rejected", trigger_id=report.trigger_id)
        return

    # 1. Publish brief to cited.md via Senso
    try:
        brief = build_compliance_brief(report, verdict)
        published = await publish_brief(brief)
        log.info("publish.cited_md", trigger_id=report.trigger_id, url=published.url)
    except Exception as e:
        log.error("publish.failed", trigger_id=report.trigger_id, error=str(e))
        published = None

    # 2. Datadog alert (with the cited.md URL if available)
    if verdict.safe_to_alert:
        for ctrl_update in report.affected_controls:
            if ctrl_update.new_status == "FAILING":
                await DatadogAlerter.send_control_breach_alert(
                    control_id=ctrl_update.control_id,
                    affected_account_count=ctrl_update.affected_account_count,
                    affected_balance_usd=ctrl_update.affected_balance_usd,
                    owner_team=...,
                    cited_md_url=published.url if published else None,
                )
```

---

## 5. Agent 4: Monitoring (Zero LLM)

`backend/agents/monitoring.py`

This is not a Pydantic AI agent. It makes ZERO LLM calls. Pure SQL.

```python
# backend/agents/monitoring.py
from backend.data import repositories as repo
from backend.integrations.datadog import DatadogAlerter


async def run_monitoring_sweep() -> dict:
    """Daily sweep across all 6 controls. Returns summary."""
    log.info("monitoring.sweep_start")

    results = {}
    for control in await repo.list_all_controls():
        scan = await repo.execute_control_check(control)
        await repo.write_compliance_scan(scan)

        if scan["breach_count"] > 0:
            await DatadogAlerter.send_control_breach_alert(
                control_id=control["control_id"],
                affected_account_count=scan["breach_count"],
                affected_balance_usd=scan["breach_balance_usd"],
                owner_team=control["owner_team"],
                source="daily_monitoring",
            )

        results[control["control_id"]] = scan

    log.info("monitoring.sweep_complete", controls_scanned=len(results))
    return results


# backend/main.py (lifespan)
async def monitoring_loop():
    """Run every 24 hours."""
    while True:
        try:
            await run_monitoring_sweep()
        except Exception as e:
            log.error("monitoring.sweep_failed", error=str(e))
        await asyncio.sleep(24 * 3600)
```

### Why zero LLM

- The 6 controls are SQL-evaluable via `controls.check_sql` (stored at seed time)
- Daily scan over 50k+ accounts in milliseconds with ClickHouse
- Zero hallucination surface
- Zero per-call cost

The Monitoring Agent's whole job is "did anything become non-compliant today that the event-driven pipeline missed?" Adding an LLM here would slow it down and add fragility.

---

## 6. Inter-Agent Communication

Agents communicate via the database, not direct calls. This gives us:

- Persistent audit trail (every trigger, every output, every verdict)
- Restart safety (if backend crashes mid-run, the worker picks up)
- Easy multi-process scaling later (just point more workers at the same tables)

**Flow:**

```
Policy Crawler
   ↓ writes
reg_versions + policy_changes (Postgres-style INSERT, ClickHouse SELECT)
   ↓ polled by event_poller_loop (500ms)
Impact Analysis
   ↓ writes
impact_reports
   ↓ direct in-memory handoff
Auditor
   ↓ writes
auditor_verdicts + audit_trail
   ↓ if safe_to_publish
Senso publish + Datadog alert (parallel tasks)
   ↓ writes
published_briefs + dd_alerts
```

The only direct in-memory handoff is Impact Analysis → Auditor, because the Auditor must run before any external side effect (publish/alert) can happen, and adding a polling step would needlessly delay the user-visible chain.

---

## 7. Error Handling and Retries

### Per-agent retry policy

Wrap every agent run in `tenacity` retry:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((google_genai_errors.ResourceExhaustedError, asyncio.TimeoutError)),
)
async def run_with_retry(input):
    return await agent.run(input)
```

After 3 failures on Vertex AI: fall back to OpenRouter with the same prompt (see INTEGRATIONS.md).

### What gets retried where

| Agent | Retry on | Don't retry on |
|---|---|---|
| Policy Crawler | Network errors, rate limits, timeouts | Validation errors (schema mismatch — log and skip) |
| Impact Analysis | Network errors, rate limits, timeouts | Auditor rejection (different recovery path) |
| Auditor | Network errors, rate limits, timeouts | Grounding failures (intended outcome) |
| Monitoring | Network errors (ClickHouse) | SQL errors (configuration bug — alert team) |

### Auditor rejection retry

When the Auditor rejects an ImpactReport, we DO NOT automatically retry the same prompt. Instead:

1. Write the rejection to `audit_trail`
2. Increment a `retry_count` on the trigger
3. Re-invoke Impact Analysis with the prompt augmented by the rejection reasons ("Your previous response was rejected because: ...")
4. If 2nd attempt also rejected, give up and alert the team manually

Max 2 attempts per trigger.

---

## 8. Datadog Instrumentation

### Auto-instrumented (via ddtrace-run)

- All `google-genai` calls → LLM spans
- All Pydantic AI agent runs → spans (Pydantic AI emits OpenTelemetry traces by default)
- All `clickhouse-connect` queries → DB spans
- All `httpx`/`aiohttp` outbound calls → HTTP spans
- All FastAPI routes → HTTP spans

### Custom tags

At the start of every agent run, call `annotate_llm_span()` to tag the active span:

```python
from backend.utils.logging import annotate_llm_span

async def run_crawler(input):
    annotate_llm_span(
        agent_id="policy_crawler",
        trigger_id=input.source_url,         # or a real trigger ID
        extra_tags={"regulator": input.expected_regulator},
    )
    # ... rest of agent logic
```

### What we see in Datadog AI Agent Console

- A graph node per agent: Policy Crawler · Impact Analysis · Auditor · Monitoring
- Edges showing call patterns (Impact Analysis → Auditor, Auditor → grounding_check)
- Per-agent latency, token cost, error rate
- Per-trigger drill-down: click a trigger_id, see the full chain

### Pre-demo Datadog smoke

Before going on stage, verify:

```bash
ddtrace-run python -c "
from backend.agents.policy_crawler import run_crawler
import asyncio
asyncio.run(run_crawler({'source_url': 'https://test', 'expected_regulator': 'CFPB', 'last_seen_content_hash': None}))
"
# Then check Datadog LLM Obs for a span tagged agent=policy_crawler
```

---

## AI Tool Hints

Building these agents in order:

1. **vertex_ai.py first.** Get the Pydantic AI provider wrapper + check_grounding helper working in isolation. Smoke-test with a one-liner.

2. **Policy Crawler next.** Easiest agent. Single input, single output. Test with a hardcoded regulation URL.

3. **Impact Analysis third.** Requires Policy Crawler output (ComplianceConditions) and ClickHouse data (synthetic accounts) — so it can only be tested end-to-end after those exist.

4. **Auditor fourth.** Requires Impact Analysis output. Test with hand-crafted ImpactReports that contain a deliberate hallucination — verify the Auditor catches it.

5. **Monitoring last.** Simplest agent (pure SQL). Just runs all `controls.check_sql` queries on a timer.

**Do not** start writing all 4 agents in parallel. Each depends on the schemas of the prior.
