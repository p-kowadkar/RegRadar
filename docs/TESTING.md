# TESTING.md

How to verify everything works -- before the demo, during the demo, and what to do if it doesn't.

This file is meant to be read TWICE. Once during dev to write the tests. Once at T-24 hours to verify nothing's broken.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Smoke Tests](#2-smoke-tests)
3. [Unit Tests](#3-unit-tests)
4. [Integration Tests](#4-integration-tests)
5. [End-to-End Demo Test](#5-end-to-end-demo-test)
6. [Pre-Demo Run-Through](#6-pre-demo-run-through)
7. [Failure Recovery Procedures](#7-failure-recovery-procedures)
8. [Pre-Recorded Backup Videos](#8-pre-recorded-backup-videos)

---

## 1. Philosophy

For hackathon scope, we prioritize:

1. **Smoke tests** that confirm every integration works -- run before every demo attempt
2. **End-to-end demo test** that runs the full CFTC cascade -- run 3+ times before pitch
3. **Failure recovery procedures** rehearsed so we don't panic on stage

We do NOT prioritize:

- Code coverage targets
- Property-based testing
- Load testing (we're demoing one trigger, not 10,000 RPS)
- Mutation testing
- Snapshot testing of UI

If a test isn't directly testing "will this work on stage tomorrow," skip it for now.

---

## 2. Smoke Tests

`scripts/smoke_test.py` is the source of truth for "is everything working." Run it before EVERY demo attempt.

### Smoke Test Coverage

```python
# scripts/smoke_test.py
"""
Verifies every integration works.
Exits 0 on success, 1 on first failure.
Run after setup, before demo, and before any push to main.
"""
import asyncio
import sys
import structlog
from rich.console import Console
from rich.table import Table

log = structlog.get_logger()
console = Console()


async def smoke_test():
    results = []
    
    # 1. Env vars
    try:
        from backend.utils import env
        env.validate()
        results.append(("Env vars validated", True, None))
    except Exception as e:
        results.append(("Env vars validated", False, str(e)))
        return _report(results)
    
    # 2. ClickHouse connection
    try:
        from backend.integrations.clickhouse_client import ClickHouseClient
        client = ClickHouseClient.get_sync()
        version = client.query("SELECT version()").result_rows[0][0]
        results.append(("ClickHouse connected", True, f"v{version}"))
    except Exception as e:
        results.append(("ClickHouse connected", False, str(e)))
    
    # 3. Seed data loaded
    try:
        client = ClickHouseClient.get_sync()
        kg_count = client.query("SELECT COUNT(*) FROM kg_nodes").result_rows[0][0]
        reg_count = client.query("SELECT COUNT(*) FROM reg_versions").result_rows[0][0]
        deriv_count = client.query("SELECT COUNT(*) FROM derivatives_portfolio").result_rows[0][0]
        ctrl_count = client.query("SELECT COUNT(*) FROM controls").result_rows[0][0]
        assert kg_count >= 100, f"Expected >=100 kg_nodes, got {kg_count}"
        assert reg_count >= 20, f"Expected >=20 regs, got {reg_count}"
        assert deriv_count >= 3000, f"Expected >=3000 derivatives, got {deriv_count}"
        assert ctrl_count >= 8, f"Expected >=8 controls, got {ctrl_count}"
        results.append(("Seed data loaded", True,
                        f"{kg_count} KG, {reg_count} regs, {deriv_count} derivs, {ctrl_count} ctrls"))
    except Exception as e:
        results.append(("Seed data loaded", False, str(e)))
    
    # 4. Vertex AI / Gemini works
    try:
        from backend.integrations.vertex_ai import VertexAIClient
        client = VertexAIClient.get()
        response = await client.generate(
            model="gemini-3.5-flash",
            prompt="Reply with exactly the word OK and nothing else.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response, f"Unexpected response: {response}"
        results.append(("Gemini 3.5 Flash works", True, None))
    except Exception as e:
        results.append(("Gemini 3.5 Flash works", False, str(e)))
    
    # 5. Gemini 3.1 Pro works
    try:
        from backend.integrations.vertex_ai import VertexAIClient
        client = VertexAIClient.get()
        response = await client.generate(
            model="gemini-3.1-pro",
            prompt="Reply with exactly the word OK and nothing else.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response
        results.append(("Gemini 3.1 Pro works", True, None))
    except Exception as e:
        results.append(("Gemini 3.1 Pro works", False, str(e)))
    
    # 6. OpenRouter fallback works
    try:
        from backend.integrations.openrouter import OpenRouterClient
        client = OpenRouterClient.get()
        response = await client.generate(
            model="gemini-3.5-flash",
            prompt="Reply with exactly the word OK.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response
        results.append(("OpenRouter fallback works", True, None))
    except Exception as e:
        results.append(("OpenRouter fallback works", False, str(e)))
    
    # 7. Nimble works
    try:
        from backend.integrations.nimble import NimbleClient
        client = NimbleClient.get()
        result = await client.search(query="SEC press release", num_results=2)
        assert len(result) > 0
        results.append(("Nimble search works", True, f"{len(result)} results"))
    except Exception as e:
        results.append(("Nimble search works", False, str(e)))
    
    # 8. Firecrawl fallback works
    try:
        from backend.integrations.firecrawl import FirecrawlClient
        client = FirecrawlClient.get()
        doc = await client.scrape_url("https://example.com")
        assert len(doc.content) > 0
        results.append(("Firecrawl fallback works", True, None))
    except Exception as e:
        results.append(("Firecrawl fallback works", False, str(e)))
    
    # 9. Datadog ingest works (best-effort -- can't really verify without UI check)
    try:
        from backend.integrations.datadog import DatadogAlerter
        DatadogAlerter.init()
        await DatadogAlerter.send_control_breach_alert(
            control_id="CTRL-SMOKE-TEST",
            control_name="Smoke Test (ignore)",
            regulation_title="Smoke test",
            affected_position_count=0,
            notional_exposure_usd=0,
            owner_team="dev",
            severity="info",
        )
        results.append(("Datadog ingest works", True, "check Datadog UI for event"))
    except Exception as e:
        results.append(("Datadog ingest works", False, str(e)))
    
    # 10. Luminai (skip if no creds yet)
    try:
        from backend.utils import env
        if not env.get("LUMINAI_API_KEY", default=""):
            results.append(("Luminai (skipped -- no creds)", True, "fill in at hackathon"))
        else:
            from backend.integrations.luminai import LuminaiClient
            client = LuminaiClient.get()
            # Just check we can hit the base URL
            response = await client.http.get("/health")
            results.append(("Luminai reachable", True, None))
    except Exception as e:
        results.append(("Luminai reachable", False, str(e)))
    
    return _report(results)


def _report(results):
    table = Table(title="RegRadar Smoke Test Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Detail", style="dim")
    
    all_passed = True
    for check, passed, detail in results:
        if passed:
            status = "[green]✓ PASS[/green]"
        else:
            status = "[red]✗ FAIL[/red]"
            all_passed = False
        table.add_row(check, status, detail or "")
    
    console.print(table)
    
    if all_passed:
        console.print("\n[bold green]All checks passed. Ready to demo.[/bold green]")
        return 0
    else:
        console.print("\n[bold red]Some checks failed. Fix before continuing.[/bold red]")
        return 1


if __name__ == "__main__":
    code = asyncio.run(smoke_test())
    sys.exit(code)
```

### Running Smoke Tests

```bash
# Default run
python scripts/smoke_test.py

# Verbose with full stack traces
python scripts/smoke_test.py --verbose

# Only check seed data
python scripts/smoke_test.py --check-seed
```

### When To Run

- After initial setup (`./scripts/setup.sh` calls this at the end)
- After any `.env` change
- At T-2 hours before demo
- After every git pull
- Whenever something feels wrong

---

## 3. Unit Tests

Unit tests live in `tests/` mirroring the `backend/` structure. Use `pytest` with `pytest-asyncio`.

### Required Unit Tests

For hackathon scope, write unit tests ONLY for these high-risk modules:

| Module | Why | Test File |
|---|---|---|
| `backend/orchestrator/blackboard.py` | Concurrency bugs are devastating | `tests/test_blackboard.py` |
| `backend/orchestrator/ordering.py` | Dependency resolution is subtle | `tests/test_ordering.py` |
| `backend/agents/base.py` | All agents inherit -- bugs propagate | `tests/test_base_agent.py` |
| `backend/data/repositories.py` | Wrong query = wrong demo | `tests/test_repositories.py` |
| `backend/utils/env.py` | Validation must be strict | `tests/test_env.py` |

Skip unit tests for everything else. Integration tests + smoke tests cover them.

### Example: Blackboard Test

```python
# tests/test_blackboard.py
import pytest
from backend.orchestrator.blackboard import Blackboard, AgentClaim


@pytest.mark.asyncio
async def test_blackboard_collects_claims():
    bb = Blackboard(trigger_id="test_001")
    bb.add_claim(AgentClaim(
        agent_id="classifier",
        relevance_score=0.92,
        response_type="primary",
        depends_on=[],
        reasoning="test",
    ))
    bb.add_claim(AgentClaim(
        agent_id="mapper",
        relevance_score=0.88,
        response_type="primary",
        depends_on=["classifier"],
        reasoning="test",
    ))
    
    claims = bb.get_claims()
    assert len(claims) == 2
    assert claims[0].agent_id == "classifier"


@pytest.mark.asyncio
async def test_blackboard_caps_at_max_per_message(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_PER_MESSAGE", "3")
    bb = Blackboard(trigger_id="test_002")
    for i in range(5):
        bb.add_claim(AgentClaim(
            agent_id=f"agent_{i}",
            relevance_score=0.9 - i * 0.05,
            response_type="primary",
            depends_on=[],
            reasoning="test",
        ))
    
    final = bb.resolve_claims()
    assert len(final) == 3                       # capped at 3
    assert final[0].agent_id == "agent_0"        # highest relevance kept
```

### Example: Ordering Test

```python
# tests/test_ordering.py
from backend.orchestrator.ordering import topological_sort
from backend.orchestrator.blackboard import AgentClaim


def test_topological_sort_respects_dependencies():
    claims = [
        AgentClaim(agent_id="advisor", relevance_score=0.8, response_type="supporting",
                   depends_on=["analyst"], reasoning=""),
        AgentClaim(agent_id="analyst", relevance_score=0.85, response_type="supporting",
                   depends_on=["mapper"], reasoning=""),
        AgentClaim(agent_id="mapper", relevance_score=0.9, response_type="primary",
                   depends_on=["classifier"], reasoning=""),
        AgentClaim(agent_id="classifier", relevance_score=0.95, response_type="primary",
                   depends_on=[], reasoning=""),
    ]
    sorted_claims = topological_sort(claims)
    order = [c.agent_id for c in sorted_claims]
    assert order == ["classifier", "mapper", "analyst", "advisor"]


def test_topological_sort_handles_cycle():
    """Dependency cycles should raise."""
    import pytest
    claims = [
        AgentClaim(agent_id="a", depends_on=["b"], relevance_score=0.8,
                   response_type="primary", reasoning=""),
        AgentClaim(agent_id="b", depends_on=["a"], relevance_score=0.8,
                   response_type="primary", reasoning=""),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topological_sort(claims)
```

### Running Unit Tests

```bash
# All unit tests
pytest tests/ -v

# Just one file
pytest tests/test_blackboard.py -v

# With coverage
pytest tests/ --cov=backend --cov-report=term-missing
```

---

## 4. Integration Tests

Integration tests verify multi-component behavior. Live in `tests/integration/`.

### Required Integration Tests

| Test | What It Verifies | File |
|---|---|---|
| `test_cftc_cascade` | Full CFTC demo arc end-to-end | `tests/integration/test_cftc_cascade.py` |
| `test_nimble_failover_to_firecrawl` | When Nimble fails, Firecrawl picks up | `tests/integration/test_scraping_failover.py` |
| `test_gemini_failover_to_openrouter` | When Vertex AI fails, OpenRouter picks up | `tests/integration/test_llm_failover.py` |
| `test_auditor_rejects_fabrication` | Auditor blocks hallucinated citations | `tests/integration/test_auditor.py` |
| `test_control_breach_triggers_datadog_alert` | Advisor → Datadog wiring | `tests/integration/test_control_alerting.py` |
| `test_proactive_trigger_fires_cascade` | Watcher → blackboard → agents | `tests/integration/test_proactive.py` |

### Example: CFTC Cascade Test

```python
# tests/integration/test_cftc_cascade.py
import pytest
import asyncio
from backend.orchestrator.blackboard import Blackboard
from backend.agents import (
    ClassifierAgent, MapperAgent, AnalystAgent, AdvisorAgent, AuditorAgent
)
from backend.data.models import RegulationEvent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cftc_cascade_completes_in_under_15s():
    """The showcase demo must complete in < 15 seconds end-to-end."""
    # Setup -- a fake CFTC margin amendment event
    event = RegulationEvent(
        reg_id="cftc_margin_amend_2026",
        title="Final Rule: Initial Margin Requirements for Uncleared Swaps",
        content="...effective date 2026-07-21...threshold increased from 6% to 8%...",
        source_url="https://cftc.gov/PressRoom/PressReleases/example",
        regulator="CFTC",
    )
    
    bb = Blackboard(trigger_id="test_cftc_cascade")
    bb.set_regulation_event(event)
    
    agents = [
        ClassifierAgent(),
        MapperAgent(),
        AnalystAgent(),
        AdvisorAgent(),
        AuditorAgent(),
    ]
    
    start = asyncio.get_event_loop().time()
    
    # Phase 1: All agents score relevance in parallel
    scores = await asyncio.gather(*[
        agent.score_relevance(bb) for agent in agents
    ])
    for agent, score in zip(agents, scores):
        claim = agent.classify_claim_type(score, bb)
        if claim:
            bb.add_claim(claim)
    
    # Phase 2: Resolve order
    resolved = bb.resolve_claims()
    
    # Phase 3: Execute in order, respecting dependencies
    for claim in resolved:
        agent = next(a for a in agents if a.agent_id == claim.agent_id)
        await agent.execute(bb)
    
    elapsed = asyncio.get_event_loop().time() - start
    
    assert elapsed < 15.0, f"Cascade took {elapsed:.1f}s, must be < 15s"
    
    # Verify outputs
    classifier_output = bb.get_agent_output("classifier")
    assert classifier_output.severity == "HIGH"
    
    mapper_output = bb.get_agent_output("mapper")
    assert mapper_output.portfolio_scan.affected_positions > 800
    
    analyst_output = bb.get_agent_output("analyst")
    assert analyst_output.position_classification.BREACH > 0
    
    advisor_output = bb.get_agent_output("advisor")
    assert any(c.control_id == "CTRL-001" for c in advisor_output.control_updates)
    
    auditor_output = bb.get_agent_output("auditor")
    assert auditor_output.verdict == "approved"
```

### Running Integration Tests

```bash
# All integration tests (requires real services)
pytest tests/integration/ -v --integration

# Skip integration tests in regular runs
pytest tests/ -v -m "not integration"
```

Mark integration tests with `@pytest.mark.integration` so they can be opted into.

---

## 5. End-to-End Demo Test

`scripts/demo_e2e_test.py` is the closest thing to "rehearse the demo." It runs the full sequence the demo will run, with the same triggers, and validates each step.

```python
# scripts/demo_e2e_test.py
"""
Runs the full demo sequence non-interactively.
Validates each agent fires, each output is correct, and total time is reasonable.
Run this 3+ times the day before the demo.
"""
import asyncio
import httpx
import time
from rich.console import Console

console = Console()
BASE_URL = "http://localhost:8000"


async def run_demo_e2e():
    """Execute the full demo arc against a running backend."""
    
    async with httpx.AsyncClient(timeout=60.0) as http:
        # 1. Health check
        r = await http.get(f"{BASE_URL}/api/health")
        assert r.status_code == 200, "Backend not healthy"
        console.print("[green]✓[/green] Backend healthy")
        
        # 2. Dashboard summary loads
        r = await http.get(f"{BASE_URL}/api/dashboard/summary")
        assert r.status_code == 200
        summary = r.json()
        assert summary["controls"]["total"] >= 8
        assert summary["positions"]["derivatives"] >= 3000
        console.print("[green]✓[/green] Dashboard summary loads")
        
        # 3. Fire CFTC trigger and time the cascade
        start = time.time()
        r = await http.post(
            f"{BASE_URL}/api/internal/trigger",
            json={"event_type": "cftc_margin_amendment"},
        )
        assert r.status_code == 200
        trigger_id = r.json()["trigger_id"]
        console.print(f"[blue]▶[/blue] Trigger fired: {trigger_id}")
        
        # 4. Poll for cascade completion
        for attempt in range(30):                    # 30 sec timeout
            r = await http.get(f"{BASE_URL}/api/triggers/{trigger_id}/status")
            status = r.json()
            if status["state"] == "completed":
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError("Cascade did not complete in 30s")
        
        elapsed = time.time() - start
        console.print(f"[green]✓[/green] Cascade completed in {elapsed:.1f}s")
        assert elapsed < 20.0, "Cascade too slow for demo"
        
        # 5. Verify each agent output
        r = await http.get(f"{BASE_URL}/api/triggers/{trigger_id}/outputs")
        outputs = r.json()
        
        assert outputs["classifier"]["severity"] == "HIGH"
        console.print("[green]✓[/green] Classifier: HIGH severity")
        
        assert outputs["mapper"]["portfolio_scan"]["affected_positions"] > 800
        console.print(f"[green]✓[/green] Mapper: {outputs['mapper']['portfolio_scan']['affected_positions']} positions")
        
        assert outputs["analyst"]["position_classification"]["BREACH"] > 100
        console.print(f"[green]✓[/green] Analyst: {outputs['analyst']['position_classification']['BREACH']} BREACH")
        
        assert any(
            c["control_id"] == "CTRL-001"
            for c in outputs["advisor"]["control_updates"]
        )
        console.print("[green]✓[/green] Advisor: CTRL-001 updated")
        
        assert outputs["auditor"]["verdict"] in ("approved", "approved_with_warnings")
        console.print("[green]✓[/green] Auditor: approved")
        
        # 6. Verify control status was updated
        r = await http.get(f"{BASE_URL}/api/controls/CTRL-001")
        ctrl = r.json()
        assert ctrl["status"] == "FAILING"
        assert ctrl["threshold"] == 0.08
        console.print("[green]✓[/green] CTRL-001 now FAILING with threshold 0.08")
        
        # 7. Verify Datadog alert was sent (best-effort)
        r = await http.get(f"{BASE_URL}/api/internal/recent_alerts")
        alerts = r.json()
        assert any(a["control_id"] == "CTRL-001" for a in alerts[-5:])
        console.print("[green]✓[/green] Datadog alert recorded")
    
    console.print(f"\n[bold green]Full demo E2E passed in {elapsed:.1f}s[/bold green]")


if __name__ == "__main__":
    asyncio.run(run_demo_e2e())
```

Run this:
- 3+ times the day before the demo
- Once right before going on stage (with `--quiet` flag)

---

## 6. Pre-Demo Run-Through

The day-of rehearsal. This is the only kind of testing that catches "presenter brain" issues.

### Full Run-Through Checklist

Do this 3 times back-to-back. If any iteration fails or feels rough, do a 4th.

- [ ] Frontend loads in browser (no errors in console)
- [ ] Sidebar navigation works (Dashboard / Chat / Graph / Controls)
- [ ] KPI cards show real numbers, not "loading" or "0"
- [ ] Live feed shows last 5+ regulatory events
- [ ] Click into a regulation -- side panel shows source text + citations
- [ ] Open Chat view -- agent avatars visible
- [ ] Type "hi" in chat -- get a response within 5s
- [ ] Type "what regulations apply to our IR swaps?" -- multi-agent response
- [ ] Open Graph view -- nodes render, edges visible
- [ ] Click a node -- inspector panel opens
- [ ] Open Controls view -- 8 controls visible with statuses
- [ ] Fire demo trigger (`python scripts/demo_trigger.py --event=cftc_margin_amendment`)
- [ ] Cascade visible in Chat view -- all 5 agents speak in order
- [ ] CTRL-001 changes color from green to red in Controls view
- [ ] Datadog alert appears in alerts panel
- [ ] Click "Execute SAR filing" action -- Luminai iframe loads
- [ ] Tab to Datadog LLM Obs in browser -- AI Agent Console shows the chain
- [ ] All-clear: no error toasts, no console errors, no stale UI states

### What Each Team Member Watches For

| Person | Watches For | When |
|---|---|---|
| Presenter | UX flow, narrative timing | Throughout |
| Backend dev | Server logs scrolling clean | Continuously |
| Frontend dev | Browser console errors | Continuously |
| QA / fifth team member | Datadog UI, Nimble credits left | Continuously |
| Note-taker | Issues to fix between rehearsals | Throughout |

---

## 7. Failure Recovery Procedures

Stage failures are inevitable. Prepared > improvised.

### Failure Matrix

| Failure Mode | Detection | Recovery |
|---|---|---|
| **Cascade doesn't start** | Trigger fired but no agent activity for 5s | Acknowledge: "Our agent system seems slow -- let me show what it does." Switch to recorded demo. |
| **One agent fails mid-cascade** | Frontend shows partial chain, then nothing | The Auditor catches this. Show: "The Auditor blocked an output -- normally we'd retry but for time let me continue." Skip to next demo beat. |
| **Cascade completes but with wrong numbers** | Visible to presenter (e.g. "0 positions affected") | Don't draw attention. Move quickly to "what if EU" segment to shift focus. |
| **Datadog UI doesn't show traces** | Backup screenshot ready on second monitor | Show the screenshot: "Here's what Datadog normally shows" -- judges still understand the integration. |
| **Luminai iframe doesn't load** | iframe shows error or blank | Skip Luminai segment, go straight to closing pitch. Mention: "Luminai integration is wired but we'll skip for time." |
| **Frontend crashes (white screen)** | Browser shows blank or error | Press Cmd+R / Ctrl+R to reload. If still broken: full pre-recorded video. |
| **Internet drops** | Network icon, browser errors | Switch to phone hotspot. Have it tethered and ready BEFORE going on stage. |
| **ClickHouse Cloud timeout** | Backend logs show timeout errors | Switch `.env` to local, restart backend. Ad-lib for 30s. |
| **All Gemini calls failing** | Backend logs show 429 or auth errors | OpenRouter fallback should kick in automatically -- verify by checking backend logs. |

### The Universal Fallback

If anything seems wrong for more than 10 seconds: cut to pre-recorded video. Narrate over it. Don't lose composure.

```
"Our live system is having a moment -- let me show you the recording we
captured at the start of the day. Same data, same flow."
```

### Post-Failure Recovery

After demo:
- Don't blame anyone, even yourself
- Don't dwell on what went wrong publicly
- During Q&A, redirect to: "What I'd love to show you is X" -- pivot to what worked

---

## 8. Pre-Recorded Backup Videos

Record these AT LEAST 2 hours before the demo. Re-record after any code change.

### Required Recordings

| Video | Length | Purpose | Quality |
|---|---|---|---|
| Full demo flow | 5 min | If everything breaks | 1080p, mic audio clean |
| CFTC cascade only | 30 sec | If just the cascade breaks | 1080p, no audio (you'll narrate live) |
| "What if EU" segment | 45 sec | If the interaction breaks | 1080p, no audio |
| Luminai execution | 30 sec | If Luminai breaks | 1080p, no audio |
| Datadog LLM Obs | 30 sec | If Datadog UI is slow | 1080p, no audio |

### Recording Setup

- **Tool:** OBS Studio (free, cross-platform)
- **Resolution:** 1920x1080
- **Frame rate:** 30fps
- **Audio:** USB mic if available, otherwise laptop mic
- **Mouse:** Highlight cursor (OBS plugin) so judges can follow
- **Browser:** Hide bookmarks bar, close other tabs

### Storage

Save each video in THREE places:
1. Local laptop primary location (`~/demo-recordings/`)
2. Cloud backup (Dropbox / Google Drive)
3. USB stick or phone for absolute worst case

### Naming Convention

```
demo-cftc-cascade-2026-05-25-1430.mp4
demo-full-flow-2026-05-25-1430.mp4
demo-luminai-2026-05-25-1430.mp4
demo-what-if-eu-2026-05-25-1430.mp4
demo-datadog-llmobs-2026-05-25-1430.mp4
```

Date and time so you know which is freshest.

---

## AI Tool Hints

If you're an AI tool implementing tests:

1. **Start with `smoke_test.py`** -- it's the only test that matters Day 1. Get every check passing before moving to other tests.

2. **Unit tests can wait** -- if the smoke test passes and the demo E2E passes, ship it. Add unit tests after demo.

3. **Integration tests need real services** -- they're slow. Run them sparingly. Don't run them in a CI loop.

4. **Never `time.sleep()` in async tests** -- use `await asyncio.sleep()`. Otherwise the event loop deadlocks.

5. **Mock the LLM in unit tests, NOT in integration tests** -- integration tests should exercise real Gemini calls. Otherwise you're just testing your mocks.

6. **The demo E2E test is the spec.** If a code change makes it fail, the change is wrong (not the test).
