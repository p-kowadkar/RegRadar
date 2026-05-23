"""
Smoke test -- verifies every integration works end-to-end.

Exits 0 on success, 1 on first failure. Run before every demo attempt.

USAGE:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --check-seed     # also verify seed counts
    python scripts/smoke_test.py --verbose        # full stack traces
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing deps: pip install rich")
    sys.exit(1)


console = Console()


async def run_smoke_tests(check_seed: bool, verbose: bool) -> int:
    results: list[tuple[str, bool, Optional[str]]] = []

    # ─── 1. Env vars ────────────────────────────────────────────
    try:
        from backend.utils import env
        env.validate()
        results.append(("Env vars validated", True, None))
    except Exception as e:
        results.append(("Env vars validated", False, _err(e, verbose)))
        return _report(results)                                 # stop early

    # ─── 2. ClickHouse connection ───────────────────────────────
    try:
        from backend.integrations.clickhouse_client import ClickHouseClient
        client = ClickHouseClient.get_sync()
        version = client.query("SELECT version()").result_rows[0][0]
        results.append(("ClickHouse connected", True, f"v{version}"))
    except Exception as e:
        results.append(("ClickHouse connected", False, _err(e, verbose)))

    # ─── 3. Seed data (optional) ────────────────────────────────
    if check_seed:
        try:
            from backend.integrations.clickhouse_client import ClickHouseClient
            client = ClickHouseClient.get_sync()
            kg = client.query("SELECT COUNT(*) FROM kg_nodes").result_rows[0][0]
            regs = client.query("SELECT COUNT(*) FROM reg_versions").result_rows[0][0]
            derivs = client.query("SELECT COUNT(*) FROM derivatives_portfolio").result_rows[0][0]
            ctrls = client.query("SELECT COUNT(*) FROM controls").result_rows[0][0]
            assert kg >= 100, f"kg_nodes={kg} (expected >=100)"
            assert regs >= 20, f"reg_versions={regs} (expected >=20)"
            assert derivs >= 3000, f"derivatives={derivs} (expected >=3000)"
            assert ctrls >= 8, f"controls={ctrls} (expected >=8)"
            results.append((
                "Seed data loaded", True,
                f"{kg} KG / {regs} regs / {derivs} derivs / {ctrls} ctrls"
            ))
        except Exception as e:
            results.append(("Seed data loaded", False, _err(e, verbose)))

    # ─── 4. Vertex AI / Gemini 3.5 Flash ────────────────────────
    try:
        from backend.integrations.vertex_ai import VertexAIClient
        client = VertexAIClient.get()
        response = await client.generate(
            model="gemini-3.5-flash",
            prompt="Reply with exactly the word OK and nothing else.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response.upper(), f"Got: {response!r}"
        results.append(("Gemini 3.5 Flash works", True, None))
    except Exception as e:
        results.append(("Gemini 3.5 Flash works", False, _err(e, verbose)))

    # ─── 5. Vertex AI / Gemini 3.1 Pro ──────────────────────────
    try:
        from backend.integrations.vertex_ai import VertexAIClient
        client = VertexAIClient.get()
        response = await client.generate(
            model="gemini-3.1-pro",
            prompt="Reply with exactly the word OK and nothing else.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response.upper(), f"Got: {response!r}"
        results.append(("Gemini 3.1 Pro works", True, None))
    except Exception as e:
        results.append(("Gemini 3.1 Pro works", False, _err(e, verbose)))

    # ─── 6. OpenRouter fallback ─────────────────────────────────
    try:
        from backend.integrations.openrouter import OpenRouterClient
        client = OpenRouterClient.get()
        response = await client.generate(
            model="gemini-3.5-flash",
            prompt="Reply with the word OK.",
            max_output_tokens=10,
            agent_id="smoke_test",
        )
        assert "OK" in response.upper(), f"Got: {response!r}"
        results.append(("OpenRouter fallback works", True, None))
    except Exception as e:
        results.append(("OpenRouter fallback works", False, _err(e, verbose)))

    # ─── 7. Nimble ──────────────────────────────────────────────
    try:
        from backend.integrations.nimble import NimbleClient
        client = NimbleClient.get()
        docs = await client.search(query="SEC press release", num_results=2)
        assert len(docs) > 0
        results.append(("Nimble search works", True, f"{len(docs)} results"))
    except Exception as e:
        results.append(("Nimble search works", False, _err(e, verbose)))

    # ─── 8. Firecrawl fallback ──────────────────────────────────
    try:
        from backend.integrations.firecrawl import FirecrawlClient
        client = FirecrawlClient.get()
        doc = await client.scrape_url("https://example.com")
        assert len(doc.content) > 0
        results.append(("Firecrawl fallback works", True, None))
    except Exception as e:
        results.append(("Firecrawl fallback works", False, _err(e, verbose)))

    # ─── 9. Datadog ingest ──────────────────────────────────────
    try:
        from backend.integrations.datadog import DatadogAlerter
        await DatadogAlerter.send_control_breach_alert(
            control_id="CTRL-SMOKE-TEST",
            control_name="Smoke Test (ignore)",
            regulation_title="Smoke test",
            affected_position_count=0,
            notional_exposure_usd=0,
            owner_team="dev",
            severity="info",
        )
        results.append(("Datadog ingest works", True, "check Datadog UI"))
    except Exception as e:
        results.append(("Datadog ingest works", False, _err(e, verbose)))

    # ─── 10. Luminai (optional) ─────────────────────────────────
    try:
        from backend.utils import env as _env
        api_key = _env.get("LUMINAI_API_KEY", default="")
        if not api_key:
            results.append(("Luminai (skipped)", True, "no creds -- fill in at hackathon"))
        else:
            from backend.integrations.luminai import LuminaiClient
            _ = LuminaiClient.get()
            results.append(("Luminai client initialized", True, None))
    except Exception as e:
        results.append(("Luminai client initialized", False, _err(e, verbose)))

    return _report(results)


def _err(exc: Exception, verbose: bool) -> str:
    if verbose:
        return "\n" + traceback.format_exc()
    return f"{type(exc).__name__}: {exc}"


def _report(results: list[tuple[str, bool, Optional[str]]]) -> int:
    table = Table(title="RegRadar Smoke Test Results")
    table.add_column("Check", style="cyan", no_wrap=True)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-seed", action="store_true",
                        help="Also verify seed data is loaded")
    parser.add_argument("--verbose", action="store_true",
                        help="Print full stack traces on failure")
    args = parser.parse_args()

    code = asyncio.run(run_smoke_tests(args.check_seed, args.verbose))
    sys.exit(code)


if __name__ == "__main__":
    main()
