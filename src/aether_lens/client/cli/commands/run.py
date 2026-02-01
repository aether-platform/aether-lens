import asyncio

import click


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

    service = container.execution_service()

    asyncio.run(
        service.run_once(
            target_dir=target,
            strategy=strategy,
            browser_strategy=browser_strategy,
            browser_url=browser_url,
            launch_browser=launch_browser,
            headless=headless,
            app_url=app_url,
            allure_strategy=allure_strategy,
            allure_endpoint=allure_endpoint,
            allure_project_id=allure_project_id,
            allure_api_key=allure_api_key,
        )
    )
