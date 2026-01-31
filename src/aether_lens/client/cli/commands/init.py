import json
import os

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
def init(target_dir):
    """Initialize Aether Lens configuration."""
    config_path = os.path.join(target_dir, "aether-lens.config.json")

    if os.path.exists(config_path):
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

    default_config = {
        "strategy": analysis_strategy,
        "custom_instruction": custom_instruction,
        "browser_strategy": browser_strategy,
        "allure_strategy": allure_strategy,
        "allure_endpoint": allure_endpoint,
        "dev_loop": {"browser_targets": ["desktop", "mobile"], "debounce_seconds": 2},
    }

    with open(config_path, "w") as f:
        json.dump(default_config, f, indent=2)

    console.print(f"[bold green]Successfully generated:[/bold green] {config_path}")
