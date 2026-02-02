import time

from playwright.async_api import async_playwright

from aether_lens.core.domain.models import (
    PipelineLogEvent,
    TestFinishedEvent,
    TestStartedEvent,
)
from aether_lens.daemon.repository.environments import LocalEnvironment

from .runner import VisualTestRunner


class TestExecutor:
    def __init__(
        self, target_dir, event_emitter=None, test_runner=None, environment=None
    ):
        self.target_dir = target_dir
        self.event_emitter = event_emitter
        self.test_runner = test_runner
        self.environment = environment or LocalEnvironment()

    async def execute_test(self, test, strategy, app_url):
        test_type = test.get("type", "command")
        label = test.get("label")
        path_or_cmd = test.get("path") or test.get("command")

        if self.event_emitter:
            self.event_emitter.emit(
                TestStartedEvent(
                    type="test_started",
                    timestamp=time.time(),
                    label=label,
                    test_type=test_type,
                    strategy=strategy,
                )
            )

        success, error, artifact = False, None, None
        if test_type == "command":
            if self.event_emitter:
                self.event_emitter.emit(
                    PipelineLogEvent(
                        type="log",
                        timestamp=time.time(),
                        message=f" -> [dim]Executing command:[/dim] {path_or_cmd}",
                    )
                )
            success, error, artifact = await self._run_command(path_or_cmd, label)
        elif test_type == "visual":
            if self.event_emitter:
                self.event_emitter.emit(
                    PipelineLogEvent(
                        type="log",
                        timestamp=time.time(),
                        message=f" -> [dim]Starting Playwright for:[/dim] {label}",
                    )
                )
            runner = self.test_runner or VisualTestRunner(
                base_url=app_url, current_dir=self.target_dir
            )
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    success, error, artifact = await runner.run_visual_test(
                        page, label=label, path_url=path_or_cmd, test_id_key=label
                    )
                    await browser.close()
            except Exception as e:
                success, error = False, f"Visual Test Error: {e}"

        status = "PASSED" if success else "FAILED"
        if self.event_emitter:
            log_message = f" -> Test '{label}' {status}"
            if error:
                log_message += f": [red]{error}[/red]"

            self.event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=log_message)
            )

            self.event_emitter.emit(
                TestFinishedEvent(
                    type="test_finished",
                    timestamp=time.time(),
                    label=label,
                    status=status,
                    error=error,
                    artifact=artifact,
                )
            )

        return {
            "type": test_type,
            "label": label,
            "status": status,
            "error": error,
            "artifact": artifact,
            "strategy": strategy,
        }

    async def _run_command(self, command, label="unknown"):
        success, error, artifact = await self.environment.run_command(
            command, cwd=self.target_dir
        )

        # Specialized error handling for common quality tools
        if not success and error:
            if "not found" in error.lower() or "no such file" in error.lower():
                if "ruff" in command:
                    error = "Ruff not found. Please install it with 'pip install ruff'."
                elif "sonar-scanner" in command:
                    error = "sonar-scanner not found. Please ensure it is installed and in your PATH."

        return success, error, artifact
