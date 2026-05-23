# TESTING.md

How to verify everything works -- before the demo, during the demo, and what to do if it doesn't.

This file is read TWICE. Once during dev to write the tests. Once at T-24 hours to verify nothing's broken.

---

## 1. Philosophy

For hackathon scope, we prioritize:

1. **Smoke tests** confirming every integration works -- run before every demo attempt
2. **End-to-end demo test** running the full schema_enrichment_fcra cascade -- run 3+ times before pitch
3. **Failure recovery rehearsed** so we don't panic on stage

We do NOT prioritize:
- Code coverage targets
- Property-based testing
- Load testing
- Mutation testing
- Snapshot testing of UI

If a test isn't directly testing "will this work on stage tomorrow," skip it.

---

## 2. Smoke Tests

`scripts/smoke_test.py` is the source of truth for "is everything working." Run it before EVERY demo attempt.

```python
# scripts/smoke_test.py
"""
Smoke-test every integration and seed-data invariant.
Run after setup, before demo, and before any push to main.
"""

import asyncio
import sys
from rich.console import Console
from rich.table import Table

console = Console()


async def smoke_test():
    results = []

    # 1. Env vars validated
    try:
        from backend.utils import env
        env.validate()
        results.append(("Env vars validated", True, None))
    except Exception as e:
        results.append(("Env vars validated", False, str(e)))
        return _report(results)

    # 2. ClickHouse + version >= 25.8
    try:
        from backend.integrations.clickhouse_client import get_client
        client = await get_client()
        version = (await client.query("SELECT version()")).result_rows[0][0]
        major = int(version.split(".")[0])
        minor = int(version.split(".")[1])
        ok = (major, minor) >= (25, 8)
        results.append(("ClickHouse >= 25.8", ok, f"v{version}"))
    except Exception as e:
        results.append(("ClickHouse >= 25.8", False, str(e)))

    # 3. Seed data loaded with expected distributions
    try:
        client = await get_client()
        accounts = (await client.query("SELECT count() FROM credit_card_accounts")).result_rows[0][0]
        controls = (await client.query("SELECT count() FROM controls")).result_rows[0][0]
        regs = (await client.query("SELECT count() FROM reg_versions")).result_rows[0][0]
        conds = (await client.query("SELECT count() FROM compliance_conditions")).result_rows[0][0]
        embeddings = (await client.query("SELECT count() FROM policy_embeddings")).result_rows[0][0]
        ok = (
            accounts >= 50000
            and controls == 6
            and regs == 2
            and conds >= 6
            and embeddings == 4
        )
        detail = f"{accounts} acct, {controls} ctrl, {regs} reg, {conds} cond, {embeddings} emb"
        results.append(("Seed data correct", ok, detail))
    except Exception as e:
        results.append(("Seed data correct", False, str(e)))

    # 4. Expected breach distributions match seed tuning
    try:
        client = await get_client()
        bureau_mismatch = (
            await client.query("SELECT count() FROM credit_card_accounts WHERE bureau_reported = true AND bureau_reported_status != payment_status")
        ).result_rows[0][0]
        active_disputes = (
            await client.query("SELECT count() FROM credit_card_accounts WHERE dispute_filed = true")
        ).result_rows[0][0]
        # Allow +/- 20% drift from tuning targets
        ok = 1200 <= bureau_mismatch <= 1800 and 320 <= active_disputes <= 480
        results.append((
            "Seed distributions in range",
            ok,
            f"bureau_mismatch={bureau_mismatch} (target ~1500), disputes={active_disputes} (target ~400)"
        ))
    except Exception as e:
        results.append(("Seed distributions in range", False, str(e)))

    # 5. Vertex AI Gemini 3.5 Flash works
    try:
        from backend.integrations.vertex_ai import _get_genai_client
        client = _get_genai_client()
        r = await client.aio.models.generate_content(
            model="gemini-3.5-flash",
            contents="Reply with exactly the word OK.",
        )
        ok = "OK" in r.text
        results.append(("Gemini 3.5 Flash", ok, None))
    except Exception as e:
        results.append(("Gemini 3.5 Flash", False, str(e)))

    # 6. Vertex AI Gemini 3.1 Pro works
    try:
        from backend.integrations.vertex_ai import _get_genai_client
        client = _get_genai_client()
        r = await client.aio.models.generate_content(
            model="gemini-3.1-pro",
            contents="Reply with exactly the word OK.",
        )
        ok = "OK" in r.text
        results.append(("Gemini 3.1 Pro", ok, None))
    except Exception as e:
        results.append(("Gemini 3.1 Pro", False, str(e)))

    # 7. gemini-embedding-001 works at output_dim=768
    try:
        from backend.integrations.vertex_ai import embed_text
        vec = await embed_text(text="The quick brown fox", output_dim=768)
        ok = len(vec) == 768
        results.append(("gemini-embedding-001 (768d)", ok, f"len={len(vec)}"))
    except Exception as e:
        results.append(("gemini-embedding-001 (768d)", False, str(e)))

    # 8. Pydantic AI Vertex provider builds
    try:
        from backend.integrations.vertex_ai import vertex_model
        m = vertex_model("gemini-3.5-flash")
        ok = m is not None
        results.append(("Pydantic AI Vertex provider", ok, type(m).__name__))
    except Exception as e:
        results.append(("Pydantic AI Vertex provider", False, str(e)))

    # 9. Check Grounding API works
    try:
        from backend.integrations.vertex_ai import check_grounding
        result = await check_grounding(
            claim="Section 605 limits stale data reporting to 7 years.",
            sources=[
                "Except as authorized under subsection (b), no consumer reporting agency may make any consumer report containing accounts placed for collection or charged to profit and loss which antedate the report by more than seven years."
            ],
        )
        ok = result.is_grounded and result.overall_confidence > 0.7
        results.append(("Check Grounding", ok, f"confidence={result.overall_confidence:.2f}"))
    except Exception as e:
        results.append(("Check Grounding", False, str(e)))

    # 10. Nimble search works
    try:
        from backend.integrations.nimble import search
        results_nimble = await search(query="CFPB credit card rule 2026", num_results=2)
        ok = len(results_nimble) >= 1
        results.append(("Nimble Web Search Agents", ok, f"{len(results_nimble)} results"))
    except Exception as e:
        results.append(("Nimble Web Search Agents", False, str(e)))

    # 11. Firecrawl fallback works
    try:
        from backend.integrations.firecrawl import scrape_url
        doc = await scrape_url("https://example.com")
        ok = len(doc.content_markdown) > 0
        results.append(("Firecrawl fallback", ok, None))
    except Exception as e:
        results.append(("Firecrawl fallback", False, str(e)))

    # 12. Senso publish (smoke -- does NOT publish, just verifies ingest works)
    try:
        from backend.integrations.senso import ingest_content
        content_id = await ingest_content(
            title="Smoke Test (ignore)",
            body_markdown="This is a smoke test. Please ignore.",
            tags=["smoke_test"],
        )
        ok = content_id is not None
        results.append(("Senso ingest", ok, f"id={content_id}"))
    except Exception as e:
        results.append(("Senso ingest", False, str(e)))

    # 13. Datadog event ingest works
    try:
        from backend.integrations.datadog import DatadogAlerter
        await DatadogAlerter.send_control_breach_alert(
            control_id="CTRL-SMOKE-TEST",
            control_name="Smoke Test (ignore)",
            regulation_section="N/A",
            affected_account_count=0,
            affected_balance_usd=0,
            owner_team="dev",
            severity="info",
        )
        results.append(("Datadog event ingest", True, "check Datadog UI for event"))
    except Exception as e:
        results.append(("Datadog event ingest", False, str(e)))

    # 14. x402 facilitator reachable
    try:
        import httpx
        import os
        r = await httpx.AsyncClient().get(
            os.environ.get("X402_FACILITATOR_URL", "https://x402.org/facilitator") + "/health",
            timeout=10,
        )
        ok = r.status_code == 200
        results.append(("x402 facilitator reachable", ok, f"status={r.status_code}"))
    except Exception as e:
        results.append(("x402 facilitator reachable", False, str(e)))

    # 15. ClickHouse HNSW index exists on policy_embeddings
    try:
        client = await get_client()
        rows = (await client.query("SELECT count() FROM system.data_skipping_indices WHERE table = 'policy_embeddings' AND type LIKE '%vector_similarity%'")).result_rows
        ok = rows[0][0] >= 1
        results.append(("ClickHouse HNSW index on policy_embeddings", ok, None))
    except Exception as e:
        results.append(("ClickHouse HNSW index on policy_embeddings", False, str(e)))

    return _report(results)


def _report(results):
    table = Table(title="RegRadar Smoke Test Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Detail", style="dim")

    all_passed = True
    for check, passed, detail in results:
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        if not passed:
            all_passed = False
        table.add_row(check, status, detail or "")

    console.print(table)
    if all_passed:
        console.print("\n[bold green]All checks passed. Ready to demo.[/bold green]")
        return 0
    console.print("\n[bold red]Some checks failed. Fix before continuing.[/bold red]")
    return 1


if __name__ == "__main__":
    code = asyncio.run(smoke_test())
    sys.exit(code)
```

### When To Run

- After initial setup
- After any `.env` change
- At T-2 hours before demo
- After every `git pull`
- Whenever something feels wrong

---

## 3. Unit Tests

For hackathon scope, write unit tests ONLY for these high-risk modules:

| Module | Why | Test File |
|---|---|---|
| `backend/data/repositories.py` | Wrong query = wrong demo | `tests/test_repositories.py` |
| `backend/utils/env.py` | Validation must be strict | `tests/test_env.py` |
| `backend/agents/auditor.py` | Critical -- this is what blocks hallucinations | `tests/test_auditor.py` |

Skip unit tests for everything else. Integration + smoke tests cover them.

### Example: Auditor blocks fabrication

```python
# tests/test_auditor.py
import pytest
from backend.agents.auditor import run_auditor
from backend.data.models import ImpactReport, ControlUpdate


@pytest.mark.asyncio
async def test_auditor_blocks_fabricated_dollar_amount():
    """The Auditor must reject an ImpactReport claiming a wrong fine amount."""
    fabricated = ImpactReport(
        trigger_id="test_fabrication",
        affected_controls=[],
        classifications={},
        sample_account_ids=[],
        total_breach_count=1247,
        total_at_risk_count=0,
        total_balance_at_risk_usd=1_975_000,
        citations=["FCRA Section 605"],
        suggested_remediation=["Citi was fined $2,500,000 for this exact violation."],   # fabricated!
        reasoning="...",
    )
    verdict = await run_auditor(fabricated)
    assert verdict.verdict == "rejected"
    assert any("2,500,000" in r or "$2.5M" in r for r in verdict.rejection_reasons)
    assert verdict.safe_to_publish is False


@pytest.mark.asyncio
async def test_auditor_approves_grounded_claim():
    """The Auditor must approve a claim that's actually in the source regulation."""
    grounded = ImpactReport(
        trigger_id="test_grounded",
        affected_controls=[
            ControlUpdate(
                control_id="CTRL-FCRA-STALE-DATA",
                new_status="FAILING",
                affected_account_count=1247,
                affected_balance_usd=1_975_000,
                rationale="Section 605 prohibits reporting accounts more than 7 years old.",
                related_regulation_section="15 USC 1681c (FCRA Section 605)",
            )
        ],
        classifications={},
        sample_account_ids=["acct_001", "acct_002"],
        total_breach_count=1247,
        total_at_risk_count=0,
        total_balance_at_risk_usd=1_975_000,
        citations=["15 USC 1681c (FCRA Section 605)"],
        suggested_remediation=["Stop reporting accounts with original_delinquency_date > 7 years."],
        reasoning="Each of 1,247 accounts has original_delinquency_date > 7 years and bureau_reported = true.",
    )
    verdict = await run_auditor(grounded)
    assert verdict.verdict in ("approved", "approved_with_warnings")
    assert verdict.overall_confidence >= 0.65
    assert verdict.safe_to_publish is True
```

---

## 4. Integration Tests

| Test | What It Verifies | File |
|---|---|---|
| `test_schema_enrichment_cascade` | Full headline demo arc end-to-end | `tests/integration/test_schema_enrichment.py` |
| `test_dispute_filed_cross_trigger` | TILA + FCRA fire in parallel from one event | `tests/integration/test_dispute_cross.py` |
| `test_nimble_failover_to_firecrawl` | When Nimble fails, Firecrawl picks up | `tests/integration/test_scraping_failover.py` |
| `test_gemini_failover_to_openrouter` | When Vertex AI 429s, OpenRouter picks up | `tests/integration/test_llm_failover.py` |
| `test_senso_publish_loop` | Auditor approves → Senso publishes → URL returned | `tests/integration/test_senso_publish.py` |
| `test_control_breach_to_datadog` | Auditor approves → Datadog alert fires | `tests/integration/test_control_alerting.py` |
| `test_x402_402_then_200` | Compliance brief returns 402, then 200 after payment | `tests/integration/test_x402.py` |
| `test_monitoring_sweep_zero_llm` | Monitoring agent calls zero LLM tokens during sweep | `tests/integration/test_monitoring_zero_llm.py` |

### Example: Schema Enrichment Cascade

```python
# tests/integration/test_schema_enrichment.py
import pytest
import httpx


@pytest.mark.asyncio
@pytest.mark.integration
async def test_schema_enrichment_completes_in_under_10s():
    """The headline demo cascade must finish in <10s end-to-end."""
    import time

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30) as http:
        # Fire trigger
        r = await http.post("/api/internal/scenarios/schema_enrichment_fcra")
        assert r.status_code == 200
        trigger_id = r.json()["data"]["trigger_id"]

        # Poll for completion
        start = time.time()
        for _ in range(60):
            r = await http.get(f"/api/triggers/{trigger_id}")
            data = r.json()["data"]
            if data.get("auditor_verdict") and data.get("published_brief"):
                break
            await asyncio.sleep(0.2)
        elapsed = time.time() - start

        assert elapsed < 10.0, f"Cascade took {elapsed:.1f}s, must be < 10s"

        # Verify each stage
        assert data["impact_report"]["total_breach_count"] > 1000           # ~1247
        assert data["impact_report"]["total_balance_at_risk_usd"] > 0
        assert "CTRL-FCRA-STALE-DATA" in [c["control_id"] for c in data["impact_report"]["affected_controls"]]

        assert data["auditor_verdict"]["verdict"] in ("approved", "approved_with_warnings")
        assert data["auditor_verdict"]["overall_confidence"] >= 0.7

        assert data["published_brief"]["cited_md_url"].startswith("https://cited.md/regradar/")

        assert len(data["dd_alerts"]) >= 1
        assert data["dd_alerts"][0]["control_id"] == "CTRL-FCRA-STALE-DATA"
```

Run with:

```bash
pytest tests/integration/ -v -m integration
```

---

## 5. End-to-End Demo Test

`scripts/demo_e2e_test.py` runs the same flow the demo will run. Use this 3+ times the day before.

```python
# scripts/demo_e2e_test.py
"""
Execute the full demo arc non-interactively.
Run 3+ times the day before. Once at T-30 minutes (with --quiet).
"""

import asyncio
import time
import httpx
from rich.console import Console

console = Console()


async def main(quiet: bool = False):
    log = (lambda s: None) if quiet else console.print

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60) as http:
        # Health
        assert (await http.get("/api/health")).status_code == 200
        log("[green]✓[/green] Backend healthy")

        # Integration smoke
        h = (await http.get("/api/health/integrations")).json()["data"]
        bad = [k for k, v in h.items() if v.get("status") != "ok"]
        assert not bad, f"Integrations not ok: {bad}"
        log("[green]✓[/green] All integrations ok")

        # Dashboard
        controls = (await http.get("/api/controls")).json()["data"]
        assert len(controls["controls"]) == 6
        log(f"[green]✓[/green] 6 controls visible")

        # SCENARIO 1: schema enrichment headline
        start = time.time()
        r = await http.post("/api/internal/scenarios/schema_enrichment_fcra")
        trigger_id = r.json()["data"]["trigger_id"]
        log(f"[blue]▶[/blue] Fired schema_enrichment_fcra: {trigger_id}")

        for _ in range(50):
            data = (await http.get(f"/api/triggers/{trigger_id}")).json()["data"]
            if data.get("auditor_verdict"):
                break
            await asyncio.sleep(0.2)
        elapsed = time.time() - start

        breach = data["impact_report"]["total_breach_count"]
        assert breach > 1000, f"Expected >1000 breaches, got {breach}"
        assert elapsed < 10, f"Cascade took {elapsed:.1f}s"
        log(f"[green]✓[/green] Schema cascade: {breach} breaches in {elapsed:.1f}s")

        # SCENARIO 2: dispute_filed cross-trigger
        start = time.time()
        r = await http.post("/api/internal/scenarios/dispute_filed_cross_trigger")
        trigger_id = r.json()["data"]["trigger_id"]

        for _ in range(50):
            data = (await http.get(f"/api/triggers/{trigger_id}")).json()["data"]
            if data.get("auditor_verdict"):
                break
            await asyncio.sleep(0.2)
        elapsed = time.time() - start

        affected = [c["control_id"] for c in data["impact_report"]["affected_controls"]]
        assert "CTRL-TILA-DISPUTE-RESOLUTION" in affected
        assert "CTRL-FCRA-DISPUTE-FLAG" in affected
        log(f"[green]✓[/green] Dispute cascade: 2 controls in {elapsed:.1f}s")

        # x402: 402 then 200
        r = await http.get("/api/compliance-brief/fcra", follow_redirects=False)
        assert r.status_code == 402, f"Expected 402 Payment Required, got {r.status_code}"
        log("[green]✓[/green] x402 returns 402 without payment")

        # (Skipping actual x402-curl payment in this test; manually verify in demo)

    log("\n[bold green]Full demo E2E passed[/bold green]")


if __name__ == "__main__":
    import sys
    quiet = "--quiet" in sys.argv
    asyncio.run(main(quiet=quiet))
```

Run this:
- 3+ times the day before
- Once at T-30 minutes before stage (with `--quiet`)

---

## 6. Pre-Demo Run-Through

Do this 3 times back-to-back. If any iteration fails or feels rough, do a 4th.

- [ ] Frontend loads (no errors in console)
- [ ] Sidebar nav works (Dashboard / Controls / Triggers / Briefs / Regulations / Demo)
- [ ] Dashboard: 4 KPI cards show real numbers
- [ ] Dashboard: 4 agent cards visible (Policy Crawler, Impact Analysis, Auditor, Monitoring) with right activation modes
- [ ] Dashboard: 6 control cards visible (3 TILA + 3 FCRA)
- [ ] Controls view: each control shows status, breach count, owner team
- [ ] Click into a control: history + check_sql visible
- [ ] Regulations view: 2 regulations (TILA, FCRA)
- [ ] Click into FCRA: 4 compliance conditions extracted
- [ ] Open Demo control panel
- [ ] Fire `schema_enrichment_fcra` -- chain runs end-to-end in UI < 10s
- [ ] CTRL-FCRA-STALE-DATA flips PASSING → FAILING with ~1247 breach count
- [ ] cited.md URL appears in TriggerDetail and is clickable
- [ ] Datadog alert appears in Datadog UI (with brief URL in alert body)
- [ ] Fire `dispute_filed_cross_trigger` -- TWO controls move to AT_RISK
- [ ] Tab to Datadog AI Agent Console -- chain visible with agent nodes
- [ ] Terminal: `curl -i http://localhost:8000/api/compliance-brief/fcra` returns 402
- [ ] All clear: no error toasts, no console errors, no stale UI states

### What Each Team Member Watches For

| Person | Watches For | When |
|---|---|---|
| Pranav (presenter) | UX flow, narrative timing | Throughout |
| Backend dev | Server logs scrolling clean | Continuously |
| Frontend dev | Browser console errors | Continuously |
| Fourth teammate | Datadog UI, Nimble credits, Senso quota | Continuously |

---

## 7. Failure Recovery Procedures

Stage failures are inevitable. Prepared > improvised.

| Failure Mode | Detection | Recovery |
|---|---|---|
| **Cascade doesn't start** | Trigger fired, no WS update in 3s | "Our agent system seems slow -- let me show what it does." Cut to recorded demo. |
| **Impact Analysis fails** | Auditor never approves | "The Auditor blocked an output -- normally we'd retry; for time, let me continue." Skip to next beat. |
| **Wrong breach count** | Visible to presenter | Don't acknowledge. Move quickly to dispute_filed beat to shift focus. |
| **Datadog UI doesn't load** | Backup screenshot ready | Show the screenshot: "Here's what Datadog normally shows." |
| **Senso publish fails** | No cited.md URL | "We'd normally publish here -- here's an earlier publish [show pre-fetched cited.md URL in tab]" |
| **x402 curl returns wrong status** | Terminal output | Skip the curl, mention briefly: "And our briefs are x402-gated for monetization." |
| **Frontend crashes** | White screen | Cmd+R / Ctrl+R to reload. If still broken: pre-recorded video. |
| **Internet drops** | Browser errors | Switch to phone hotspot. If still down: pre-recorded video, narrate over. |
| **ClickHouse Cloud timeout** | Backend logs show timeout | Switch `.env` to local, restart backend. Ad-lib for 30s. |
| **All Gemini calls 429** | Backend logs | OpenRouter fallback should auto-kick-in -- verify in logs. |

### The Universal Fallback

If anything is wrong for >10 seconds: cut to pre-recorded video. Narrate. Don't lose composure.

> "Our live system is having a moment -- let me show you the recording we captured an hour ago. Same data, same flow."

---

## 8. Pre-Recorded Backup Videos

Record at LEAST 2 hours before the demo. Re-record after any code change.

| Video | Length | Purpose |
|---|---|---|
| Full demo flow | 3 min | Everything breaks |
| schema_enrichment_fcra cascade | 30s | Headline beat alone |
| dispute_filed cascade | 20s | Secondary beat alone |
| x402 curl flow | 15s | Closing beat alone |
| Datadog AI Agent Console | 20s | If Datadog UI is slow |

Save each in THREE places:
1. Laptop `~/demo-recordings/`
2. Cloud (Dropbox / Google Drive)
3. USB stick

### Naming

```
demo-full-2026-05-23-0900.mp4
demo-schema-enrichment-2026-05-23-0900.mp4
demo-dispute-cross-2026-05-23-0900.mp4
demo-x402-2026-05-23-0900.mp4
demo-datadog-2026-05-23-0900.mp4
```

---

## AI Tool Hints

1. **`smoke_test.py` is what matters Day 1.** Get every check passing before writing other tests.

2. **Unit tests can wait** -- if smoke + demo E2E pass, ship it.

3. **Never `time.sleep()` in async tests.** Use `await asyncio.sleep()`.

4. **Mock the LLM in unit tests, NOT in integration tests.** Integration tests need real Gemini calls to test real failure modes.

5. **The demo E2E test is the spec.** If a code change breaks it, the code is wrong (not the test).

6. **For the Auditor test specifically:** seed the test ImpactReport with one obvious hallucination (wrong fine amount, fabricated case citation). The Auditor must reject. If it approves, fix the prompt or grounding logic immediately.
