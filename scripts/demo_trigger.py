"""
Manually fire pre-staged demo events. Used during the live demo to trigger
the agent cascade visibly.

USAGE:
    python scripts/demo_trigger.py --list
    python scripts/demo_trigger.py --event=cftc_margin_amendment
    python scripts/demo_trigger.py --event=cfpb_bnpl_guidance
    python scripts/demo_trigger.py --event=sec_cyber_disclosure
    python scripts/demo_trigger.py --event=ofac_sanctions_update
    python scripts/demo_trigger.py --event=fincen_aml_update

Each event POSTs to /api/internal/trigger which inserts a fake regulation
into reg_versions, posts a TriggerEvent to the blackboard, and fans out
to all 5 LLM agents. The full cascade fires and streams over WebSocket
to the frontend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

try:
    import httpx
    from rich.console import Console
except ImportError:
    print("Missing deps: pip install httpx rich")
    sys.exit(1)

console = Console()

BACKEND_URL = "http://localhost:8000"


# ════════════════════════════════════════════════════════════════
# Pre-staged demo events (locked content -- do not improvise during demo)
# ════════════════════════════════════════════════════════════════

DEMO_EVENTS: dict[str, dict] = {
    "cftc_margin_amendment": {
        "trigger_type": "new_regulation",
        "regulator": "CFTC",
        "title": "Final Rule: Amendments to Margin Requirements for Uncleared Swaps",
        "summary": (
            "The CFTC has finalized amendments to 17 CFR Part 23 increasing "
            "the initial margin threshold from 6% to 8% of notional for "
            "uncleared interest rate swaps. Effective 60 days from publication. "
            "Affects all swap dealers and major swap participants."
        ),
        "source_url": "https://www.cftc.gov/PressRoom/PressReleases/8000-26",
        "jurisdiction": "us_federal",
        "topics": ["margin_requirements", "uncleared_swaps", "interest_rate_swaps"],
        "effective_date_offset_days": 60,
    },
    "cfpb_bnpl_guidance": {
        "trigger_type": "new_regulation",
        "regulator": "CFPB",
        "title": "Interpretive Rule: Buy Now Pay Later Products and Reg Z",
        "summary": (
            "The CFPB has issued an interpretive rule confirming that Buy Now "
            "Pay Later (BNPL) loans are credit cards under Reg Z. BNPL providers "
            "must now offer dispute and chargeback rights, periodic statements, "
            "and refund processing comparable to traditional credit cards."
        ),
        "source_url": "https://www.consumerfinance.gov/about-us/newsroom/example-bnpl-rule/",
        "jurisdiction": "us_federal",
        "topics": ["bnpl", "reg_z", "consumer_credit", "dispute_rights"],
        "effective_date_offset_days": 90,
    },
    "sec_cyber_disclosure": {
        "trigger_type": "reg_amended",
        "regulator": "SEC",
        "title": "Item 1.05 Material Cybersecurity Incident -- Reduced Window",
        "summary": (
            "The SEC has amended Form 8-K Item 1.05 to reduce the materiality "
            "disclosure window from 4 business days to 3 business days for "
            "registrants in the financial services sector. The amendment "
            "responds to feedback regarding the speed of incident impact."
        ),
        "source_url": "https://www.sec.gov/news/press-release/example-cyber-amendment",
        "jurisdiction": "us_federal",
        "topics": ["cybersecurity", "8-K_disclosure", "material_events"],
        "effective_date_offset_days": 30,
    },
    "ofac_sanctions_update": {
        "trigger_type": "new_regulation",
        "regulator": "OFAC",
        "title": "Specially Designated Nationals List Update -- Country X Entities",
        "summary": (
            "OFAC has added 47 entities and 23 individuals to the SDN list "
            "related to financial flows in Country X. US persons are prohibited "
            "from transactions with these entities. Screening systems must be "
            "updated within 24 hours."
        ),
        "source_url": "https://home.treasury.gov/news/press-releases/example-sdn-update",
        "jurisdiction": "us_federal",
        "topics": ["sanctions", "sdn_list", "ofac", "screening"],
        "effective_date_offset_days": 0,
    },
    "fincen_aml_update": {
        "trigger_type": "new_regulation",
        "regulator": "FinCEN",
        "title": "Customer Due Diligence Rule -- Beneficial Ownership Threshold",
        "summary": (
            "FinCEN has lowered the beneficial ownership reporting threshold "
            "under the CDD Rule from 25% to 10% for fintechs and money services "
            "businesses. New onboarding must comply within 120 days; existing "
            "customer base re-verified within 12 months."
        ),
        "source_url": "https://www.fincen.gov/news/news-releases/example-cdd-update",
        "jurisdiction": "us_federal",
        "topics": ["aml", "beneficial_ownership", "cdd_rule", "kyc"],
        "effective_date_offset_days": 120,
    },
}


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════


def list_events() -> None:
    console.print("[bold]Available demo events:[/bold]\n")
    for key, ev in DEMO_EVENTS.items():
        console.print(f"  [cyan]{key}[/cyan]")
        console.print(f"    Regulator: {ev['regulator']}")
        console.print(f"    Title: {ev['title']}")
        console.print(f"    Effective: T+{ev['effective_date_offset_days']} days\n")


async def fire_event(event_key: str, *, dry_run: bool = False) -> None:
    if event_key not in DEMO_EVENTS:
        console.print(f"[red]Unknown event: {event_key}[/red]")
        console.print(f"Use --list to see available events")
        sys.exit(1)

    event = DEMO_EVENTS[event_key]

    if dry_run:
        console.print(f"[yellow]DRY RUN -- would fire:[/yellow]")
        console.print(json.dumps(event, indent=2))
        return

    console.print(f"[blue]▶ Firing event:[/blue] {event_key}")
    console.print(f"  [dim]{event['title']}[/dim]\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            r = await client.post(
                f"{BACKEND_URL}/api/internal/trigger",
                json=event,
            )
            r.raise_for_status()
            result = r.json()

            trigger_id = result.get("trigger_id")
            console.print(f"[green]✓ Trigger accepted:[/green] {trigger_id}")
            console.print(f"  Watch the cascade in:")
            console.print(f"    [link]http://localhost:5173/chat?trigger={trigger_id}[/link]")
            console.print(f"    [link]http://localhost:5173/dashboard[/link]\n")

        except httpx.HTTPError as e:
            console.print(f"[red]✗ Request failed:[/red] {e}")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fire pre-staged demo events")
    parser.add_argument("--list", action="store_true", help="List available events")
    parser.add_argument("--event", help="Event key to fire")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without firing")
    parser.add_argument("--backend", default=BACKEND_URL, help="Backend URL")
    args = parser.parse_args()

    global BACKEND_URL
    BACKEND_URL = args.backend

    if args.list:
        list_events()
        return

    if not args.event:
        parser.print_help()
        console.print("\n[yellow]Specify --event=<name> or --list[/yellow]")
        sys.exit(1)

    asyncio.run(fire_event(args.event, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
