import asyncio
import os

import click

from aether_lens.core.pipeline import load_config, run_pipeline


@click.command()
@click.argument("target", required=False)
@click.option(
    "--allure",
    "--allure-strategy",
    "allure_strategy",
    type=click.Choice(["none", "ephemeral", "external", "kubernetes", "docker"]),
    help="Allure reporting strategy. Must match execution environment (env: ALLURE_STRATEGY)",
)
@click.option(
    "--allure-endpoint",
    help="Remote Allure API endpoint (env: ALLURE_ENDPOINT)",
)
@click.option(
    "--allure-project-id",
    help="Project ID for team isolation (env: ALLURE_PROJECT_ID)",
)
@click.option(
    "--allure-api-key",
    help="API Key for remote Allure (env: ALLURE_API_KEY)",
)
def run(
    target,
    strategy,
    browser_strategy,
    browser_url,
    launch_browser,
    headless,
    app_url,
    allure_strategy,
    allure_endpoint,
    allure_project_id,
    allure_api_key,
):
    """Run Aether Lens pipeline once."""
    from aether_lens.client.cli.main import container

    # 1. Load config first to check for defaults
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")
    config = load_config(target_dir)

    # 2. Resolve browser strategy (CLI > Env > Config > Default)
    # ... (browser logic remains the same)
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

    # Resolve strategy and context
    selected_strategy = (
        strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
    )
    custom_instruction = (
        config.get("custom_instruction", "") if selected_strategy == "custom" else None
    )

    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    # Allure Config (CLI > Env > Config)
    allure_strategy = (
        allure_strategy or os.getenv("ALLURE_STRATEGY") or config.get("allure_strategy")
    )
    allure_endpoint = (
        allure_endpoint or os.getenv("ALLURE_ENDPOINT") or config.get("allure_endpoint")
    )
    allure_project_id = (
        allure_project_id
        or os.getenv("ALLURE_PROJECT_ID")
        or config.get("allure_project_id", "default")
    )
    allure_api_key = (
        allure_api_key or os.getenv("ALLURE_API_KEY") or config.get("allure_api_key")
    )

    if allure_strategy == "none":
        allure_endpoint = None
    elif allure_strategy in ["ephemeral", "kubernetes"] and not allure_endpoint:
        pass

    if allure_endpoint:
        os.environ["ALLURE_ENDPOINT"] = allure_endpoint
    if allure_project_id:
        os.environ["ALLURE_PROJECT_ID"] = allure_project_id
    if allure_api_key:
        os.environ["ALLURE_API_KEY"] = allure_api_key

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
