import asyncio
from os import environ
from pathlib import Path

import click
from dependency_injector.wiring import Provide, inject
from rich.console import Console

from aether_lens.core.containers import Container
from aether_lens.core.domain.events import CallbackTransport, EventEmitter
from aether_lens.core.presentation.tui import PipelineDashboard

console = Console(stderr=True)


@click.command()
@click.argument("target", required=False)
@click.option(
    "--analysis",
    "--analysis-strategy",
    "--strategy",
    "strategy",
    type=click.Choice(["auto", "frontend", "backend", "microservice", "custom"]),
    help="AI Analysis strategy (env: AETHER_ANALYSIS)",
)
@click.option(
    "--browser",
    "--browser-strategy",
    "browser_strategy",
    type=click.Choice(["local", "docker", "k8s", "inpod", "dry-run"]),
    required=False,
    help="Browser execution strategy (env: AETHER_BROWSER)",
)
@click.option(
    "--headless/--headed",
    default=False,
    help="Run in headless mode",
)
@click.option("--browser-url", help="CDP URL for docker/inpod strategy")
@click.option(
    "--app-url",
    help="Base URL of the application under test",
)
@inject
def watch(
    target,
    strategy,
    browser_strategy,
    browser_url,
    headless,
    app_url,
    execution_service: Container.execution_service = Provide[
        Container.execution_service
    ],
):
    """Watch for file changes and trigger pipeline."""
    target_path = Path(target or environ.get("TARGET_DIR") or ".").resolve()
    target_dir = str(target_path)

    strategy = strategy or environ.get("AETHER_ANALYSIS") or "auto"

    console.print(f"[Lens Watch] Starting Watch Mode on {target_dir}...")

    async def run_watch():
        if headless:
            # Headless mode: Simple console output
            # We need an orchestrator for watch, which is now provided by Orchestrator
            # But execution_service is the Orchestrator?
            # In containers.py: execution_service = ExecutionController
            # But AetherOrchestrator exists too.

            # For now, if we use ExecutionController directly:
            from aether_lens.daemon.controller.orchestrator import AetherOrchestrator

            orchestrator = AetherOrchestrator(execution_service)

            await orchestrator.start_watch(
                target_dir=target_dir, strategy=strategy, interactive=False
            )
            console.print("[Lens Watch] Watching for changes... (Press Ctrl+C to stop)")
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                execution_service.stop_dev_loop(target_dir)
        else:
            app = PipelineDashboard([], strategy_name=strategy)
            emitter = EventEmitter(
                transports=[
                    CallbackTransport(
                        callback=lambda e: execution_service._handle_event_for_tui(
                            e, app
                        )
                    )
                ]
            )

            async def run_logic():
                loop = asyncio.get_running_loop()
                await execution_service.run_pipeline(
                    target_dir=target_dir,
                    browser_url=browser_url,
                    strategy=strategy,
                    app_url=app_url,
                    interactive=True,
                    event_emitter=emitter,
                )

                from aether_lens.daemon.controller.watcher import start_watcher

                async def _on_watch_change(path):
                    await execution_service.run_pipeline(
                        target_dir=target_dir,
                        strategy=strategy,
                        interactive=True,
                        event_emitter=emitter,
                        app_url=app_url,
                    )

                def on_change(path):
                    loop.create_task(_on_watch_change(path))

                observer = start_watcher(
                    target_dir, on_change, blocking=False, loop=loop
                )
                if execution_service.lifecycle_registry:
                    execution_service.lifecycle_registry.register(target_dir, observer)

            app.run_logic_callback = lambda inst: run_logic()
            await app.run_async()

    try:
        asyncio.run(run_watch())
    except KeyboardInterrupt:
        execution_service.stop_dev_loop(target_dir)
