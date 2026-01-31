import asyncio
import os

import click
from rich.console import Console

from aether_lens.core.pipeline import load_config, run_pipeline
from aether_lens.core.watcher import start_watcher

console = Console(stderr=True)


@click.command()
@click.argument("target", required=False)
@click.option(
    "--strategy",
    type=click.Choice(["auto", "frontend", "backend", "microservice", "custom"]),
    help="Analysis strategy",
)
@click.option(
    "--browser-strategy",
    type=click.Choice(["local", "docker", "inpod"]),
    default="inpod",
    help="Browser execution strategy",
)
@click.option("--browser-url", help="CDP URL for docker/inpod strategy")
def watch(target, strategy, browser_strategy, browser_url):
    """Watch for changes and run pipeline (In-Pod mode)."""
    from aether_lens.client.cli.main import container

    # Resolve default URL if not provided
    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    container.config.browser_strategy.from_value(browser_strategy)
    container.config.browser_url.from_value(browser_url)

    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")

    config = load_config(target_dir)
    selected_strategy = strategy or config.get("strategy", "auto")

    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    console.print(f"[Lens Loop] Starting Watch Mode on {target_dir}...")

    def on_change(path):
        console.print(f"\n[Lens Watch] Change detected: {path}", style="bold yellow")
        asyncio.run(
            run_pipeline(
                target_dir,
                browser_url,
                context,
                rp_url=rp_url,
                allure_dir=allure_dir,
                strategy=selected_strategy,
            )
        )

    # Initial run
    asyncio.run(
        run_pipeline(
            target_dir,
            browser_url,
            context,
            rp_url=rp_url,
            allure_dir=allure_dir,
            strategy=selected_strategy,
        )
    )

    start_watcher(target_dir, on_change)
