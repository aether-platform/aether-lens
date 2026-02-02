import asyncio

import click
from dependency_injector.wiring import Provide, inject

from aether_lens.core.containers import Container


@click.command()
@click.argument("target", default=".")
@click.option(
    "--analysis",
    "--analysis-strategy",
    "--strategy",
    "strategy",
    type=click.Choice(["auto", "frontend", "backend", "microservice", "custom"]),
    default="auto",
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
@inject
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
    service=Provide[Container.execution_service],
):
    """Run Aether Lens pipeline once."""
    # container access removed, using injected service

    asyncio.run(
        service.run_pipeline(
            target_dir=target,
            interactive=False,
            browser_url=browser_url,
            strategy=strategy,
            app_url=app_url,
            # event_emitter=emitter if not headless else None, # emitter is not defined in this scope
        )
    )
