import asyncio
import os

from aether_lens.daemon.controller.execution import ExecutionController
from aether_lens.daemon.controller.watcher import start_watcher
from aether_lens.daemon.repository.session import LocalLensLoopHandler


class AetherOrchestrator:
    """
    Higher-level orchestrator that coordinates between watching and execution.
    Eliminates circular dependencies between ExecutionController and WatchController.
    """

    def __init__(self, execution_ctrl: ExecutionController):
        self.execution_ctrl = execution_ctrl

    # Delegated methods for WatchController to use, preventing direct dependency on ExecutionController
    def start_background_process(self, command, cwd=None):
        return self.execution_ctrl.start_background_process(command, cwd=cwd)

    def run_deployment_hook(self, command, cwd=None):
        return self.execution_ctrl.run_deployment_hook(command, cwd=cwd)

    async def wait_for_health_check(self, url, timeout=30, event_emitter=None):
        return await self.execution_ctrl.wait_for_health_check(
            url, timeout=timeout, event_emitter=event_emitter
        )

    async def start_watch(self, target_dir, strategy="auto", use_tui=True):
        """Start a local watch-and-run loop."""
        target_dir = os.path.abspath(target_dir)

        async def _on_watch_change(path):
            await self.execution_ctrl.run_pipeline(
                target_dir=target_dir, strategy=strategy, use_tui=use_tui
            )

        def on_change(path):
            # Use the existing running loop or create a new one if needed
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_on_watch_change(path))
            except RuntimeError:
                asyncio.run(_on_watch_change(path))

        observer = start_watcher(
            target_dir, on_change, blocking=False, orchestrator=self
        )
        if self.execution_ctrl.lifecycle_registry:
            self.execution_ctrl.lifecycle_registry.register(target_dir, observer)
        return observer

    async def start_loop(
        self,
        target_dir,
        pod_name,
        namespace="aether-system",
        remote_path="/app/project",
        browser_strategy="inpod",
        browser_url=None,
    ):
        """Start a remote heavy development loop (Sync & Remote Test)."""
        target_dir = os.path.abspath(target_dir)

        handler = LocalLensLoopHandler(
            target_dir=target_dir,
            pod_name=pod_name,
            namespace=namespace,
            remote_path=remote_path,
            browser_strategy=browser_strategy,
            browser_url=browser_url,
        )

        # Initial sync
        handler.sync_and_trigger()

        def on_change(path):
            handler.sync_and_trigger(path)

        observer = start_watcher(
            target_dir, on_change, blocking=False, orchestrator=self
        )
        if self.execution_ctrl.lifecycle_registry:
            self.execution_ctrl.lifecycle_registry.register(target_dir, observer)
        return observer
