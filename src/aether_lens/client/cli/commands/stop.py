import click
from rich.console import Console

console = Console(stderr=True)


@click.command()
@click.argument("target_dir", default=".")
def stop(target_dir):
    """Stop an active Aether Lens loop."""
    from aether_lens.core.services.daemon_service import DaemonService

    service = DaemonService()

    if service.stop_loop(target_dir):
        click.echo(f"Lens loop stopped for {target_dir}")
    else:
        click.echo(f"No active loop found for {target_dir}")
        # Since CLI and MCP might run in different processes,
        # this only works if they share a registry (e.g. via a socket or file).
        # For now, we report if it's not found in the current process.
        console.print()
        console.print(
            "[dim]Note: If the loop was started in a different process (like MCP), use that interface to stop it.[/dim]"
        )
