import time

from aether_lens.core.domain.models import (
    PipelineLogEvent,
    TestFinishedEvent,
    TestStartedEvent,
)
from aether_lens.core.presentation.logging import PipelineFormatter
from aether_lens.daemon.repository.environments import LocalEnvironment


class TestExecutor:
    def __init__(self, target_dir, event_emitter=None, environment=None):
        self.target_dir = target_dir
        self.event_emitter = event_emitter
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
            success, output, artifact = await env.run_command(
                path_or_cmd, cwd=self.target_dir
            )

        status = "PASSED" if success else "FAILED"
        if self.event_emitter:
            log_message = PipelineFormatter.format_log(label, status, output)
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
