import os

import click
from rich.console import Console

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
@click.argument("pod_name", required=False)
@click.option("--namespace", default="aether-system", help="Target Namespace")
@click.option("--remote-path", default="/app/project", help="Remote sync path")
@click.option(
    "--browser-strategy",
    type=click.Choice(["local", "docker", "inpod"]),
    default="inpod",
    help="Browser execution strategy",
)
@click.option("--browser-url", help="CDP URL for docker/inpod strategy")
def loop(target_dir, pod_name, namespace, remote_path, browser_strategy, browser_url):
    """Start a heavy development loop (Sync & Remote Test)."""
    from aether_lens.client.cli.main import container
    from aether_lens.core.services.daemon_service import DaemonService

    # Resolve default URL if not provided
    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    container.config.browser_strategy.from_value(browser_strategy)
    container.config.browser_url.from_value(browser_url)

    if not pod_name:
        console.print("[red]Error: Pod name is required for loop command.[/red]")
        return

    service = DaemonService()
    service.start_loop(
        target_dir=target_dir,
        pod_name=pod_name,
        namespace=namespace,
        remote_path=remote_path,
        blocking=True,
        browser_strategy=browser_strategy,
        browser_url=browser_url,
    )
