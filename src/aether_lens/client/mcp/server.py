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
        interactive=False,
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
async def watch_project(
    target_dir: str = ".",
    strategy: str = "auto",
    orchestrator=Provide[Container.orchestrator],
    execution_service=Provide[Container.execution_service],
):
    """
    Start watching for file changes and trigger the pipeline automatically (Non-blocking).

    :param target_dir: The directory to watch.
    :param strategy: AI analysis strategy to use.
    """
    await execution_service.run_pipeline(
        target_dir=target_dir, strategy=strategy, interactive=False, auto_watch=True
    )
    return f"Pipeline execution started for {target_dir} with watch mode enabled."


@mcp.tool()
@inject
async def start_lens_loop(
    target_dir: str,
    pod_name: str,
    namespace: str = "aether-system",
    remote_path: str = "/app/project",
    browser_strategy: str = "inpod",
    browser_url: str = None,
    orchestrator=Provide[Container.orchestrator],
):
    """
    Start the local Lens Loop daemon for a directory (Non-blocking).
    This will watch for local changes in the background and sync to remote.
    """
    await orchestrator.start_loop(
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
async def get_pipeline_history(target_dir: str = ".", limit: int = 5):
    """
    Get the history of recent pipeline runs.

    :param target_dir: The directory to check.
    :param limit: Number of recent runs to return.
    """
    history_dir = Path(target_dir) / ".aether" / "history"
    if not history_dir.exists():
        return "No history found for this project."

    files = sorted(history_dir.glob("run_*.json"), reverse=True)
    results = []
    for f in files[:limit]:
        try:
            with open(f, "r") as f_in:
                data = json.load(f_in)
                # Just return summary to avoid huge output
                results.append(
                    {
                        "filename": f.name,
                        "timestamp": data.get("timestamp"),
                        "strategy": data.get("strategy"),
                        "test_count": len(data.get("results", [])),
                    }
                )
        except Exception:
            continue

    return results


@mcp.tool()
async def get_latest_insight(target_dir: str = "."):
    """
    Get detailed insights and scores from the latest pipeline run.
    """
    latest_path = Path(target_dir) / ".aether" / "history" / "latest.json"
    if not latest_path.exists():
        return "No recent results found. Run the pipeline first."

    try:
        with open(latest_path, "r") as f:
            data = json.load(f)
            return data
    except Exception as e:
        return f"Error reading results: {e}"


@mcp.tool()
async def get_allure_results(target_dir: str = "."):
    """
    Get Allure-compatible test results from the .aether/allure-results directory.
    """
    allure_dir = Path(target_dir) / ".aether" / "allure-results"
    if not allure_dir.exists():
        return "No Allure results found. Run the pipeline with Allure strategy enabled."

    results = []
    # Read up to 20 recent result files
    files = sorted(
        allure_dir.glob("*-result.json"), key=lambda x: x.stat().st_mtime, reverse=True
    )
    for f in files[:20]:
        try:
            with open(f, "r") as f_in:
                results.append(json.load(f_in))
        except Exception:
            continue

    return results


@mcp.tool()
async def get_allure_summary(target_dir: str = "."):
    """
    Get a summary of Allure test results, grouped by status and suite.
    """
    allure_dir = Path(target_dir) / ".aether" / "allure-results"
    if not allure_dir.exists():
        return "No Allure results found."

    summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "suites": {}}

    files = list(allure_dir.glob("*-result.json"))
    for f in files:
        try:
            with open(f, "r") as f_in:
                data = json.load(f_in)
                summary["total"] += 1
                status = data.get("status", "unknown")
                if status == "passed":
                    summary["passed"] += 1
                elif status == "failed":
                    summary["failed"] += 1
                else:
                    summary["skipped"] += 1

                suite = "unknown"
                for label in data.get("labels", []):
                    if label.get("name") == "suite":
                        suite = label.get("value")

                if suite not in summary["suites"]:
                    summary["suites"][suite] = {"total": 0, "passed": 0, "failed": 0}

                summary["suites"][suite]["total"] += 1
                if status == "passed":
                    summary["suites"][suite]["passed"] += 1
                elif status == "failed":
                    summary["suites"][suite]["failed"] += 1
        except Exception:
            continue

    return summary


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
