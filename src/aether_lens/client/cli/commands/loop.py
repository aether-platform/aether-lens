import os
import sys

import click
from rich.console import Console

from aether_lens.daemon.loop_daemon import run_loop_daemon

console = Console(stderr=True)


@click.command()
@click.argument("target", required=False, default=".")
@click.option("--pod", help="Target Pod name")
@click.option("--namespace", default="aether-system", help="Target Namespace")
@click.option(
    "--browser-strategy",
    type=click.Choice(["local", "docker", "inpod"]),
    default="inpod",
    help="Browser execution strategy",
)
@click.option("--browser-url", help="CDP URL for docker/inpod strategy")
def loop(target, pod, namespace, browser_strategy, browser_url):
    """Local development loop: sync changes to remote Pod and trigger analysis."""
    from aether_lens.client.cli.main import container

    # Resolve default URL if not provided
    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    container.config.browser_strategy.from_value(browser_strategy)
    container.config.browser_url.from_value(browser_url)

    pod_name = pod or os.getenv("LENS_POD_NAME")
    if not pod_name:
        console.print(
            "[bold red][Error] 'loop' command requires --pod or LENS_POD_NAME env var.[/bold red]"
        )
        sys.exit(1)

    remote_path = os.getenv("REMOTE_TARGET_DIR", "/app/project")
    run_loop_daemon(target, pod_name, namespace, remote_path)
