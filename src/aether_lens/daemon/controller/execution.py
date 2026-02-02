import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional

try:
    from python_on_whales import DockerClient
except ImportError:
    DockerClient = None

import httpx
import logfire
from rich.console import Console

from aether_lens.core.domain.events import CallbackTransport, EventEmitter
from aether_lens.core.domain.models import (
    PipelineLogEvent,
)
from aether_lens.core.presentation import report
from aether_lens.core.presentation.logging import PipelineFormatter
from aether_lens.core.presentation.tui import PipelineDashboard
from aether_lens.daemon.repository.discovery import ToolResolver
from aether_lens.daemon.repository.environments import (
    DockerEnvironment,
    K8sEnvironment,
    LocalEnvironment,
)
from aether_lens.daemon.repository.executor import TestExecutor

console = Console(stderr=True)


class ComposeProjectHandle:
    """Handle for an SDK-managed Docker Compose project."""

    def __init__(self, docker_client, config_files: Optional[List[str]] = None):
        self.docker_client = docker_client
        self.config_files = config_files

    def stop(self):
        """Synchronously stop the compose project (called by LifecycleRegistry)."""
        try:
            # We don't have a direct sync wrapper if we are in a thread,
            # but python-on-whales calls are sync.
            self.docker_client.compose.down(config_files=self.config_files)
        except Exception as e:
            self._emit_log(
                None, PipelineFormatter.format_warning(f"SDK Cleanup failed: {e}")
            )

    def terminate(self):
        """Alias for stop."""
        self.stop()


class ExecutionController:
    """
    Unified controller for test execution, merging ExecutionService and Pipeline orchestration.
    """

    def __init__(self, config, planner=None, lifecycle_registry=None):
        self.config = config
        self.planner = planner
        self.lifecycle_registry = lifecycle_registry
        self.cleanup_process = None
        self.orchestrator = None

    def stop_dev_loop(self, target_dir: str) -> bool:
        """Stop all background services for a target directory."""
        if not self.lifecycle_registry:
            return False
        target_dir = str(Path(target_dir).resolve())
        return self.lifecycle_registry.stop(target_dir)

    async def ensure_services(self, target_dir, config, event_emitter=None):
        """Start defined background services and wait for health checks."""
        services = config.get("services", [])
        if not services:
            return True

        # Global orchestration strategy (sdk is now the default)
        global_strategy = config.get("orchestration_strategy", "sdk")

        for svc in services:
            name = svc.get("name", "Unknown")
            command = svc.get("command")
            if not command:
                continue

            health_check = svc.get("health_check")
            # Local override for specific service strategy
            svc_strategy = svc.get("strategy", global_strategy)

            msg = PipelineFormatter.format_service_start(name, command, svc_strategy)
            self._emit_log(event_emitter, msg)

            # NEW: Normalize binary name early to favor V2 (docker compose)
            if command.startswith("docker-compose"):
                command = command.replace("docker-compose", "docker compose", 1)

            # Pre-check tool presence using the normalized command
            tool_ok, tool_err = await ToolResolver.check_tool_presence(command)
            if not tool_ok:
                err_msg = PipelineFormatter.format_error(
                    f"{tool_err}. Please ensure the tool is installed."
                )
                self._emit_log(event_emitter, err_msg)
                return False

            # Execution Dispatch based on strategy
            if svc_strategy == "sdk":
                proc = await self._start_via_sdk(command, cwd=target_dir)
            else:
                proc = await self.start_background_process(command, cwd=target_dir)

            if proc:
                if self.lifecycle_registry:
                    self.lifecycle_registry.register(target_dir, proc)

                if health_check:
                    timeout = svc.get("timeout_seconds", 30)
                    if not await self.wait_for_health_check(
                        health_check, timeout=timeout, event_emitter=event_emitter
                    ):
                        return False
            else:
                return False
        return True

    async def _start_via_sdk(self, command: str, cwd: str = None):
        """Start a service via the Python-on-Whales SDK."""
        if not DockerClient:
            self._emit_log(
                None,
                PipelineFormatter.format_error(
                    "'python-on-whales' library not installed. Falling back to CLI."
                ),
            )
            return await self.start_background_process(command, cwd=cwd)

        self._emit_log(None, PipelineFormatter.format_sdk_orchestration_message())
        try:
            docker_client = DockerClient()

            if "compose" in command:
                # Use the SDK to manage compose projects.
                project_dir = Path(cwd) if cwd else Path.cwd()
                compose_files = []

                # Smart discovery of compose files
                # 1. Check for -f/--file in command
                m = re.search(r"-f\s+([^\s]+)", command) or re.search(
                    r"--file\s+([^\s]+)", command
                )
                if m:
                    compose_files = [m.group(1)]
                else:
                    # 2. Check standard locations
                    for f in [
                        "docker-compose.yml",
                        "docker-compose.yaml",
                        "compose.yml",
                        "compose.yaml",
                    ]:
                        if (project_dir / f).exists():
                            compose_files.append(str(project_dir / f))
                            break

                action = "up"
                if "down" in command:
                    action = "down"

                if action == "up":
                    await asyncio.to_thread(
                        docker_client.compose.up,
                        detach=True,
                        config_files=compose_files if compose_files else None,
                    )
                    # Return a handle for LifecycleRegistry to cleanup later
                    return ComposeProjectHandle(docker_client, compose_files)
                else:
                    await asyncio.to_thread(
                        docker_client.compose.down,
                        config_files=compose_files if compose_files else None,
                    )
                    return True

            return await self.start_background_process(command, cwd=cwd)
        except Exception as e:
            self._emit_log(
                None,
                PipelineFormatter.format_warning(
                    f"SDK failed: {e}. Falling back to CLI."
                ),
            )
            return await self.start_background_process(command, cwd=cwd)

    async def start_background_process(self, command, cwd=None):
        """Start a background process using asyncio."""
        # Standardize on V2
        if command.startswith("docker-compose"):
            command = command.replace("docker-compose", "docker compose", 1)

        try:
            return await asyncio.create_subprocess_shell(command, cwd=cwd)
        except Exception as e:
            self._emit_log(
                None,
                PipelineFormatter.format_error(
                    f"Error starting background process: {e}"
                ),
            )
            return None

    def load_config(self, target_dir: str, overrides: Optional[dict] = None) -> dict:
        """Load and merge configuration from file and overrides."""
        config_path = Path(target_dir) / "aether-lens.config.json"
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except Exception as e:
                self._emit_log(
                    None,
                    PipelineFormatter.format_warning(
                        f"Failed to load config file: {e}"
                    ),
                )

        if overrides:
            config.update({k: v for k, v in overrides.items() if v is not None})

        # Set defaults if missing
        config.setdefault("strategy", "auto")
        config.setdefault("execution_env", "local")
        return config

    def _create_execution_environment(self, config: dict, target_dir: str):
        """Factory method to create the appropriate execution environment."""
        env_type = config.get("execution_env", "local")

        if env_type == "docker":
            docker_conf = config.get("docker_config", {})
            return DockerEnvironment(
                service_name=docker_conf.get("service_name", "app"),
                project_dir=target_dir,
            )
        elif env_type == "k8s":
            k8s_conf = config.get("k8s_config", {})
            return K8sEnvironment(
                pod_name=k8s_conf.get("pod_name"),
                namespace=k8s_conf.get("namespace", "default"),
                container=k8s_conf.get("container", "aether-lens"),
            )
        return LocalEnvironment()

    def save_test_session(self, target_dir, results, strategy):
        """Save run results to a unified history directory."""
        history_dir = Path(target_dir) / ".aether" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        session_id = str(uuid.uuid4())[:8]
        timestamp = int(time.time())
        filename = f"run_{timestamp}_{session_id}.json"

        data = {
            "session_id": session_id,
            "timestamp": timestamp,
            "strategy": strategy,
            "results": results,
        }

        with open(history_dir / filename, "w") as f:
            json.dump(data, f, indent=2)

        # Also update 'latest.json'
        with open(history_dir / "latest.json", "w") as f:
            json.dump(data, f, indent=2)

        self._emit_log(None, PipelineFormatter.format_session_saved(filename))

    async def run_deployment_hook(self, command, cwd=None):
        """Run an arbitrary command in a subprocess for deployment/setup."""
        if not command:
            return True, "No command provided"
        self._emit_log(None, PipelineFormatter.format_deployment_hook_start(command))
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                self._emit_log(None, PipelineFormatter.format_deployment_hook_success())
                return True, stdout.decode().strip()
            else:
                err = stderr.decode().strip()
                self._emit_log(
                    None, PipelineFormatter.format_deployment_hook_failure(err)
                )
                return False, err
        except Exception as e:
            self._emit_log(
                None, PipelineFormatter.format_error(f"Deployment Error: {e}")
            )
            return False, str(e)

    async def wait_for_health_check(self, url, timeout=30, event_emitter=None):
        if not url:
            return True

        msg = PipelineFormatter.format_health_check_start(url)
        self._emit_log(event_emitter, msg)

        start_time = time.time()
        async with httpx.AsyncClient(trust_env=False) as client:
            while time.time() - start_time < timeout:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        ok_msg = PipelineFormatter.format_health_check_success()
                        self._emit_log(event_emitter, ok_msg)
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1)

        err_msg = PipelineFormatter.format_health_check_timeout()
        self._emit_log(event_emitter, err_msg)
        return False

    async def get_git_diff(self, target_dir):
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "HEAD",
                cwd=target_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode().strip()
        except Exception:
            return ""

    @logfire.instrument("Aether Lens Pipeline")
    async def run_pipeline(
        self,
        target_dir: str,
        strategy: str = "auto",
        app_url: str = None,
        interactive: bool = False,
        event_emitter: EventEmitter = None,
        context: str = "watch",
        auto_watch: bool = False,
        custom_instruction: str = None,
        **kwargs,
    ):
        """Unified entry point for the pipeline flow."""
        target_dir = str(Path(target_dir or ".").resolve())

        try:
            # Phase 1: Preparation
            self._emit_phase_log(event_emitter, "PREPARATION")
            if auto_watch and self.orchestrator:
                await self.orchestrator.start_watch(
                    target_dir,
                    strategy=strategy,
                    interactive=interactive,
                    event_emitter=event_emitter,
                )

            config = self.load_config(
                target_dir, overrides=kwargs
            )  # Use kwargs for overrides
            env_runner = self._create_execution_environment(config, target_dir)

            # Unified Intro message
            self._emit_log(
                event_emitter,
                PipelineFormatter.get_intro_panel(target_dir, config["strategy"]),
            )

            if not await self._prepare_services(target_dir, config, event_emitter):
                return

            # Phase 2: Analysis & Selection
            diff = "" if context == "cli" else await self.get_git_diff(target_dir)
            if context != "cli" and not diff:
                self._emit_log(
                    event_emitter,
                    PipelineFormatter.format_warning(
                        "No changes detected. Skipping analysis."
                    ),
                )
                return

            self._emit_phase_log(event_emitter, "ANALYSIS")
            analysis = self.planner.run_analysis(
                diff, context, config["strategy"], custom_instruction
            )
            all_tests = analysis.get("recommended_tests", [])

            if not all_tests:
                self._emit_log(
                    event_emitter,
                    PipelineFormatter.format_warning(
                        "No tests recommended. Using fallback audit."
                    ),
                )
                all_tests = [self._get_fallback_test()]

            # Phase 3: Quality Guard
            all_tests = self._inject_quality_tests(config, all_tests, event_emitter)

            # Phase 4: Execution
            self._emit_phase_log(event_emitter, "EXECUTION")
            results = await self._execute_tests(
                all_tests,
                config["strategy"],
                target_dir,
                event_emitter,
                config.get("app_url"),
                interactive,
                environment=env_runner,
            )

            # Phase 5: Result Persistence & Reporting
            self.save_test_session(target_dir, results, config["strategy"])
            if config.get("allure_strategy") != "none":
                report.export_to_allure(results, target_dir)

            return results
        finally:
            if context == "cli":
                self._emit_phase_log(event_emitter, "CLEANUP")
                self.stop_dev_loop(target_dir)

    async def _prepare_services(self, target_dir, config, event_emitter):
        """Handle service orchestration and deployment hooks."""
        if not await self.ensure_services(
            target_dir, config, event_emitter=event_emitter
        ):
            self._emit_error_log(event_emitter, "Service Orchestration failed.")
            return False

        deploy_conf = config.get("deployment", {}).get(
            config.get("execution_env", "local")
        )
        if deploy_conf:
            cmd = deploy_conf.get("command")
            if cmd:
                success, msg = await self.run_deployment_hook(cmd, cwd=target_dir)
                if not success:
                    self._emit_error_log(
                        event_emitter, f"Deployment Hook failed: {msg}"
                    )
                    return False

            hc = deploy_conf.get("health_check")
            if hc and not await self.wait_for_health_check(
                hc, event_emitter=event_emitter
            ):
                self._emit_error_log(event_emitter, "Health check failed.")
                return False
        return True

    def _inject_quality_tests(self, config, tests, event_emitter):
        """Add quality guard tests (Ruff, SonarQube) if enabled."""
        q_conf = config.get("quality_checks", {"enabled": True, "providers": ["ruff"]})
        if not q_conf.get("enabled"):
            return tests

        self._emit_phase_log(event_emitter, "QUALITY GUARD")
        q_tests = []
        for provider in q_conf.get("providers", []):
            if provider == "ruff":
                q_tests.append(
                    {
                        "type": "command",
                        "label": "Quality Guard (Ruff)",
                        "command": "ruff check . && ruff format --check .",
                        "execution_env": "local",
                    }
                )
            elif provider == "sonarqube":
                q_tests.append(
                    {
                        "type": "command",
                        "label": "Quality Guard (SonarQube)",
                        "command": "npx -y sonarqube-scanner",
                        "execution_env": "local",
                    }
                )
        return q_tests + tests

    def _get_fallback_test(self):
        return {
            "type": "command",
            "label": "Site Health Audit",
            "command": "python3 -m aether_lens.daemon.repository.runner site_audit",
            "execution_env": "local",
        }

    def _emit_log(self, event_emitter, message):
        """Unified logging to both console and event emitter."""
        if isinstance(message, str):
            console.print(message)
        else:
            # Handle Rich objects (like Panels)
            console.print(message)
            # If it's a Panel, we might want to extract text for the emitter,
            # but for now, we'll just skip detailed emission for complex objects
            if not hasattr(message, "render"):
                return

        if event_emitter and isinstance(message, str):
            event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=message)
            )

    async def _execute_tests(
        self,
        tests,
        strategy,
        target_dir,
        event_emitter,
        app_url,
        use_tui,
        environment=None,
    ):
        results = []

        async def run_core(app_instance=None):
            nonlocal results
            current_emitter = event_emitter
            if use_tui and app_instance:
                current_emitter = event_emitter or EventEmitter(
                    transports=[
                        CallbackTransport(
                            callback=lambda e: self._handle_event_for_tui(
                                e, app_instance
                            )
                        )
                    ]
                )

            executor = TestExecutor(
                target_dir,
                current_emitter,
                environment=environment,
            )
            tasks = [executor.execute_test(t, strategy, app_url) for t in tests]
            results = await asyncio.gather(*tasks)
            return results

        if use_tui and not event_emitter:
            app = PipelineDashboard(tests, strategy_name=strategy)
            app.run_logic_callback = run_core

            async def run_with_dashboard():
                await app.run_async()

            await run_with_dashboard()
        else:
            await run_core()
        return results

    def _handle_event_for_tui(self, event, app):
        if hasattr(event, "type"):
            etype = getattr(event, "type")
        else:
            return

        if etype == "test_started":
            label = getattr(event, "label", "Unknown")
            app.update_test_status(label, test_status="running")
            app.log_message(f"[blue]Starting:[/blue] {label}")
        elif etype == "test_progress":
            label = getattr(event, "label", "Unknown")
            status_text = getattr(event, "status_text", "")
            app.update_test_status(label, test_status=status_text)
        elif etype == "test_finished":
            label = getattr(event, "label", "Unknown")
            status = getattr(event, "status", "UNKNOWN")
            status_color = "bold green" if status == "PASSED" else "bold red"
            display_status = f"[{status_color}]{status}[/{status_color}]"
            app.update_test_status(label, test_status=display_status)
            app.log_message(f"[{status_color}]Finished:[/{status_color}] {label}")
        elif etype == "log":
            message = getattr(event, "message", "")
            app.log_message(message)

    def _emit_phase_log(self, event_emitter, phase: str):
        msg = PipelineFormatter.format_phase(phase)
        self._emit_log(event_emitter, msg)

    def _emit_error_log(self, event_emitter, message: str):
        msg = PipelineFormatter.format_error(message)
        self._emit_log(event_emitter, msg)
