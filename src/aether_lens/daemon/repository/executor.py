import time

from rich.markup import escape
from rich.text import Text

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

        success, output, artifact = False, None, None
        env = self.environment
        if test.get("execution_env") == "local" and not isinstance(
            env, LocalEnvironment
        ):
            env = LocalEnvironment()

        if test_type == "command":
            if self.event_emitter:
                self.event_emitter.emit(
                    PipelineLogEvent(
                        type="log",
                        timestamp=time.time(),
                        message=f" -> [dim]Executing command:[/dim] {path_or_cmd}",
                    )
                )
            # Use the resolved environment (potentially overridden to local)
            success, output, artifact = await env.run_command(
                path_or_cmd, cwd=self.target_dir
            )
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
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    success, output, artifact = await runner.run_visual_test(
                        page, label=label, path_url=path_or_cmd, test_id_key=label
                    )
                    await browser.close()
            except Exception as e:
                success, output = False, f"Visual Test Error: {e}"

        status = "PASSED" if success else "FAILED"
        status_color = "bold green" if success else "bold red"

        if self.event_emitter:
            log_message = (
                f" -> Test '{label}' [{status_color}]{status}[/{status_color}]"
            )
            if output:
                # Convert output to Rich markup with ANSI support or escaping
                try:
                    # If it's a string, try parsing ANSI codes
                    if isinstance(output, str):
                        rich_text = Text.from_ansi(output)
                        # If there were ANSI codes, use markup. If not, escape to be safe.
                        if "\x1b[" in output:
                            formatted_output = rich_text.markup
                        else:
                            formatted_output = escape(output)
                    else:
                        formatted_output = escape(str(output))

                    output_color = "dim" if success else "red"
                    log_message += (
                        f": [{output_color}]{formatted_output}[/{output_color}]"
                    )
                except Exception:
                    # Fallback to simple escaping if anything goes wrong
                    log_message += f": [dim]{escape(str(output))}[/dim]"

            self.event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=log_message)
            )

            self.event_emitter.emit(
                TestFinishedEvent(
                    type="test_finished",
                    timestamp=time.time(),
                    label=label,
                    status=status,
                    error=None if success else output,
                    artifact=artifact,
                )
            )

        return {
            "type": test_type,
            "label": label,
            "status": status,
            "error": None if success else output,
            "artifact": artifact,
            "strategy": strategy,
        }
