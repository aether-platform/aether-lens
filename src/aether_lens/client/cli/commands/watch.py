import asyncio
import os

import click
from rich.console import Console

from aether_lens.core.pipeline import load_config, run_pipeline

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
def watch(
    target,
    strategy,
    browser_strategy,
    browser_url,
    launch_browser,
    headless,
    app_url,
    allure_strategy,
    launch_allure,
    allure_endpoint,
    allure_project_id,
    allure_api_key,
):
    """Watch for changes and run pipeline (In-Pod mode)."""
    from aether_lens.client.cli.main import container
    from aether_lens.core.tui import PipelineDashboard

    service = container.watch_service()
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")
    config = load_config(target_dir)

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

    container.config.browser_strategy.from_value(browser_strategy.replace("-", "_"))
    container.config.browser_url.from_value(browser_url)
    container.config.launch_browser.from_value(launch_browser)
    container.config.headless.from_value(headless)

    selected_strategy = (
        strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
    )
    custom_instruction = config.get("vibecoding", {}).get("custom_instruction")
    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    console.print(f"[Lens Loop] Starting Watch Mode on {target_dir}...")
    browser_provider = container.browser_provider()
    app = PipelineDashboard([], strategy_name=selected_strategy)

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
        from aether_lens.core.report import KubernetesAllureProvider

        allure_provider = KubernetesAllureProvider()

    async def run_logic():
        if allure_provider:
            try:
                endpoint = await allure_provider.start()
                os.environ["ALLURE_ENDPOINT"] = endpoint
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to launch Allure: {e}[/yellow]")

        if allure_project_id or os.getenv("ALLURE_PROJECT_ID"):
            os.environ["ALLURE_PROJECT_ID"] = allure_project_id or os.getenv(
                "ALLURE_PROJECT_ID", "default"
            )
        if allure_api_key or os.getenv("ALLURE_API_KEY"):
            os.environ["ALLURE_API_KEY"] = allure_api_key or os.getenv("ALLURE_API_KEY")

        # --- Deployment Hook via Service ---
        try:
            await service.setup_deployment(target_dir, browser_strategy, config)
        except Exception as e:
            console.print(f"[red]Setup failed: {e}[/red]")
            return

        while not app.is_mounted:
            await asyncio.sleep(0.1)

        async def trigger_pipeline():
            try:
                await run_pipeline(
                    target_dir,
                    browser_url,
                    context,
                    rp_url=rp_url,
                    allure_dir=allure_dir,
                    strategy=selected_strategy,
                    custom_instruction=custom_instruction,
                    browser_provider=browser_provider,
                    use_tui=True,
                    close_browser=False,
                    app_url=app_url,
                )
            except Exception as e:
                app.log_message(f"[red]Pipeline error:[/red] {e}")

        def on_change(file_path):
            app.log_message(f"Change detected: {file_path}")
            asyncio.run_coroutine_threadsafe(
                trigger_pipeline(), asyncio.get_running_loop()
            )

        observer = service.start_watching(target_dir, on_change)
        await trigger_pipeline()

        try:
            while True:
                await asyncio.sleep(1)
        finally:
            observer.stop()
            observer.join()
            await browser_provider.close()
            if allure_provider:
                await allure_provider.stop()
            await service.perform_cleanup(target_dir)

    async def main_loop():
        asyncio.create_task(run_logic())
        await app.run_async()

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        console.print("\n[Lens Watch] Stopped.", style="dim")
