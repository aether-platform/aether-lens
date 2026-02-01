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
    test_runner=Provide[Container.test_runner],
):
    """
    Starts the loop daemon that watches for changes and triggers sync.
    """
    console.print(f" -> Local Dir: {target_dir}")
    console.print(f" -> Remote Pod: {namespace}/{pod_name}")
    console.print(f" -> Remote Path: {remote_path}")
    console.print(f" -> Browser Strategy: {browser_strategy}")

    test_runner.pod_name = pod_name
    test_runner.namespace = namespace
    test_runner.remote_path = remote_path
    test_runner.browser_strategy = browser_strategy
    test_runner.browser_url = browser_url

    # Initial sync
    test_runner.sync_and_trigger()

    def on_change(path):
        test_runner.sync_and_trigger(path)

    observer = start_watcher(target_dir, on_change, blocking=blocking)

    if not blocking:
        register_loop(target_dir, observer)
        return observer
