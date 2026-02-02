import asyncio
import json
import platform
import re
import time
import uuid
from os import environ
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from python_on_whales import DockerClient
except ImportError:
    DockerClient = None

import httpx
import logfire
from rich.console import Console
from rich.panel import Panel

from aether_lens.core.domain.events import CallbackTransport, EventEmitter
from aether_lens.core.domain.models import (
    PipelineLogEvent,
)
from aether_lens.core.presentation import report
from aether_lens.core.presentation.tui import PipelineDashboard
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
            console.print(f"    - [yellow]Warning: SDK Cleanup failed:[/yellow] {e}")

    def terminate(self):
        """Alias for stop."""
        self.stop()


class ExecutionController:
    """
    Unified controller for test execution, merging ExecutionService and Pipeline orchestration.
    """

    def __init__(self, config, test_runner=None, planner=None, lifecycle_registry=None):
        self.config = config
        self.test_runner = test_runner
        self.planner = planner
        self.lifecycle_registry = lifecycle_registry
        self.cleanup_process = None

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

            msg = f" -> [Management] Starting service: [cyan]{name}[/cyan] ({command}) [Strategy: {svc_strategy}]"
            console.print(msg)

            # NEW: Normalize binary name early to favor V2 (docker compose)
            if command.startswith("docker-compose"):
                command = command.replace("docker-compose", "docker compose", 1)

            # Pre-check tool presence using the normalized command
            tool_ok, tool_err = self._check_tool_presence(command)
            if not tool_ok:
                err_msg = f"    - [red]Error:[/red] {tool_err}. Please ensure the tool is installed."
                console.print(err_msg)
                if event_emitter:
                    event_emitter.emit(
                        PipelineLogEvent(
                            type="log", timestamp=time.time(), message=err_msg
                        )
                    )
                return False

            if event_emitter:
                event_emitter.emit(
                    PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
                )

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
            console.print(
                "    - [red]Error:[/red] 'python-on-whales' library not installed. Falling back to CLI."
            )
            return await self.start_background_process(command, cwd=cwd)

        console.print(
            "    - [cyan][SDK][/cyan] Orchestrating via Python-on-Whales SDK..."
        )
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
            console.print(
                f"    - [yellow]SDK failed: {e}. Falling back to CLI.[/yellow]"
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
            console.print(f"    - [red]Error starting background process:[/red] {e}")
            return None

    def _check_tool_presence(self, command: str) -> Tuple[bool, str]:
        """Check if the required tool is available using Path."""
        if not command:
            return True, ""

        words = command.split()
        first_word = words[0]

        # Handling 'docker compose' as a single tool concept
        if first_word == "docker" and len(words) > 1 and words[1] == "compose":
            if self._find_executable("docker"):
                return True, ""
            return False, "Command 'docker' (required for 'docker compose') not found."

        if self._find_executable(first_word):
            return True, ""
        return False, f"Command '{first_word}' not found in PATH."

    def _find_executable(self, name):
        """Path-based replacement for which."""
        if not name:
            return None

        # Handle absolute or relative paths directly
        path_name = Path(name)
        if path_name.is_absolute() and path_name.exists() and not path_name.is_dir():
            return str(path_name)

        env_path = environ.get("PATH", "")
        # Handle platform-specific path separators
        sep = ";" if platform.system() == "Windows" else ":"
        for p in env_path.split(sep):
            if not p:
                continue
            file_path = Path(p.strip('"')) / name
            if file_path.exists() and not file_path.is_dir():
                return str(file_path)
            if platform.system() == "Windows":
                exe_path = file_path.with_suffix(".exe")
                if exe_path.exists() and not exe_path.is_dir():
                    return str(exe_path)
        return None

    def load_config(self, target_dir, overrides=None):
        config_path = Path(target_dir) / "aether-lens.config.json"
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to load config file: {e}[/yellow]"
                )

        if overrides:
            config.update({k: v for k, v in overrides.items() if v is not None})

        browser_strategy = config.get("browser_strategy", "local")
        browser_url = config.get("browser_url")

        if not browser_url:
            if browser_strategy == "docker":
                browser_url = "ws://localhost:9222"
            elif browser_strategy == "inpod":
                browser_url = environ.get(
                    "TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222"
                )

        config["browser_strategy"] = browser_strategy
        config["browser_url"] = browser_url
        return config

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

        console.print(f" -> [Execution] Session saved: [cyan]{filename}[/cyan]")

    async def run_deployment_hook(self, command, cwd=None):
        if not command:
            return True, "No command provided"
        console.print(
            f" -> [Execution] Running deployment hook: [cyan]{command}[/cyan]"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                console.print("    - [green]Deployment OK[/green]")
                return True, stdout.decode().strip()
            else:
                err = stderr.decode().strip()
                console.print(f"      {err}")
                return False, err
        except Exception as e:
            console.print(f"    - [red]Deployment Error:[/red] {e}")
            return False, str(e)

    async def wait_for_health_check(self, url, timeout=30, event_emitter=None):
        if not url:
            return True

        msg = f" -> [Management] Waiting for health check: [cyan]{url}[/cyan] ..."
        console.print(msg)
        if event_emitter:
            event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
            )

        start_time = time.time()
        async with httpx.AsyncClient(trust_env=False) as client:
            while time.time() - start_time < timeout:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        ok_msg = "    - [green]Health Check OK[/green]"
                        console.print(ok_msg)
                        if event_emitter:
                            event_emitter.emit(
                                PipelineLogEvent(
                                    type="log", timestamp=time.time(), message=ok_msg
                                )
                            )
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1)

        err_msg = "    - [red]Health Check Timeout[/red]"
        console.print(err_msg)
        if event_emitter:
            event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=err_msg)
            )
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
        target_dir = str(Path(target_dir or ".").resolve())

        try:
            # Phase 1: Preparation
            self._emit_phase_log(event_emitter, "PREPARATION")

            overrides = {
                "browser_url": browser_url,
                "strategy": strategy,
                "app_url": app_url,
            }
            config = self.load_config(target_dir, overrides=overrides)

            exec_env_type = config.get("execution_env", "local")

            if exec_env_type == "docker":
                docker_conf = config.get("docker_config", {})
                env_runner = DockerEnvironment(
                    service_name=docker_conf.get("service_name", "app"),
                    project_dir=target_dir,
                )
            elif exec_env_type == "k8s":
                k8s_conf = config.get("k8s_config", {})
                env_runner = K8sEnvironment(
                    pod_name=k8s_conf.get("pod_name"),
                    namespace=k8s_conf.get("namespace", "default"),
                    container=k8s_conf.get("container", "aether-lens"),
                )
            else:
                env_runner = LocalEnvironment()

            strategy = config.get("strategy", strategy)
            browser_url = config.get("browser_url")
            app_url = config.get("app_url", app_url)

            strategy_disp = f"{strategy} (Custom)" if strategy == "custom" else strategy
            intro_msg = f"[bold blue]Aether Lens[/bold blue] Pipeline Triggered for [cyan]{target_dir}[/cyan] (Strategy: {strategy_disp})"
            console.print(Panel(intro_msg, expand=False))
            if event_emitter:
                event_emitter.emit(
                    PipelineLogEvent(
                        type="log", timestamp=time.time(), message=intro_msg
                    )
                )

            if not await self.ensure_services(
                target_dir, config, event_emitter=event_emitter
            ):
                self._emit_error_log(
                    event_emitter,
                    "Service Orchestration failed during PREPARATION phase.",
                )
                return

            deploy_conf = config.get("deployment", {}).get(
                config.get("browser_strategy", "local")
            )
            if deploy_conf:
                command = deploy_conf.get("command")
                if command:
                    success, msg = await self.run_deployment_hook(
                        command, cwd=target_dir
                    )
                    if not success:
                        if event_emitter:
                            self._emit_error_log(
                                event_emitter,
                                f"Deployment Hook failed during PREPARATION phase: {msg}",
                            )
                        return

                health_check = deploy_conf.get("health_check")
                if health_check:
                    if not await self.wait_for_health_check(
                        health_check, event_emitter=event_emitter
                    ):
                        if event_emitter:
                            self._emit_error_log(
                                event_emitter,
                                "Health check failed during PREPARATION phase.",
                            )
                        return

            diff = ""
            if context == "cli":
                msg = " -> [Analysis] CLI context detected: Performing full test run (ignoring diff)."
                console.print(msg)
                if event_emitter:
                    event_emitter.emit(
                        PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
                    )
            else:
                diff = await self.get_git_diff(target_dir)
                if not diff:
                    msg = "[yellow]No changes detected. Skipping analysis.[/yellow]"
                    console.print(msg)
                    if event_emitter:
                        event_emitter.emit(
                            PipelineLogEvent(
                                type="log", timestamp=time.time(), message=msg
                            )
                        )
                    return

            # Phase 2: Analysis
            self._emit_phase_log(event_emitter, "ANALYSIS")
            analysis = self.planner.run_analysis(
                diff, context, strategy, custom_instruction
            )
            all_tests = analysis.get("recommended_tests", [])

            if not all_tests:
                msg = "[yellow]No tests recommended for current changes.[/yellow]"
                console.print(msg)
                if event_emitter:
                    event_emitter.emit(
                        PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
                    )
                # Fallback test should also run local
                all_tests = [
                    {
                        "type": "command",
                        "label": "Home Layout Check (Fallback)",
                        "command": "python3 -m aether_lens.core.runner layout_check",
                        "execution_env": "local",
                    }
                ]

            # Phase 3: Quality
            quality_conf = config.get(
                "quality_checks", {"enabled": True, "providers": ["ruff"]}
            )
            if quality_conf.get("enabled"):
                self._emit_phase_log(event_emitter, "QUALITY GUARD")
                quality_tests = []
                for provider in quality_conf.get("providers", []):
                    if provider == "ruff":
                        quality_tests.append(
                            {
                                "type": "command",
                                "label": "Quality Guard (Ruff)",
                                "command": "ruff check . && ruff format --check .",
                                "execution_env": "local",
                            }
                        )
                    elif provider == "sonarqube":
                        quality_tests.append(
                            {
                                "type": "command",
                                "label": "Quality Guard (SonarQube)",
                                "command": "sonar-scanner",
                                "execution_env": "local",
                            }
                        )
                all_tests = quality_tests + all_tests

            # Phase 4: Execution
            self._emit_phase_log(event_emitter, "EXECUTION")
            results = await self._execute_tests(
                all_tests,
                strategy,
                target_dir,
                event_emitter,
                app_url,
                use_tui,
                environment=env_runner,
            )

            self.save_test_session(target_dir, results, strategy)

            allure_strategy = config.get("allure_strategy", "none")
            if allure_strategy != "none":
                report.export_to_allure(results, target_dir)

            if self.cleanup_process and close_browser:
                try:
                    self.cleanup_process.terminate()
                except Exception:
                    pass

            return results
        finally:
            # One-shot CLI run should cleanup all services started.
            if context == "cli":
                self._emit_phase_log(event_emitter, "CLEANUP")
                self.stop_dev_loop(target_dir)

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
                test_runner=self.test_runner,
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

    def _emit_phase_log(self, event_emitter, phase_name: str):
        separator = "=" * 20
        msg = f"\n[bold yellow]{separator} PHASE: {phase_name} {separator}[/bold yellow]\n"
        console.print(msg)
        if event_emitter:
            event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
            )

    def _emit_error_log(self, event_emitter, message: str):
        msg = f"[bold red]ERROR:[/bold red] {message}"
        console.print(msg)
        if event_emitter:
            event_emitter.emit(
                PipelineLogEvent(type="log", timestamp=time.time(), message=msg)
            )
