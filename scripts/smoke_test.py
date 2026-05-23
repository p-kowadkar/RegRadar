"""
End-to-end smoke test for the RegRadar stack.

Verifies every external dependency the agents need before a demo.

USAGE:
    python scripts/smoke_test.py                  # run all checks
    python scripts/smoke_test.py --verbose        # full stack traces
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

# Ensure the project root is importable when running this script directly.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing deps: pip install rich")
    sys.exit(1)

console = Console()


async def run_smoke_tests(verbose: bool) -> int:
    results: list[tuple[str, bool, Optional[str]]] = []

    # ─── 1. Env vars ────────────────────────────────────────────
    try:
        for key in (
            "CLICKHOUSE_HOST", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD",
            "NIMBLE_API_KEY",
        ):
            if not os.environ.get(key):
                raise RuntimeError(f"missing required env var: {key}")
        results.append(("Env vars present", True, None))
    except Exception as e:
        results.append(("Env vars present", False, _err(e, verbose)))
        return _report(results)

    # ─── 2. ClickHouse Cloud connection (sync) ──────────────────
    try:
        from backend.integrations.clickhouse_client import get_sync_client
        ch = get_sync_client()
        version = ch.query("SELECT version()").result_rows[0][0]
        n_regs = ch.query("SELECT count() FROM regulations").result_rows[0][0]
        results.append((
            "ClickHouse Cloud reachable", True,
            f"v{version} / {n_regs} regulations",
        ))
    except Exception as e:
        results.append(("ClickHouse Cloud reachable", False, _err(e, verbose)))

    # ─── 3. ClickHouse Cloud connection (async) ─────────────────
    try:
        from backend.integrations.clickhouse_client import get_client
        ch = await get_client()
        rows = (await ch.query("SELECT 1")).result_rows
        assert rows[0][0] == 1
        results.append(("ClickHouse async client", True, None))
    except Exception as e:
        results.append(("ClickHouse async client", False, _err(e, verbose)))

    # ─── 4. Nimble extract ──────────────────────────────────────
    try:
        from backend.integrations.nimble import scrape_url
        doc = await scrape_url("https://example.com")
        assert len(doc.content_markdown) > 0
        results.append((
            "Nimble extract", True,
            f"{len(doc.content_markdown)} chars markdown",
        ))
    except Exception as e:
        results.append(("Nimble extract", False, _err(e, verbose)))

    # ─── 5. Firecrawl fallback (only if API key present) ────────
    if os.environ.get("FIRECRAWL_API_KEY"):
        try:
            from backend.integrations.firecrawl import scrape_url as fc_scrape
            doc = await fc_scrape("https://example.com")
            assert len(doc.content_markdown) > 0
            results.append(("Firecrawl fallback", True, None))
        except Exception as e:
            results.append(("Firecrawl fallback", False, _err(e, verbose)))
    else:
        results.append(("Firecrawl fallback (skipped)", True, "no FIRECRAWL_API_KEY"))

    # ─── 6. Vertex AI / Gemini (only if creds present) ──────────
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            from backend.integrations.vertex_ai import vertex_model
            model = vertex_model("gemini-2.5-flash")
            results.append((
                "Vertex AI provider", True,
                f"model={getattr(model, 'model_name', 'gemini-2.5-flash')}",
            ))
        except Exception as e:
            results.append(("Vertex AI provider", False, _err(e, verbose)))
    else:
        results.append(("Vertex AI (skipped)", True, "no GOOGLE_CLOUD_PROJECT"))

    # ─── 7. Lapdog local agent (optional) ───────────────────────
    try:
        import httpx
        with httpx.Client(timeout=2) as c:
            r = c.get("http://127.0.0.1:8126/info")
        results.append((
            "Lapdog local agent",
            r.status_code == 200,
            "running" if r.status_code == 200 else f"http {r.status_code}",
        ))
    except Exception:
        results.append((
            "Lapdog local agent (optional)", True,
            "not running (start with: lapdog start)",
        ))

    return _report(results)


def _err(exc: Exception, verbose: bool) -> str:
    if verbose:
        return "\n" + traceback.format_exc()
    return f"{type(exc).__name__}: {exc}"


def _report(results: list[tuple[str, bool, Optional[str]]]) -> int:
    table = Table(title="RegRadar Smoke Test")
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Detail", style="dim")

    all_passed = True
    for check, passed, detail in results:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        if not passed:
            all_passed = False
        table.add_row(check, status, detail or "")

    console.print(table)
    if all_passed:
        console.print("\n[bold green]All checks passed.[/bold green]")
        return 0
    console.print("\n[bold red]Some checks failed.[/bold red]")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="full tracebacks")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_smoke_tests(args.verbose)))


if __name__ == "__main__":
    main()
