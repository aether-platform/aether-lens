import json
import os
import subprocess

import click
from rich.console import Console

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
def check(target_dir):
    """Validate environment prerequisites and configuration integrity."""
    check_prerequisites(target_dir, verbose=True)


def check_prerequisites(target_dir=".", verbose=False):
    """
    Core logic to check environment and configuration.
    Returns: dict with check results
    """
    results = {
        "config": {"status": "skipped", "error": None},
        "tools": {},
        "valid": True,
    }

    def log(msg, style=""):
        if verbose:
            console.print(msg, style=style)

    log("[bold blue]Running Prerequisite Checks...[/bold blue]")

    # 1. Config Check
    config_path = os.path.join(target_dir, "aether-lens.config.json")
    if not os.path.exists(config_path):
        log(f"[yellow]⚠ Config not found at {config_path}[/yellow]")
        results["config"]["status"] = "missing"
    else:
        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            # Simple Schema Validation
            required_keys = ["strategy", "browser_strategy"]
            missing = [k for k in required_keys if k not in config]

            if missing:
                log(f"[red]✖ Config Invalid. Missing keys: {missing}[/red]")
                results["config"] = {
                    "status": "invalid",
                    "error": f"Missing: {missing}",
                }
                results["valid"] = False
            else:
                log(
                    f"[green]✔ Config Integrity OK[/green] (Strategy: {config.get('strategy')})"
                )
                results["config"]["status"] = "ok"

                # Check tools based on config
                browser_strategy = config.get("browser_strategy", "local")
                if browser_strategy == "docker":
                    _check_tool(results, "docker", "docker --version")
                elif browser_strategy in ["kubernetes", "inpod", "k8s"]:
                    _check_tool(results, "kubectl", "kubectl version --client")

        except json.JSONDecodeError as e:
            log(f"[red]✖ Config JSON Error: {e}[/red]")
            results["config"] = {"status": "error", "error": str(e)}
            results["valid"] = False

    # 2. Common Tools Check (Node/NPM often required for frontend checks)
    _check_tool(results, "node", "node --version")
    _check_tool(results, "npm", "npm --version", critical=False)
    _check_tool(results, "git", "git --version")

    if results["valid"]:
        log("\n[bold green]All checks passed![/bold green]")
    else:
        log("\n[bold red]Checks failed. Please review errors above.[/bold red]")

    return results


def _check_tool(results, tool_name, check_cmd, critical=True):
    try:
        subprocess.run(
            check_cmd,
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if results.get("tools") is None:
            results["tools"] = {}
        # We need to access the closure or pass console, but function is simple
        console.print(f"[green]✔ Tool '{tool_name}' found[/green]")
        results["tools"][tool_name] = True
    except subprocess.CalledProcessError:
        style = "red" if critical else "yellow"
        msg = f"[{style}]✖ Tool '{tool_name}' not found or failed[/{style}]"
        console.print(msg)
        results["tools"][tool_name] = False
        if critical:
            results["valid"] = False
