import asyncio

from dependency_injector.wiring import Provide, inject
from rich.console import Console

from aether_lens.core.containers import Container
from aether_lens.daemon.controller.watcher import start_watcher
from aether_lens.daemon.registry import register_loop

console = Console(stderr=True)


@inject
def run_loop_daemon(
    target_dir,
    pod_name,
    namespace,
    remote_path,
    blocking=True,
    browser_strategy="inpod",
    browser_url=None,
    loop_handler_factory=Provide[Container.loop_handler.provider],
):
    """
    Starts the loop daemon that watches for changes and triggers sync.
    """
    console.print(f" -> Local Dir: {target_dir}")
    console.print(f" -> Remote Pod: {namespace}/{pod_name}")
    console.print(f" -> Remote Path: {remote_path}")
    console.print(f" -> Browser Strategy: {browser_strategy}")

    handler = loop_handler_factory(
        target_dir=target_dir,
        pod_name=pod_name,
        namespace=namespace,
        remote_path=remote_path,
        browser_strategy=browser_strategy,
        browser_url=browser_url,
    )

    # Initial sync
    asyncio.run(handler.sync_and_trigger())

    async def on_change(path):
        await handler.sync_and_trigger(path)

    observer = start_watcher(target_dir, on_change, blocking=blocking)

    if not blocking:
        register_loop(target_dir, observer)
        return observer
