import asyncio
import os

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
    target_dir = os.path.abspath(target or os.getenv("TARGET_DIR") or ".")

    # Resolve strategy
    strategy = strategy or os.getenv("AETHER_ANALYSIS") or "auto"

    console.print(f"[Lens Watch] Starting Watch Mode on {target_dir}...")

    if headless:
        # Headless mode: Simple console output
        execution_service.start_watch(
            target_dir=target_dir, strategy=strategy, use_tui=False
        )
        console.print("[Lens Watch] Watching for changes... (Press Ctrl+C to stop)")
        try:
            while True:
                import time

                time.sleep(1)
        except KeyboardInterrupt:
            execution_service.stop_dev_loop(target_dir)
    else:
        # TUI mode: Persistent dashboard
        # We start a run manually first, or just let the watcher trigger.
        # But we need the dashboard to be the long-lived process.

        app = PipelineDashboard([], strategy_name=strategy)

        # Polymorphic event emitter for the controller to talk to this TUI
        emitter = EventEmitter(
            transports=[
                CallbackTransport(
                    callback=lambda e: execution_service._handle_event_for_tui(e, app)
                )
            ]
        )

        async def run_logic():
            # Initial run
            await execution_service.run_pipeline(
                target_dir=target_dir,
                browser_url=browser_url,
                strategy=strategy,
                app_url=app_url,
                use_tui=True,
                event_emitter=emitter,
            )

            # Start watcher via controller
            # We don't use the controller's run_pipeline loop here because we want to pass the emitter
            from aether_lens.daemon.controller.watcher import start_watcher

            def on_change(path):
                # Trigger pipeline with the same emitter
                asyncio.run(
                    execution_service.run_pipeline(
                        target_dir=target_dir,
                        strategy=strategy,
                        use_tui=True,
                        event_emitter=emitter,
                        app_url=app_url,
                    )
                )

            observer = start_watcher(target_dir, on_change, blocking=False)
            execution_service.lifecycle_registry.register(target_dir, observer)

        app.run_logic_callback = lambda inst: run_logic()

        try:
            asyncio.run(app.run_async())
        except KeyboardInterrupt:
            execution_service.stop_dev_loop(target_dir)
