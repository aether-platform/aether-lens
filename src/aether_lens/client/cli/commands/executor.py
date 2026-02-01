import asyncio
import sys
import time

import click
from dependency_injector.wiring import Provide, inject

from aether_lens.core.containers import Container
from aether_lens.core.domain.events import EventEmitter, JSONLinesTransport
from aether_lens.core.domain.models import PipelineLogEvent


@click.command()
@click.argument("target_dir", type=click.Path(exists=True))
@click.option("--strategy", default="auto", help="Execution strategy")
@click.option("--browser-strategy", default="local", help="Browser strategy")
@click.option("--browser-url", help="Browser websocket URL")
@click.option("--app-url", help="Base URL of the application to test")
@click.option(
    "--headless/--headed",
    default=False,
    help="Run in headless mode",
)
@inject
def executor(
    target_dir,
    strategy,
    browser_strategy,
    browser_url,
    app_url,
    headless,
    execution_service=Provide[Container.execution_service],
):
    """
    Testkube-style Executor: runs pipeline and emits JSON Lines to stdout.
    """

    async def run():
        # Setup EventEmitter with abstracted JSONLinesTransport
        emitter = EventEmitter(transports=[JSONLinesTransport()])

        # Log start
        emitter.emit(
            PipelineLogEvent(
                type="log",
                timestamp=time.time(),
                message=f"Executor started for {target_dir}",
                level="INFO",
            )
        )

        try:
            # Note: ExecutionController handles container config internally
            await execution_service.run_pipeline(
                target_dir=target_dir,
                browser_url=browser_url,
                context="executor",
                strategy=strategy,
                app_url=app_url,
                use_tui=False,
                event_emitter=emitter,
            )

            # Final result is already emitted via PipelineResultEvent inside run_pipeline?
            # If not, we can emit it here if we want.
        except Exception as e:
            emitter.emit(
                PipelineLogEvent(
                    type="log",
                    timestamp=time.time(),
                    message=f"Executor failed: {str(e)}",
                    level="ERROR",
                )
            )
            sys.exit(1)

    asyncio.run(run())
