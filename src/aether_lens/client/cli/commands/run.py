import asyncio
import os

import click

from aether_lens.core.pipeline import load_config, run_pipeline


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
def run(
    target, strategy, browser_strategy, browser_url, launch_browser, headless, app_url
):
    """Run Aether Lens pipeline once."""
    from aether_lens.client.cli.main import container

    # 1. Load config first to check for defaults
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")
    config = load_config(target_dir)

    # 2. Resolve browser strategy (CLI > Env > Config > Default)
    # Smart Default: If no browser specified, decide based on headless flag
    # --headless -> docker (managed), --headed -> local (headed)

    env_browser = os.getenv("AETHER_BROWSER")
    config_browser = config.get("browser_strategy")

    if not browser_strategy and not env_browser and not config_browser:
        if headless:
            browser_strategy = "docker"
            if launch_browser is None:
                launch_browser = True
        else:
            browser_strategy = "local"
    else:
        # Fallback to defaults if partially set
        browser_strategy = browser_strategy or env_browser or config_browser or "local"

    # Default launch_browser to False if not set by smart logic or user
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

    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")

    # config already loaded above

    selected_strategy = (
        strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
    )
    custom_instruction = (
        config.get("custom_instruction", "") if selected_strategy == "custom" else None
    )

    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    # Run the pipeline logic
    asyncio.run(
        run_pipeline(
            target_dir,
            browser_url,
            context,
            rp_url=rp_url,
            allure_dir=allure_dir,
            strategy=selected_strategy,
            custom_instruction=custom_instruction,
            app_url=app_url,
        )
    )
