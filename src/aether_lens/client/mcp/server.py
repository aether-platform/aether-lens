import os

from fastmcp import FastMCP

from aether_lens.core.containers import Container
from aether_lens.core.pipeline import run_pipeline
from aether_lens.daemon.loop_daemon import run_loop_daemon

# Initialize and wire container for MCP process
container = Container()
container.wire(
    modules=[
        "aether_lens.core.pipeline",
        "aether_lens.daemon.loop_daemon",
    ]
)

mcp = FastMCP("Aether Lens")


@mcp.tool()
def run_lens_test(
    target_dir: str,
    strategy: str = "auto",
    browser_strategy: str = "local",
    browser_url: str = None,
):
    """
    Run the Aether Lens analysis pipeline on a local directory (Blocking).

    :param target_dir: The directory to analyze.
    :param strategy: Analysis strategy (auto, frontend, backend, microservice, custom).
    :param browser_strategy: local, docker, or inpod.
    :param browser_url: Optional CDP URL for docker/inpod.
    """
    # The original run_pipeline import is at the top of the file,
    # but the instruction snippet includes it here.
    # Keeping the original top-level import and removing this redundant one.
    # from aether_lens.core.pipeline import run_pipeline

    # Resolve default URL if not provided
    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            # os is already imported at top
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    container.config.browser_strategy.from_value(browser_strategy)
    container.config.browser_url.from_value(browser_url)

    import asyncio

    results = asyncio.run(run_pipeline(target_dir=target_dir, strategy=strategy))
    return results


@mcp.tool()
def start_lens_loop(
    target_dir: str,
    pod_name: str,
    namespace: str = "aether-system",
    remote_path: str = "/app/project",
    browser_strategy: str = "inpod",
    browser_url: str = None,
):
    """
    Start the local Lens Loop daemon for a directory (Non-blocking).
    This will watch for local changes in the background.

    :param target_dir: Local directory to watch.
    :param pod_name: Target Kubernetes Pod name.
    :param namespace: Kubernetes namespace.
    :param remote_path: Path inside the container to sync files to.
    :param browser_strategy: local, docker, or inpod.
    :param browser_url: Optional CDP URL for docker/inpod.
    """
    run_loop_daemon(
        target_dir,
        pod_name,
        namespace,
        remote_path,
        blocking=False,
        browser_strategy=browser_strategy,
        browser_url=browser_url,
    )
    return f"Lens Loop started in background for {target_dir} targeting {pod_name}."


@mcp.tool()
def stop_lens_loop(target_dir: str):
    """
    Stop the active Lens Loop daemon for a directory.

    :param target_dir: Local directory being watched.
    """
    from aether_lens.daemon.registry import stop_loop

    if stop_loop(target_dir):
        return f"Lens Loop stopped for {target_dir}."
    else:
        return f"No active Lens Loop found for {target_dir}."


def main():
    mcp.run()


if __name__ == "__main__":
    main()
