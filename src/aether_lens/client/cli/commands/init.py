from pathlib import Path

import click
from dependency_injector.wiring import Provide, inject
from rich.console import Console
from rich.prompt import Confirm, Prompt

from aether_lens.core.containers import Container

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
@inject
def init(
    target_dir,
    init_service: Container.init_service = Provide[Container.init_service],
):
    """Initialize Aether Lens configuration."""
    config_path = Path(target_dir) / "aether-lens.config.json"

    if config_path.exists():
        if not Confirm.ask(
            f"[yellow]{config_path} already exists. Overwrite?[/yellow]", default=False
        ):
            console.print("[yellow]Aborted.[/yellow]")
            return

    console.print("[bold blue]Aether Lens Configuration Generator[/bold blue]")

    analysis_strategy = Prompt.ask(
        "Select default analysis strategy",
        choices=["auto", "frontend", "backend", "microservice", "custom"],
        default="auto",
    )

    custom_instruction = ""
    if analysis_strategy == "custom":
        custom_instruction = Prompt.ask("Enter custom analysis instructions")

    console.print("\n[bold cyan]Execution Settings[/bold cyan]")
    browser_strategy = Prompt.ask(
        "Select browser execution strategy",
        choices=["local", "docker", "kubernetes", "inpod"],
        default="local",
    )

    console.print("\n[bold cyan]Allure Reporting Settings[/bold cyan]")
    allure_choice = Prompt.ask(
        f"Select Allure reporting method (Matched to {browser_strategy}?)",
        choices=["managed", "external", "none"],
        default="managed",
    )

    allure_strategy = "none"
    allure_endpoint = ""
    allure_project_id = "default"

    if allure_choice == "managed":
        # Match browser strategy
        allure_strategy = (
            browser_strategy if browser_strategy != "local" else "ephemeral"
        )
    elif allure_choice == "external":
        allure_strategy = "external"
        allure_endpoint = Prompt.ask(
            "Enter external Allure API endpoint", default="http://localhost:5050"
        )

    if allure_choice != "none":
        allure_project_id = Prompt.ask(
            "Enter Allure Project ID (for team isolation)", default="default"
        )

    console.print("\n[bold cyan]Application Lifecycle (Environment-Driven)[/bold cyan]")
    deployment_config = {}

    # Smart defaults based on strategy
    if browser_strategy in ["docker", "local"]:
        if Confirm.ask(
            "Use Docker Compose for deployment?", default=(browser_strategy == "docker")
        ):
            compose_file = Prompt.ask(
                "Compose file path", default="docker-compose.yaml"
            )
            service = Prompt.ask(
                "Target Service Name (default: app, empty for full stack)",
                default="app",
            )
            health_check = Prompt.ask(
                "Health Check URL", default="http://localhost:8080/health"
            )

            deployment_config["docker"] = {
                "type": "compose",
                "file": compose_file,
                "service": service,
                "health_check": health_check,
            }
            deployment_config["local"] = deployment_config["docker"]

    elif browser_strategy in ["kubernetes", "inpod"]:
        if Confirm.ask("Use Kustomize for deployment?", default=True):
            kustomize_path = Prompt.ask(
                "Kustomize overlay path (dir)", default="k8s/overlays/test"
            )
            namespace = Prompt.ask("Target Namespace (optional override)", default="")
            health_check = Prompt.ask(
                "Health Check URL", default="http://service:8080/health"
            )

            deploy_conf = {
                "type": "kustomize",
                "path": kustomize_path,
                "health_check": health_check,
            }
            if namespace:
                deploy_conf["namespace"] = namespace

            deployment_config["kubernetes"] = deploy_conf
            deployment_config["inpod"] = deploy_conf

    # Write config
    config = {
        "strategy": analysis_strategy,
        "custom_instruction": custom_instruction,
        "browser_strategy": browser_strategy,
        "allure_strategy": allure_strategy,
        "allure_endpoint": allure_endpoint,
        "allure_project_id": allure_project_id,
        "deployment": deployment_config,
    }

    result_path = init_service.generate_default_config(target_dir, **config)
    console.print(f"[bold green]Successfully generated:[/bold green] {result_path}")
