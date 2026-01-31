import click
from rich.console import Console

from aether_lens.daemon.registry import stop_loop

console = Console(stderr=True)


@click.command()
@click.argument("target", required=False, default=".")
def stop(target):
    """Stop an active Lens Loop for a specific directory."""
    if stop_loop(target):
        console.print(f"[bold green]Stopped Lens Loop for:[/bold green] {target}")
    else:
        # Since CLI and MCP might run in different processes,
        # this only works if they share a registry (e.g. via a socket or file).
        # For now, we report if it's not found in the current process.
        console.print(
            f"[yellow]No active Lens Loop found in this process for:[/yellow] {target}"
        )
        console.print(
            "[dim]Note: If the loop was started in a different process (like MCP), use that interface to stop it.[/dim]"
        )
