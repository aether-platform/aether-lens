import threading
from typing import Any, Dict


class LifecycleRegistry:
    """
    DI-managed registry for active background processes (WATCH/LOOP).
    """

    def __init__(self):
        # target_dir -> list of handles
        self._active_resources: Dict[str, list] = {}
        self._lock = threading.Lock()

    def register(self, target_dir: str, handle: Any):
        """Register a background resource handle."""
        with self._lock:
            if target_dir not in self._active_resources:
                self._active_resources[target_dir] = []
            self._active_resources[target_dir].append(handle)

    def stop(self, target_dir: str) -> bool:
        """Stop and remove all background resource handles for a directory."""
        with self._lock:
            if target_dir in self._active_resources:
                handles = self._active_resources.pop(target_dir)
                for handle in handles:
                    try:
                        if hasattr(handle, "stop") and hasattr(handle, "join"):
                            # watchdog Observer
                            handle.stop()
                            handle.join()
                        elif hasattr(handle, "terminate"):
                            # Process handle (asyncio or subprocess)
                            handle.terminate()
                            # For sync processes, we might want to wait,
                            # but we can't await here easily without making stop async.
                    except Exception:
                        pass
                return True
            return False

    def list_active(self) -> list:
        """List all active target directories."""
        with self._lock:
            return list(self._active_resources.keys())

    def stop_all(self):
        """Stop all registered background processes."""
        targets = self.list_active()
        for t in targets:
            self.stop(t)
