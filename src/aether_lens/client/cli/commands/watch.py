import asyncio
import os

import click
from dependency_injector.wiring import Provide, inject
from rich.console import Console

from aether_lens.core.containers import Container
from aether_lens.core.presentation.report import KubernetesAllureProvider
from aether_lens.core.presentation.tui import PipelineDashboard

console = Console(stderr=True)


@click.command()
@click.argument("target", required=False)
@click.option(
    "--analysis",
    "--analysis-strategy",
    "--strategy",
    "strategy",
    type=click.Choice(["auto", "frontend", "backend", "microservice", "custom"]),
    help="AI Analysis strategy (env: AETHER_ANALYSIS)",
)
@click.option(
    "--browser",
    "--browser-strategy",
    "browser_strategy",
    type=click.Choice(["local", "docker", "k8s", "inpod", "dry-run"]),
    required=False,
    help="Browser execution strategy (env: AETHER_BROWSER)",
)
@click.option(
    "--launch-browser/--no-launch-browser",
    default=None,
    help="Launch ephemeral browser container/pod (Default: False, or True if --headless implied)",
)
@click.option(
    "--headless/--headed",
    default=False,
    help="Run in headless mode (Implies --browser docker if not set)",
)
@click.option("--browser-url", help="CDP URL for docker/inpod strategy")
@click.option(
    "--app-url",
    help="Base URL of the application under test (Default: http://localhost:4321)",
)
@click.option(
    "--allure",
    "--allure-strategy",
    "allure_strategy",
    type=click.Choice(["none", "ephemeral", "external", "kubernetes", "docker"]),
    help="Allure reporting strategy (env: ALLURE_STRATEGY)",
)
@click.option(
    "--launch-allure/--no-launch-allure",
    default=None,
    help="Launch ephemeral Allure dashboard during watch (Default: True if no endpoint)",
)
@inject
def watch(
    target,
    strategy,
    browser_strategy,
    browser_url,
    launch_browser,
    headless,
    app_url,
    launch_allure,
    allure_strategy: str = Provide[Container.config.allure_strategy],
    allure_endpoint: str = Provide[Container.config.allure_endpoint],
    allure_project_id: str = Provide[Container.config.allure_project_id],
    allure_api_key: str = Provide[Container.config.allure_api_key],
    execution_service: Container.execution_service = Provide[
        Container.execution_service
    ],
    watch_service: Container.watch_service = Provide[Container.watch_service],
):
    """Watch for file changes and trigger pipeline."""
    # container access removed, using injected services
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")
    config = execution_service.load_config(target_dir)

    # 1. Resolve browser strategy (Controller logic)
    env_browser = os.getenv("AETHER_BROWSER")
    config_browser = config.get("browser_strategy")

    if not browser_strategy and not env_browser and not config_browser:
        browser_strategy = "docker" if headless else "local"
        if headless and launch_browser is None:
            launch_browser = True
    else:
        browser_strategy = browser_strategy or env_browser or config_browser or "local"

    if launch_browser is None:
        launch_browser = False

    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    # Update config in DI container
    execution_service.config.browser_strategy.from_value(
        browser_strategy.replace("-", "_")
    )
    execution_service.config.browser_url.from_value(browser_url)
    execution_service.config.launch_browser.from_value(launch_browser)
    execution_service.config.headless.from_value(headless)

    strategy = (
        strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
    )

    console.print(f"[Lens Loop] Starting Watch Mode on {target_dir}...")
    # browser_provider removed

    app = PipelineDashboard(config.get("tests", []), strategy_name=strategy)

    # Allure Strategy resolution
    allure_strategy = (
        allure_strategy or os.getenv("ALLURE_STRATEGY") or config.get("allure_strategy")
    )
    if launch_allure is None:
        if allure_strategy in ["ephemeral", "kubernetes"]:
            launch_allure = True
        elif allure_strategy == "none" or allure_strategy == "external":
            launch_allure = False
        else:
            launch_allure = not bool(allure_endpoint or os.getenv("ALLURE_ENDPOINT"))

    allure_provider = None
    if launch_allure:
        allure_provider = KubernetesAllureProvider()

    async def run_logic():
        if allure_provider:
            try:
                endpoint = await allure_provider.start()
                os.environ["ALLURE_ENDPOINT"] = endpoint
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to launch Allure: {e}[/yellow]")

        # --- Deployment Hook via WatchController ---
        try:
            await watch_service.setup_deployment(target_dir, browser_strategy, config)
        except Exception as e:
            console.print(f"[red]Setup failed: {e}[/red]")
            return

        while not app.is_mounted:
            await asyncio.sleep(0.1)

        def on_change(path):
            asyncio.run(
                execution_service.run_pipeline(
                    target_dir,
                    browser_url,
                    "watch",
                    strategy=strategy,
                    app_url=app_url,
                    use_tui=True,
                )
            )

        # Configure and start WatchController
        watch_service.target_dir = target_dir
        watch_service.on_change_callback = on_change
        observer = watch_service.start(blocking=False)
        if not observer:
            app.log_message("[red]Failed to start watcher observer[/red]")

        # Initial run
        try:
            await execution_service.run_pipeline(
                target_dir,
                browser_url,
                "watch",
                strategy=strategy,
                app_url=app_url,
                use_tui=True,
            )
        except Exception as e:
            app.log_message(f"[red]Pipeline error:[/red] {e}")

        try:
            while True:
                await asyncio.sleep(1)
        finally:
            watch_service.stop()
            if allure_provider:
                await allure_provider.stop()
            await watch_service.run_cleanup(target_dir)

    async def main_loop():
        asyncio.create_task(run_logic())
        await app.run_async()

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        console.print("\n[Lens Watch] Stopped.", style="dim")
