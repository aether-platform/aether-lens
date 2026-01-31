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

    strategy = Prompt.ask(
        "Select default analysis strategy",
        choices=["auto", "frontend", "backend", "microservice", "custom"],
        default="auto",
    )

    custom_instruction = ""
    if strategy == "custom":
        custom_instruction = Prompt.ask("Enter custom analysis instructions")

    default_config = {
        "strategy": strategy,
        "custom_instruction": custom_instruction,
        "dev_loop": {"browser_targets": ["desktop", "mobile"], "debounce_seconds": 2},
    }

    with open(config_path, "w") as f:
        json.dump(default_config, f, indent=2)

    console.print(f"[bold green]Successfully generated:[/bold green] {config_path}")
