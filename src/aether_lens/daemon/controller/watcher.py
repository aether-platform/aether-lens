import asyncio
import time

from rich.console import Console
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

console = Console(stderr=True)


class WatchController(FileSystemEventHandler):
    """
    Unified controller for file watching and deployment lifecycle.
    """

    def __init__(
        self,
        target_dir,
        on_change_callback,
        debounce_seconds=2,
        orchestrator=None,
        loop=None,
    ):
        self.target_dir = target_dir
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self.orchestrator = orchestrator
        self.loop = loop or asyncio.get_event_loop()
        self.last_triggered = 0
        self.observer = None

    def on_any_event(self, event):
        if event.is_directory or event.event_type not in [
            "created",
            "modified",
            "deleted",
            "moved",
        ]:
            return

        # Simple ignore list
        if any(
            x in event.src_path
            for x in [".git", "node_modules", ".astro", "__pycache__", ".aether"]
        ):
            return

        console.print(f"[Watcher] Event: {event.event_type} on {event.src_path}")
        current_time = time.time()
        if (current_time - self.last_triggered) > self.debounce_seconds:
            console.print(f"[Watcher] TRIGGERING callback for {event.src_path}")
            self.last_triggered = current_time

            if asyncio.iscoroutinefunction(self.on_change_callback):
                asyncio.run_coroutine_threadsafe(
                    self.on_change_callback(event.src_path), self.loop
                )
            else:
                self.loop.call_soon_threadsafe(
                    lambda: self.on_change_callback(event.src_path)
                )

    def start(self, blocking=True):
        self.observer = Observer()
        self.observer.schedule(self, self.target_dir, recursive=True)
        self.observer.start()
        console.print(f"[Watcher] Watching {self.target_dir} for changes...")

        if not blocking:
            return self.observer

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()


def start_watcher(target_dir, callback, blocking=True, orchestrator=None, loop=None):
    ctrl = WatchController(target_dir, callback, orchestrator=orchestrator, loop=loop)
    return ctrl.start(blocking=blocking)
