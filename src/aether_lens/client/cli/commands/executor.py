import asyncio
import sys
import time

import click

from aether_lens.core.models import PipelineLogEvent


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
def executor(target_dir, strategy, browser_strategy, browser_url, app_url, headless):
    """
    Testkube-style Executor: runs pipeline and emits JSON Lines to stdout.
    """

    async def run():
        from aether_lens.core.events import EventEmitter, JSONLinesTransport

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

        from aether_lens.client.cli.main import container

        try:
            service = container.execution_service()
            await service.run_once(
                target_dir=target_dir,
                strategy=strategy,
                browser_strategy=browser_strategy,
                browser_url=browser_url,
                app_url=app_url,
                headless=headless,
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
