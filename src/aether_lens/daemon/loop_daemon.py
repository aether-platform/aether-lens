from rich.console import Console

from aether_lens.core.session import LocalLensLoopHandler
from aether_lens.core.watcher import start_watcher
from aether_lens.daemon.registry import register_loop

console = Console(stderr=True)


def run_loop_daemon(
    target_dir,
    pod_name,
    namespace,
    remote_path,
    blocking=True,
    browser_strategy="inpod",
    browser_url=None,
):
    """
    Starts the loop daemon that watches for changes and triggers sync.
    """
    console.print(f" -> Local Dir: {target_dir}")
    console.print(f" -> Remote Pod: {namespace}/{pod_name}")
    console.print(f" -> Remote Path: {remote_path}")
    console.print(f" -> Browser Strategy: {browser_strategy}")

    handler = LocalLensLoopHandler(
        target_dir,
        pod_name,
        namespace,
        remote_path,
        browser_strategy=browser_strategy,
        browser_url=browser_url,
    )

    # Initial sync
    handler.sync_and_trigger()

    def on_change(path):
        handler.sync_and_trigger(path)

    observer = start_watcher(target_dir, on_change, blocking=blocking)

    if not blocking:
        register_loop(target_dir, observer)
        return observer
