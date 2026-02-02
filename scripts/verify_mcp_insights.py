import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from aether_lens.client.mcp.server import (
    get_allure_results,
    get_latest_insight,
    get_pipeline_history,
)


async def main():
    target_dir = "example/astro"
    print(f"--- Testing History for {target_dir} ---")
    history = await get_pipeline_history(target_dir, limit=3)
    print(f"History items: {len(history)}")
    for item in history:
        print(f" - {item['filename']} ({item['test_count']} tests)")

    print(f"\n--- Testing Latest Insight for {target_dir} ---")
    insight = await get_latest_insight(target_dir)
    if isinstance(insight, dict):
        print(f"Session ID: {insight.get('session_id')}")
        print(f"Result count: {len(insight.get('results', []))}")
    else:
        print(f"Insight: {insight}")

    print(f"\n--- Testing Allure Results for {target_dir} ---")
    allure = await get_allure_results(target_dir)
    if isinstance(allure, list):
        print(f"Allure items: {len(allure)}")
    else:
        print(f"Allure: {allure}")


if __name__ == "__main__":
    asyncio.run(main())
