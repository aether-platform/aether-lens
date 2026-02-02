import json
from pathlib import Path

import logfire
from dependency_injector.wiring import Provide, inject
from fastmcp import FastMCP

from aether_lens.core.containers import Container
from aether_lens.core.planning.ai import run_analysis

logfire.configure(send_to_logfire="if-token-present")
logfire.instrument_pydantic()

# Initialize container for MCP process
Container.validate_environment()
container = Container()

mcp = FastMCP("Aether Lens")


@mcp.tool()
async def init_lens(
    target_dir: str = ".",
    strategy: str = "auto",
    browser_strategy: str = "docker",
    allure_strategy: str = "managed",
):
    """
    Initialize Aether Lens configuration for a project (Non-interactive).

    :param target_dir: The directory to initialize.
    :param strategy: Default analysis strategy (auto, frontend, backend, microservice, custom).
    :param browser_strategy: local, docker, kubernetes, or inpod.
    :param allure_strategy: managed, external, or none.
    """
    config_path = Path(target_dir) / "aether-lens.config.json"

    default_config = {
        "strategy": strategy,
        "custom_instruction": "",
        "browser_strategy": browser_strategy,
        "allure_strategy": allure_strategy,
        "dev_loop": {
            "browser_targets": ["desktop", "tablet", "mobile"],
            "debounce_seconds": 2,
        },
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(default_config, f, indent=2)

    return f"Successfully generated: {config_path}"


@inject
async def _get_vibe_insight_impl(
    target_dir: str,
    strategy: str,
    execution_service=Provide[Container.execution_service],
):
    # execution_service.get_git_diff is now async
    diff = await execution_service.get_git_diff(target_dir)
    if not diff:
        return "No changes detected."

    analysis = run_analysis(diff, context="mcp-agent", strategy=strategy)
    return analysis


@mcp.tool()
async def get_vibe_insight(target_dir: str = ".", strategy: str = "auto"):
    """
    Get AI-powered vibe insight (analysis only) for the current changes.

    :param target_dir: The directory to analyze.
    :param strategy: Analysis strategy to use.
    """
    return await _get_vibe_insight_impl(target_dir, strategy)


@inject
async def _run_pipeline_impl(
    target_dir: str,
    strategy: str,
    browser_url: str,
    execution_service=Provide[Container.execution_service],
):
    target_dir = str(Path(target_dir).resolve())
    return await execution_service.run_pipeline(
        target_dir=target_dir,
        browser_url=browser_url,
        context="mcp",
        strategy=strategy,
        use_tui=False,
    )


@mcp.tool()
async def run_pipeline(
    target_dir: str = ".",
    strategy: str = "auto",
    browser_url: str = None,
) -> str:
    """Run Aether Lens test pipeline on a target directory."""
    return await _run_pipeline_impl(target_dir, strategy, browser_url)


@mcp.tool()
@inject
async def start_lens_loop(
    target_dir: str,
    pod_name: str,
    namespace: str = "aether-system",
    remote_path: str = "/app/project",
    browser_strategy: str = "inpod",
    browser_url: str = None,
    execution_service=Provide[Container.execution_service],
):
    """
    Start the local Lens Loop daemon for a directory (Non-blocking).
    This will watch for local changes in the background.
    """
    await execution_service.start_loop(
        target_dir=target_dir,
        pod_name=pod_name,
        namespace=namespace,
        remote_path=remote_path,
        browser_strategy=browser_strategy,
        browser_url=browser_url,
    )
    return f"Lens Loop started in background for {target_dir} targeting {pod_name}."


@mcp.tool()
@inject
def stop_lens_loop(
    target_dir: str, execution_service=Provide[Container.execution_service]
):
    """
    Stop the active Lens Loop daemon for a directory.
    """
    if execution_service.stop_dev_loop(target_dir):
        return f"Lens Loop stopped for {target_dir}."
    else:
        return f"No active Lens Loop found for {target_dir}."


@inject
async def _check_prerequisites_impl(
    target_dir: str,
    check_service=Provide[Container.check_service],
):
    check_service.verbose = True
    results = await check_service.check_prerequisites(target_dir)

    if results["valid"]:
        return f"Checks Passed: {results}"
    else:
        return f"Checks Failed: {results}"


@mcp.tool()
async def check_prerequisites(target_dir: str = "."):
    """
    Validate environment prerequisites and configuration integrity.
    Checks config schema, tool availability (Docker, Node, etc.), and reports status.

    :param target_dir: The directory to check.
    """
    return await _check_prerequisites_impl(target_dir)


# Wire the container after all functions are defined so @inject picks them up
container.wire(
    modules=[
        "aether_lens.daemon.controller.execution",
        "aether_lens.daemon.controller.watcher",
        "aether_lens.daemon.loop_daemon",
        "aether_lens.client.mcp.server",
        "__main__",
    ]
)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
