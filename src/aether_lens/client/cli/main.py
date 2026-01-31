import click

from aether_lens.client.cli.commands.init import init
from aether_lens.client.cli.commands.loop import loop
from aether_lens.client.cli.commands.mcp import mcp
from aether_lens.client.cli.commands.run import run
from aether_lens.client.cli.commands.stop import stop
from aether_lens.client.cli.commands.watch import watch
from aether_lens.core.containers import Container

# Initialize container and wire to relevant modules
container = Container()
container.wire(
    modules=[
        "aether_lens.core.pipeline",
        "aether_lens.client.cli.commands.run",
        "aether_lens.client.cli.commands.watch",
        "aether_lens.client.cli.commands.loop",
    ]
)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Aether Lens: AI-powered live testing and development loop."""
    pass


# Add subcommands
cli.add_command(init)
cli.add_command(run)
cli.add_command(watch)
cli.add_command(loop)
cli.add_command(stop)
cli.add_command(mcp)


def main():
    cli()


if __name__ == "__main__":
    main()
