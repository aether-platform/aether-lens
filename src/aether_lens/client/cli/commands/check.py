import subprocess

import click
from rich.console import Console

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
def check(target_dir, verbose):
    """Validate environment prerequisites and configuration integrity."""
    from aether_lens.client.cli.main import container

    service = container.check_service()
    service.verbose = verbose
    service.check_prerequisites(target_dir)


def check_prerequisites(target_dir=".", verbose=False):
    """Legacy/Compatibility entry point for MCP/others."""
    from aether_lens.client.cli.main import container

    service = container.check_service()
    service.verbose = verbose
    return service.check_prerequisites(target_dir)


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
