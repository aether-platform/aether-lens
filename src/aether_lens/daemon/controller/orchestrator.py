import asyncio
from pathlib import Path

from aether_lens.daemon.controller.execution import ExecutionController
from aether_lens.daemon.controller.watcher import start_watcher
from aether_lens.daemon.repository.session import LocalLensLoopHandler


class AetherOrchestrator:
    """
    Higher-level orchestrator that coordinates between watching and execution.
    """

    def __init__(self, execution_ctrl: ExecutionController):
        self.execution_ctrl = execution_ctrl
        self.execution_ctrl.orchestrator = self
        self._watchers = {}  # target_dir -> observer

    async def start_background_process(self, command, cwd=None):
        return await self.execution_ctrl.start_background_process(command, cwd=cwd)

    async def run_deployment_hook(self, command, cwd=None):
        return await self.execution_ctrl.run_deployment_hook(command, cwd=cwd)

    async def wait_for_health_check(self, url, timeout=30, event_emitter=None):
        return await self.execution_ctrl.wait_for_health_check(
            url, timeout=timeout, event_emitter=event_emitter
        )

    async def start_watch(self, target_dir: str, strategy="auto", interactive=True):
        """Start a local watch-and-run loop."""
        target_path = Path(target_dir).resolve()
        target_dir_str = str(target_path)

        if target_dir_str in self._watchers:
            return self._watchers[target_dir_str]

        loop = asyncio.get_running_loop()

        async def _on_watch_change(path):
            await self.execution_ctrl.run_pipeline(
                target_dir=str(target_path), strategy=strategy, interactive=interactive
            )

        def on_change(path):
            # No need for complex logic here, WatchController will handle thread-safety
            # But we wrap it in a task just in case it's not a coroutine
            loop.create_task(_on_watch_change(path))

        observer = start_watcher(
            str(target_path), on_change, blocking=False, orchestrator=self, loop=loop
        )
        self._watchers[target_dir_str] = observer

        if self.execution_ctrl.lifecycle_registry:
            self.execution_ctrl.lifecycle_registry.register(str(target_path), observer)
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
        target_path = Path(target_dir).resolve()

        handler = LocalLensLoopHandler(
            target_dir=str(target_path),
            pod_name=pod_name,
            namespace=namespace,
            remote_path=remote_path,
            browser_strategy=browser_strategy,
            browser_url=browser_url,
        )

        # Initial sync
        await handler.sync_and_trigger()

        async def _on_sync_change(path):
            await handler.sync_and_trigger(path)

        def on_change(path):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_on_sync_change(path))
            except RuntimeError:
                asyncio.run(_on_sync_change(path))

        observer = start_watcher(
            str(target_path), on_change, blocking=False, orchestrator=self
        )
        if self.execution_ctrl.lifecycle_registry:
            self.execution_ctrl.lifecycle_registry.register(str(target_path), observer)
        return observer
