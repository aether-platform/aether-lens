import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))


async def main():
    target_dir = "example/astro"
    print(f"--- Testing History for {target_dir} ---")
    from aether_lens.client.mcp.server import get_pipeline_history as hist_tool

    result = await hist_tool.run({"target_dir": target_dir, "limit": 3})
    # FastMCP ToolResult.content is a list of TextContent objects or similar
    # In recent FastMCP, it's often a list of content parts.
    print(f"History: {result.content}")

    print(f"\n--- Testing Latest Insight for {target_dir} ---")
    from aether_lens.client.mcp.server import get_latest_insight as insight_tool

    result = await insight_tool.run({"target_dir": target_dir})
    print(f"Insight: {result.content}")

    print(f"\n--- Testing Allure Summary for {target_dir} ---")
    from aether_lens.client.mcp.server import get_allure_summary as summary_tool

    result = await summary_tool.run({"target_dir": target_dir})
    print(f"Summary: {result.content}")


if __name__ == "__main__":
    asyncio.run(main())
