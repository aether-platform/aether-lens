import os
import signal
import time

from rich.console import Console
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .execution import ExecutionController

console = Console(stderr=True)


class WatchController(FileSystemEventHandler):
    """
    Unified controller for file watching and deployment lifecycle.
    Merges WatchService and watcher.py logic.
    """

    def __init__(
        self, target_dir, on_change_callback, debounce_seconds=2, execution_ctrl=None
    ):
        self.target_dir = target_dir
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self.execution_ctrl = execution_ctrl
        self.last_triggered = 0
        self.observer = None
        self.cleanup_data = None  # {"cmd": str, "proc": Popen}

    def on_any_event(self, event):
        if event.is_directory or event.event_type not in [
            "created",
            "modified",
            "deleted",
            "moved",
        ]:
            return

        if any(
            x in event.src_path
            for x in [".git", "node_modules", ".astro", "__pycache__"]
        ):
            return

        current_time = time.time()
        if (current_time - self.last_triggered) > self.debounce_seconds:
            console.print(f"[Watcher] Change detected: {event.src_path}")
            self.last_triggered = current_time
            self.on_change_callback(event.src_path)

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

    async def setup_deployment(self, target_dir, browser_strategy, config):
        """Logic for setting up the test environment (compose, kubectl, etc.)"""
        exec_ctrl = self.execution_ctrl
        if not exec_ctrl:
            exec_ctrl = ExecutionController(config={})  # Fallback

        deployment_config = config.get("deployment", {})
        current_env = browser_strategy.replace("-", "_")
        env_deploy = deployment_config.get(current_env)

        deploy_cmd = os.getenv("DEPLOY_COMMAND")
        cleanup_cmd = os.getenv("CLEANUP_COMMAND")
        health_check_url = config.get("health_check_url")

        if env_deploy and not deploy_cmd:
            deploy_type = env_deploy.get("type")
            health_check_url = env_deploy.get("health_check") or health_check_url
            if deploy_type == "compose":
                deploy_cmd = f"docker compose -f {env_deploy.get('file', 'docker-compose.yaml')} up -d {env_deploy.get('service', '')}"
                cleanup_cmd = f"docker compose -f {env_deploy.get('file', 'docker-compose.yaml')} down"
            elif deploy_type == "kubectl":
                manifests = env_deploy.get("manifests", [])
                if isinstance(manifests, list):
                    manifests = " ".join([f"-f {m}" for m in manifests])
                deploy_cmd = f"kubectl apply {manifests} -n {env_deploy.get('namespace', 'default')}"
                cleanup_cmd = f"kubectl delete {manifests} -n {env_deploy.get('namespace', 'default')}"

        if deploy_cmd:
            if env_deploy and env_deploy.get("background"):
                proc = exec_ctrl.start_background_process(
                    deploy_cmd, cwd=target_dir
                )  # Need to ensure this exists or is moved
                self.cleanup_data = {"cmd": cleanup_cmd, "proc": proc}
            else:
                success, _ = exec_ctrl.run_deployment_hook(deploy_cmd, cwd=target_dir)
                if not success:
                    raise RuntimeError("Deployment hook failed.")
                self.cleanup_data = {"cmd": cleanup_cmd, "proc": None}

            if health_check_url:
                if not await exec_ctrl.wait_for_health_check(health_check_url):
                    raise RuntimeError(f"Health check failed for {health_check_url}")

        return self.cleanup_data

    async def perform_cleanup(self, target_dir):
        if not self.cleanup_data:
            return

        cleanup_cmd = self.cleanup_data.get("cmd")
        proc = self.cleanup_data.get("proc")

        if proc:
            console.print(
                f"\n[Watcher] Stopping background process (PID: {proc.pid})..."
            )
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()

        if cleanup_cmd:
            exec_ctrl = self.execution_ctrl
            if not exec_ctrl:
                exec_ctrl = ExecutionController(config={})
            exec_ctrl.run_deployment_hook(cleanup_cmd, cwd=target_dir)

        self.cleanup_data = None


def start_watcher(target_dir, callback, blocking=True):
    ctrl = WatchController(target_dir, callback)
    return ctrl.start(blocking=blocking)
