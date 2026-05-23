"""Run crawler on just REG-005 (FCRA Section 605) and print the result.

Usage:
    python -m scripts.test_crawler
"""

import asyncio

from backend.utils.env import validate
from backend.utils.logging import configure_logging


async def main() -> None:
    configure_logging()
    validate()

    from backend.agents.policy_crawler import crawl_one

    result = await crawl_one("REG-005")
    if result:
        print(f"change_type:  {result.change_type}")
        print(f"material:     {result.is_material_change}")
        print(f"summary:      {result.change_summary}")
        print(f"new_version:  {result.new_version}")
        print(f"excerpt:      {result.relevant_excerpt[:300]}")
    else:
        # Scrape failed entirely -- check what Nimble + Firecrawl returned
        print("Crawl failed — check logs above for scrape error details")


asyncio.run(main())
