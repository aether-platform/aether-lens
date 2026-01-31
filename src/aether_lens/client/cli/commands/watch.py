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
def watch(
    target, strategy, browser_strategy, browser_url, launch_browser, headless, app_url
):
    """Watch for changes and run pipeline (In-Pod mode)."""
    from aether_lens.client.cli.main import container

    # 1. Load config first
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")
    config = load_config(target_dir)

    # 2. Resolve browser strategy (CLI > Env > Config > Default)
    # Smart Default for Watch: same as run
    env_browser = os.getenv("AETHER_BROWSER")
    config_browser = config.get("browser_strategy")

    if not browser_strategy and not env_browser and not config_browser:
        if headless:
            browser_strategy = "docker"
            if launch_browser is None:
                launch_browser = True
        else:
            browser_strategy = "local"  # Watch defaults to local headed now
    else:
        browser_strategy = (
            browser_strategy or env_browser or config_browser or "inpod"
        )  # Fallback original default if needed? No, let's consistency.

    # If fallback logic above didn't catch (e.g. browser_strategy provided but others None), defaults handled.
    # Actually logic:
    # browser_strategy = browser_strategy or env or config or "inpod" (original)
    # New logic replaces the "inpod" default with smart choice.

    if not browser_strategy and not env_browser and not config_browser:
        pass  # Handled above
    elif not browser_strategy:
        browser_strategy = env_browser or config_browser or "local"

    # Simplified consistent logic:
    if not browser_strategy:
        browser_strategy = env_browser or config_browser

    if not browser_strategy:
        if headless:
            browser_strategy = "docker"
            if launch_browser is None:
                launch_browser = True
        else:
            browser_strategy = "local"

    if launch_browser is None:
        launch_browser = False

    # Resolve default URL if not provided
    if not browser_url:
        if browser_strategy == "docker":
            browser_url = "ws://localhost:9222"
        elif browser_strategy == "inpod":
            browser_url = os.getenv("TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222")

    container.config.browser_strategy.from_value(browser_strategy.replace("-", "_"))
    container.config.browser_url.from_value(browser_url)
    container.config.launch_browser.from_value(launch_browser)
    container.config.headless.from_value(headless)

    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")

    # config already loaded above
    selected_strategy = (
        strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
    )
    custom_instruction = config.get("vibecoding", {}).get("custom_instruction")

    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    console.print(f"[Lens Loop] Starting Watch Mode on {target_dir}...")

    # Get persistent browser provider
    browser_provider = container.browser_provider()

    async def async_watch():
        loop = asyncio.get_running_loop()

        def on_change(file_path):
            console.print(
                f"\n[Lens Watch] Change detected: {file_path}", style="bold yellow"
            )
            asyncio.run_coroutine_threadsafe(
                run_pipeline(
                    target_dir,
                    browser_url,
                    context,
                    rp_url=rp_url,
                    allure_dir=allure_dir,
                    strategy=selected_strategy,
                    custom_instruction=custom_instruction,
                    browser_provider=browser_provider,
                    use_tui=False,
                    close_browser=False,
                    app_url=app_url,
                ),
                loop,
            )

        # Initial run
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
                use_tui=False,
                close_browser=False,
                app_url=app_url,
            )
        except Exception as e:
            console.print(f"[red]Initial run error:[/red] {e}")

        # Start watcher (non-blocking)
        observer = start_watcher(target_dir, on_change, blocking=False)
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            observer.stop()
        finally:
            observer.stop()
            observer.join()
            await browser_provider.close()

    try:
        asyncio.run(async_watch())
    except KeyboardInterrupt:
        console.print("\n[Lens Watch] Stopped.", style="dim")
