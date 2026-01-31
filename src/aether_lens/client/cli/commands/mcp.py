import click

from aether_lens.client.mcp.server import main as run_mcp


@click.command()
def mcp():
    """Start the Aether Lens MCP server."""
    run_mcp()
