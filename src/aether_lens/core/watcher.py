import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class LensLoopHandler(FileSystemEventHandler):
    def __init__(self, target_dir, on_change_callback):
        self.target_dir = target_dir
        self.on_change_callback = on_change_callback
        self.last_triggered = 0
        self.debounce_seconds = 2

    def on_any_event(self, event):
        if event.is_directory:
            return

        if event.event_type not in ["created", "modified", "deleted", "moved"]:
            return

        self._process(event)

    def _process(self, event):
        if event.is_directory:
            return

        # フィルタリング (例: .git, node_modules, temp files)
        if any(
            x in event.src_path
            for x in [".git", "node_modules", ".astro", "__pycache__"]
        ):
            return

        current_time = time.time()
        if (current_time - self.last_triggered) > self.debounce_seconds:
            print(f"[Lens Loop] Change detected: {event.src_path}")
            self.last_triggered = current_time
            self.on_change_callback(event.src_path)


def start_watcher(target_dir, callback, blocking=True):
    event_handler = LensLoopHandler(target_dir, callback)
    observer = Observer()
    observer.schedule(event_handler, target_dir, recursive=True)
    observer.start()
    print(f"[Lens Loop] Watching {target_dir} for changes...")

    if not blocking:
        return observer

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
