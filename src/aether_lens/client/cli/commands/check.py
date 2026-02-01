import subprocess

import click
from dependency_injector.wiring import Provide, inject
from rich.console import Console

from aether_lens.core.containers import Container

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
@inject
def check(
    target_dir,
    verbose,
    check_service: Container.check_service = Provide[Container.check_service],
):
    """Validate environment prerequisites and configuration integrity."""
    check_service.verbose = verbose
    check_service.check_prerequisites(target_dir)


@inject
def check_prerequisites(
    target_dir=".",
    verbose=False,
    check_service: Container.check_service = Provide[Container.check_service],
):
    """Legacy/Compatibility entry point for MCP/others."""
    check_service.verbose = verbose
    return check_service.check_prerequisites(target_dir)


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
