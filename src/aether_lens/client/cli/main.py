import click
import logfire

from aether_lens.client.cli.commands.check import check
from aether_lens.client.cli.commands.executor import executor
from aether_lens.client.cli.commands.init import init
from aether_lens.client.cli.commands.loop import loop
from aether_lens.client.cli.commands.mcp import mcp
from aether_lens.client.cli.commands.report import report
from aether_lens.client.cli.commands.run import run
from aether_lens.client.cli.commands.stop import stop
from aether_lens.client.cli.commands.watch import watch
from aether_lens.core.containers import Container

logfire.configure(send_to_logfire="if-token-present")
logfire.instrument_pydantic()

# Initialize container and wire to relevant modules
Container.validate_environment()
container = Container()
container.wire(
    modules=[
        "aether_lens.client.cli.commands.run",
        "aether_lens.client.cli.commands.watch",
        "aether_lens.client.cli.commands.loop",
        "aether_lens.client.cli.commands.stop",
        "aether_lens.client.cli.commands.report",
        "aether_lens.client.cli.commands.executor",
        "aether_lens.client.cli.commands.init",
        "aether_lens.client.cli.commands.check",
        "aether_lens.daemon.controller.execution",
        "aether_lens.daemon.controller.watcher",
        "aether_lens.daemon.loop_daemon",
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
cli.add_command(check)
cli.add_command(watch)
cli.add_command(loop)
cli.add_command(executor)
cli.add_command(stop)
cli.add_command(mcp)
cli.add_command(report)


def main():
    cli()


if __name__ == "__main__":
    main()
