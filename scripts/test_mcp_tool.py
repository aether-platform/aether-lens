import asyncio

from aether_lens.client.mcp.server import _run_pipeline_impl


async def main():
    print("Triggering pipeline via MCP tool implementation...")
    # target_dir, strategy, browser_url
    result = await _run_pipeline_impl(
        target_dir="example/astro", strategy="auto", browser_url=None
    )
    print("\nMCP Tool Result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
