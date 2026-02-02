import click
from dependency_injector.wiring import Provide, inject
from rich.console import Console

from aether_lens.core.containers import Container

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
@inject
def loop(
    target_dir,
    pod_name,
    namespace,
    remote_path,
    browser_strategy,
    browser_url,
    execution_service: Container.execution_service = Provide[
        Container.execution_service
    ],
):
    """Start a heavy development loop (Sync & Remote Test)."""

    if not pod_name:
        console.print("[red]Error: Pod name is required for loop command.[/red]")
        return

    # Use controller to start the loop
    import asyncio

    asyncio.run(
        execution_service.start_loop(
            target_dir=target_dir,
            pod_name=pod_name,
            namespace=namespace,
            remote_path=remote_path,
            browser_strategy=browser_strategy,
            browser_url=browser_url,
        )
    )

    # Since start_loop with blocking=False returns, but CLI usually wants to block
    # We might need to keep it running here if we want the CLI to stay active.
    import time

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        execution_service.stop_dev_loop(target_dir)
