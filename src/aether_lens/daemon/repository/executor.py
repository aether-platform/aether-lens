import asyncio
import time

from aether_lens.core.domain.models import TestFinishedEvent, TestStartedEvent


class TestExecutor:
    def __init__(self, target_dir, event_emitter=None, test_runner=None):
        self.target_dir = target_dir
        self.event_emitter = event_emitter
        self.test_runner = test_runner

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
            success, error, artifact = await self._run_command(path_or_cmd, label)
        elif test_type == "visual":
            from playwright.async_api import async_playwright

            from .runner import VisualTestRunner

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

    async def _run_command(self, command, label):
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.target_dir,
            )
            stdout, stderr = await proc.communicate()
            return (
                proc.returncode == 0,
                stdout.decode().strip() + "\n" + stderr.decode().strip(),
                None,
            )
        except Exception as e:
            return False, str(e), None
