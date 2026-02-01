import asyncio
import json
import os
import subprocess
import time

import httpx
import logfire
from rich.console import Console
from rich.panel import Panel

from aether_lens.core.domain.events import CallbackTransport, EventEmitter
from aether_lens.core.domain.models import (
    PipelineLogEvent,
    TestFinishedEvent,
    TestProgressEvent,
    TestStartedEvent,
)
from aether_lens.core.presentation import report
from aether_lens.core.presentation.tui import PipelineDashboard

console = Console(stderr=True)


class ExecutionController:
    """
    Unified controller for test execution, merging ExecutionService and Pipeline orchestration.
    """

    def __init__(self, config, test_runner=None, planner=None):
        self.config = config
        self.test_runner = test_runner
        self.planner = planner
        self.cleanup_process = None

    def start_background_process(self, command, cwd=None):
        console.print(
            f" -> [Execution] Starting background process: [cyan]{command}[/cyan]"
        )
        try:
            return subprocess.Popen(
                command,
                cwd=cwd,
                shell=True,
                preexec_fn=os.setsid,
            )
        except Exception as e:
            console.print(f"    - [red]Error starting background process:[/red] {e}")
            return None

    def load_config(self, target_dir):
        config_path = os.path.join(target_dir, "aether-lens.config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to load config file: {e}[/yellow]"
                )
        return {}

    def run_deployment_hook(self, command, cwd=None):
        if not command:
            return True, "No command provided"
        console.print(
            f" -> [Execution] Running deployment hook: [cyan]{command}[/cyan]"
        )
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                console.print("    - [green]Deployment OK[/green]")
                return True, result.stdout
            else:
                console.print(f"      {result.stderr.strip()}")
                return False, result.stderr
        except Exception as e:
            console.print(f"    - [red]Deployment Error:[/red] {e}")
            return False, str(e)

    async def wait_for_health_check(self, url, timeout=30):
        if not url:
            return True

        console.print(
            f" -> [Execution] Waiting for health check: [cyan]{url}[/cyan] ..."
        )
        start_time = time.time()

        async with httpx.AsyncClient() as client:
            while time.time() - start_time < timeout:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        console.print("    - [green]Health Check OK[/green]")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1)

        console.print("    - [red]Health Check Timeout[/red]")
        return False

    def get_git_diff(self, target_dir):
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=target_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except Exception:
            return ""

    @logfire.instrument("Aether Lens Pipeline")
    async def run_pipeline(
        self,
        target_dir=".",
        browser_url=None,
        context=None,
        rp_url=None,
        allure_dir=None,
        strategy="auto",
        custom_instruction=None,
        use_tui: bool = True,
        event_emitter: EventEmitter = None,
        close_browser: bool = True,
        app_url: str = None,
    ):
        target_dir = os.path.abspath(target_dir or ".")
        config = self.load_config(target_dir)

        strategy_disp = f"{strategy} (Custom)" if strategy == "custom" else strategy
        console.print(
            Panel(
                f"[bold blue]Aether Lens[/bold blue] Pipeline Triggered for [cyan]{target_dir}[/cyan] (Strategy: {strategy_disp})",
                expand=False,
            )
        )

        # 1. Deployment hooks
        deploy_conf = config.get("deployment", {}).get(
            config.get("browser_strategy", "local")
        )
        if deploy_conf:
            command = deploy_conf.get("command")
            if command:
                success, msg = self.run_deployment_hook(command, cwd=target_dir)
                if not success:
                    return

            health_check = deploy_conf.get("health_check")
            if health_check:
                if not await self.wait_for_health_check(health_check):
                    return

        # 2. Get diff
        diff = self.get_git_diff(target_dir)
        if not diff:
            console.print("[yellow]No changes detected. Skipping analysis.[/yellow]")
            # If no diff, we might still want to run some basic tests?
            # For now, let's just abort if no changes.
            return

        # AI Analysis
        strategy = strategy or config.get("strategy", "auto")

        strategies = (
            [s.strip() for s in strategy.split(",")]
            if isinstance(strategy, str)
            else strategy
        )
        if not strategies:
            strategies = ["auto"]

        all_tests = []
        seen_tests = set()

        for s in strategies:
            analysis = self.planner.run_analysis(diff, context, s, custom_instruction)
            recommended_tests = analysis.get("recommended_tests", [])

            for test in recommended_tests:
                test_id = f"{test['type']}:{test['label']}:{test['command']}"
                if test_id not in seen_tests:
                    all_tests.append(test)
                    seen_tests.add(test_id)

        if not all_tests:
            console.print("[yellow]No tests recommended for current changes.[/yellow]")
            return

        # Execution
        if use_tui:
            results = await self._run_with_tui(
                all_tests, strategy, target_dir, event_emitter, app_url
            )
        else:
            results = await self._run_headless(
                all_tests, strategy, target_dir, event_emitter, app_url
            )

        # Reporting
        allure_strategy = config.get("allure_strategy", "none")
        if allure_strategy != "none":
            report.export_to_allure(results, target_dir)

        # Cleanup process if any
        if self.cleanup_process and close_browser:
            try:
                os.killpg(os.getpgid(self.cleanup_process.pid), 15)
            except Exception:
                pass

        return results

    async def _run_headless(self, tests, strategy, target_dir, event_emitter, app_url):
        from aether_lens.daemon.repository.executor import TestExecutor

        executor = TestExecutor(target_dir, event_emitter, test_runner=self.test_runner)
        tasks = [executor.execute_test(t, strategy, app_url) for t in tests]
        return await asyncio.gather(*tasks)

    async def _run_with_tui(self, tests, strategy, target_dir, event_emitter, app_url):
        app = PipelineDashboard(tests, strategy_name=strategy)
        results = []

        @logfire.instrument("Visual Test Execution")
        async def run_tests(app_instance):
            nonlocal results
            from aether_lens.daemon.repository.executor import TestExecutor

            tui_emitter = event_emitter or EventEmitter(
                transports=[
                    CallbackTransport(
                        callback=lambda e: self._handle_event_for_tui(e, app_instance)
                    )
                ]
            )
            executor = TestExecutor(
                target_dir, tui_emitter, test_runner=self.test_runner
            )
            tasks = [executor.execute_test(t, strategy, app_url) for t in tests]
            results = await asyncio.gather(*tasks)
            return results

        app.run_logic_callback = run_tests
        await app.run_async()
        return results

    def _handle_event_for_tui(self, event, app):
        if isinstance(event, TestStartedEvent):
            app.set_test_status(event.test_id, "running")
            app.log_message(f"[blue]Starting:[/blue] {event.label}")
        elif isinstance(event, TestProgressEvent):
            app.set_test_progress(event.test_id, event.progress)
        elif isinstance(event, TestFinishedEvent):
            status = "passed" if event.success else "failed"
            app.set_test_status(event.test_id, status)
            color = "green" if status == "passed" else "red"
            app.log_message(f"[{color}]Finished:[/color] {event.label} ({status})")
        elif isinstance(event, PipelineLogEvent):
            app.log_message(event.message)
