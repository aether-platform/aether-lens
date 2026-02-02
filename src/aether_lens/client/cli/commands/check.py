import asyncio

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
    asyncio.run(check_service.check_prerequisites(target_dir))


@inject
async def check_prerequisites(
    target_dir=".",
    verbose=False,
    check_service: Container.check_service = Provide[Container.check_service],
):
    """Legacy/Compatibility entry point for MCP/others."""
    check_service.verbose = verbose
    return await check_service.check_prerequisites(target_dir)
