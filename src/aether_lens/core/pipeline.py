import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from dependency_injector.wiring import Provide, inject
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from pixelmatch import pixelmatch
except ImportError:
    pixelmatch = None

from aether_lens.core import browser, report
from aether_lens.core.ai import run_analysis
from aether_lens.core.containers import Container
from aether_lens.core.events import CallbackTransport, EventEmitter
from aether_lens.core.models import (
    PipelineLogEvent,
    TestFinishedEvent,
    TestProgressEvent,
    TestStartedEvent,
)

console = Console(stderr=True)


# EventEmitter moved to .events for abstraction


def load_config(target_dir):
    config_path = os.path.join(target_dir, "aether-lens.config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load config file: {e}[/yellow]")
    return {}


def run_deployment_hook(command, cwd=None):
    if not command:
        return True, "No command provided"
    console.print(f" -> [Pipeline] Running deployment hook: [cyan]{command}[/cyan]")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            check=False,  # Allow manual error handling
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


def start_background_process(command, cwd=None):
    """Starts a process in the background and returns the Popen object."""
    if not command:
        return None
    console.print(f" -> [Pipeline] Starting background process: [cyan]{command}[/cyan]")
    try:
        # Popen to start without waiting
        # unix shell=True for complex commands
        process = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdout=subprocess.DEVNULL,  # Optionally redirect logging
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,  # Create new session group for cleaner kill
        )
        console.print(f"    - [green]Process Started (PID: {process.pid})[/green]")
        return process
    except Exception as e:
        console.print(f"    - [red]Start Error:[/red] {e}")
        return None
        return False, str(e)


async def wait_for_health_check(url, timeout=30):
    if not url:
        return True

    import httpx

    console.print(f" -> [Pipeline] Waiting for health check: [cyan]{url}[/cyan] ...")
    start_time = time.time()

    async with httpx.AsyncClient() as client:
        while time.time() - start_time < timeout:
            try:
                response = await client.get(url, timeout=2.0)
                if response.status_code < 400:
                    console.print("    - [green]Health Check OK[/green]")
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)

    console.print(f"    - [red]Health Check Timed Out after {timeout}s[/red]")
    return False


def get_git_diff(target_dir):
    try:
        result = subprocess.run(
            ["git", "-C", target_dir, "diff", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        if not result.stdout:
            result = subprocess.run(
                ["git", "-C", target_dir, "diff"],
                capture_output=True,
                text=True,
                check=True,
            )
        return result.stdout
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error getting git diff:[/bold red] {e}")
        return ""


def calculate_pixel_diff(img1_path, img2_path, diff_path):
    if not pixelmatch:
        return None, "pixelmatch not installed"

    img1 = Image.open(img1_path).convert("RGBA")
    img2 = Image.open(img2_path).convert("RGBA")

    if img1.size != img2.size:
        # Resize img2 to match img1 for comparison if different
        img2 = img2.resize(img1.size)

    width, height = img1.size
    diff_data = bytearray(width * height * 4)

    # pixelmatch(img1, img2, width, height, output, threshold=0.1, ...)
    try:
        mismatch = pixelmatch(
            img1.tobytes(), img2.tobytes(), width, height, diff_data, threshold=0.1
        )
        if mismatch > 0:
            diff_img = Image.frombytes("RGBA", img1.size, bytes(diff_data))
            diff_img.save(diff_path)
        return mismatch, None
    except Exception as e:
        return 0, str(e)

    return mismatch, None


async def run_visual_test(
    viewport,
    path_url,
    base_url="http://localhost:4321",
    browser_instance=None,
    update_callback=None,
    test_id_key=None,
    target_dir=".",
):
    if not browser_instance:
        return False, "No active browser instance provided", None

    if isinstance(viewport, str) and "x" in viewport:
        w, h = viewport.split("x")
        vp = {"width": int(w), "height": int(h)}
    else:
        vp = viewport

    test_uid = str(uuid.uuid4())
    success = False
    error_msg = None
    screenshot_path = None
    baseline_path = None

    try:
        context = await browser_instance.new_context(viewport=vp)
        page = await context.new_page()

        if update_callback:
            update_callback(test_id_key, test_status="[cyan]Navigating...[/cyan]")

        full_url = f"{base_url.rstrip('/')}{path_url}"
        console.print(
            f" -> [Visual Test] Navigating to: [cyan]{full_url}[/cyan]", style="dim"
        )
        await page.goto(full_url, wait_until="networkidle")

        screenshot_path = f"screenshot_{test_uid}.png"
        if update_callback:
            update_callback(test_id_key, test_status="[cyan]Capturing...[/cyan]")

        await page.screenshot(path=screenshot_path)

        # VRT Logic
        baseline_dir = Path(target_dir) / ".aether" / "baselines"
        baseline_dir.mkdir(parents=True, exist_ok=True)

        # Clean label for filename
        safe_label = "".join(
            [c if c.isalnum() else "_" for c in (test_id_key or "default")]
        )
        vp_str = f"{vp['width']}x{vp['height']}"
        baseline_path = baseline_dir / f"{safe_label}_{vp_str}.png"

        if not baseline_path.exists():
            # First time: save as baseline
            import shutil

            shutil.copy(screenshot_path, baseline_path)
            if update_callback:
                update_callback(test_id_key, test_status="[green]NEW BASELINE[/green]")
            success = True
        else:
            # Compare with baseline
            diff_path = f"diff_{test_uid}.png"
            mismatch, err = calculate_pixel_diff(
                str(baseline_path), screenshot_path, diff_path
            )

            if err:
                error_msg = f"VRT Error: {err}"
                success = True  # Test ran, but comparison failed
            elif mismatch > 0:
                error_msg = f"Visual Diff Detected: {mismatch} pixels mismatched."
                success = False
                # Optionally link diff_path in artifact
                screenshot_path = diff_path  # Show diff as primary artifact
            else:
                success = True

        await context.close()
    except Exception as e:
        error_msg = str(e)

    return (
        success,
        error_msg,
        screenshot_path,
        str(baseline_path) if baseline_path else None,
    )


async def run_command_test(command, cwd=None, update_callback=None, test_id_key=None):
    if update_callback:
        update_callback(test_id_key, test_status="[cyan]Running...[/cyan]")
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0
        output = stdout.decode().strip() + "\n" + stderr.decode().strip()

        return success, output, None
    except Exception as e:
        return False, str(e), None


async def execute_test_internal(
    test,
    browser_instance,
    target_dir,
    rp_service,
    strategy,
    event_emitter: EventEmitter = None,
    app_url="http://localhost:4321",
):
    test_type = test.get("type", "visual")
    label = test.get("label")
    vp = test.get("viewport")
    path_or_cmd = test.get("path") or test.get("command")

    if event_emitter:
        event_emitter.emit(
            TestStartedEvent(
                type="test_started",
                timestamp=time.time(),
                label=label,
                test_type=test_type,
                strategy=strategy,
            )
        )

    baseline_path = None
    if test_type == "visual":
        if not browser_instance:
            success, error, artifact = (False, "Browser not available", None)
        else:
            success, error, artifact, bp = await run_visual_test(
                vp,
                path_url=path_or_cmd,
                base_url=app_url,
                browser_instance=browser_instance,
                update_callback=lambda lbl, **kw: event_emitter.emit(
                    TestProgressEvent(
                        type="test_progress",
                        timestamp=time.time(),
                        label=lbl,
                        status_text=kw.get("test_status", ""),
                    )
                )
                if event_emitter
                else None,
                test_id_key=label,
                target_dir=target_dir,
            )
            baseline_path = bp
    elif test_type == "command":
        # Handle ENOENT or missing npm by ensuring we run in shell (already doing)
        # But maybe we should log CWD for clarity
        success, error, artifact = await run_command_test(
            path_or_cmd,
            cwd=target_dir,
            update_callback=lambda lbl, **kw: event_emitter.emit(
                TestProgressEvent(
                    type="test_progress",
                    timestamp=time.time(),
                    label=lbl,
                    status_text=kw.get("test_status", ""),
                )
            )
            if event_emitter
            else None,
            test_id_key=label,
        )
        baseline_path = None
    else:
        success, error, artifact = (False, f"Unknown test type: {test_type}", None)
        baseline_path = None

    status = "PASSED" if success else "FAILED"

    if event_emitter:
        event_emitter.emit(
            TestFinishedEvent(
                type="test_finished",
                timestamp=time.time(),
                label=label,
                status=status,
                error=error,
                artifact=artifact,
                baseline=baseline_path,
            )
        )

    if rp_service:
        try:
            rp_service.start_test_item(name=label, item_type="STEP")
            if not success:
                rp_service.log(message=f"Test failed: {error}", level="ERROR")
            rp_service.finish_test_item(
                end_time=str(int(time.time() * 1000)), status=status
            )
        except Exception:
            pass

    return {
        "type": test_type,
        "label": label,
        "status": status,
        "error": error,
        "artifact": artifact,
        "baseline": baseline_path,
        "strategy": strategy,
    }


async def _run_headless(
    tests,
    browser_provider,
    strategy,
    target_dir,
    rp_service,
    close_browser=True,
    app_url="http://localhost:4321",
    event_emitter: EventEmitter = None,
):
    """Executes tests without TUI, handling optional browser dependencies."""
    results = []
    test_tasks = []

    # Check if we have visual tests
    has_visual = any(t.get("type") == "visual" for t in tests)

    if has_visual:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser_instance = None
                try:
                    # Non-interactive start: auto-confirm browser launch in headless mode
                    async def auto_confirm(q, default=True):
                        return True

                    await browser_provider.start(p, display_callback=auto_confirm)
                    browser_instance = await browser_provider.get_browser(p)
                except Exception as e:
                    console.print(f"[red]Browser setup failed:[/red] {e}")

                for test in tests:
                    test_tasks.append(
                        execute_test_internal(
                            test,
                            browser_instance,
                            target_dir,
                            rp_service,
                            strategy,
                            event_emitter=event_emitter,
                            app_url=app_url,
                        )
                    )
                results = await asyncio.gather(*test_tasks)

                # Cleanup
                if browser_instance and close_browser:
                    await browser_provider.close()

        except ImportError:
            console.print("[red]Playwright is not installed.[/red]")
            console.print("[yellow]Visual tests require the 'browser' extra.[/yellow]")
            console.print(
                "[blue]Please install it with: pip install 'aether-lens-cli\\[browser]'[/blue]\n"
            )
            console.print("[dim]Skipping visual tests for now...[/dim]")
            # Skip visual tests, run others
            for test in tests:
                if test.get("type") == "visual":
                    results.append(
                        {
                            **test,
                            "status": "SKIPPED",
                            "error": "Playwright missing",
                            "strategy": strategy,
                        }
                    )
                else:
                    test_tasks.append(
                        execute_test_internal(
                            test,
                            None,
                            target_dir,
                            rp_service,
                            strategy,
                            event_emitter=event_emitter,
                            app_url=app_url,
                        )
                    )
            if test_tasks:
                results.extend(await asyncio.gather(*test_tasks))
    else:
        # No visual tests, just run commands
        for test in tests:
            test_tasks.append(
                execute_test_internal(
                    test,
                    None,
                    target_dir,
                    rp_service,
                    strategy,
                    event_emitter=event_emitter,
                    app_url=app_url,
                )
            )
        results = await asyncio.gather(*test_tasks)

    return results


async def run_pipeline_with_tui(
    tests,
    browser_provider,
    strategy,
    target_dir,
    rp_service,
    event_emitter: EventEmitter = None,
    close_browser=True,
    app_url="http://localhost:4321",
    config=None,
):
    """Executes the pipeline within the Textual TUI."""
    # This import is guarded in run_pipeline, so it should be safe here if we passed checks
    from aether_lens.core.tui import PipelineDashboard

    # Check for playwright before starting TUI if we have visual tests
    app = PipelineDashboard(tests, strategy_name=strategy)

    async def run_logic(app_instance):
        has_visual = any(t.get("type") == "visual" for t in tests)
        browser_instance = None

        # Allure Lifecycle
        allure_provider = None
        allure_strategy = config.get("allure_strategy") if config else None
        if allure_strategy == "docker":
            allure_provider = report.DockerAllureProvider()
        elif allure_strategy in ["kubernetes", "inpod"]:
            allure_provider = report.KubernetesAllureProvider()
        elif allure_strategy == "ephemeral":
            # Auto-detect or default to Docker if local
            allure_provider = report.DockerAllureProvider()

        if allure_provider:
            try:
                await allure_provider.start()
            except Exception as e:
                app_instance.log_message(f"[yellow]Allure start failed: {e}[/yellow]")

        app_instance.log_message(f"Run Logic started. Has Visual: {has_visual}")

        # Create a proxy event emitter that updates the TUI
        # This allows the same pipeline code to work for both TUI and external Executor
        tui_emitter = event_emitter or EventEmitter(
            transports=[
                CallbackTransport(
                    callback=lambda ev: (
                        app.update_test_status(
                            ev.label,
                            test_status=ev.status
                            if hasattr(ev, "status")
                            else ev.status_text
                            if hasattr(ev, "status_text")
                            else "",
                        )
                        if isinstance(
                            ev, (TestStartedEvent, TestProgressEvent, TestFinishedEvent)
                        )
                        else app.log_message(ev.message)
                        if isinstance(ev, PipelineLogEvent)
                        else None
                    )
                )
            ]
        )

        # Prepare Browser Context Manager (Sub-workflow)

        async def execute_all_tests():
            # Separate setup tasks and normal tests
            setup_tasks = [t for t in tests if t.get("type") == "setup"]
            normal_tests = [t for t in tests if t.get("type") != "setup"]

            # Execute Setup Tasks First
            browser_instance = None

            for setup_task in setup_tasks:
                if setup_task.get("label") == "Prepare Browser Environment":
                    # Notify status
                    if tui_emitter:
                        tui_emitter.emit(
                            TestStartedEvent(
                                type="test_started",
                                timestamp=time.time(),
                                label=setup_task["label"],
                            )
                        )

            # Refactored Logic: Context Manager around execution
            if has_visual:
                try:
                    from playwright.async_api import async_playwright

                    async with async_playwright() as p:
                        # Run Setup Task "Visually"
                        for t in setup_tasks:
                            if t.get("label") == "Prepare Browser Environment":
                                try:
                                    await browser_provider.start(
                                        p, display_callback=app.ask_browser_confirmation
                                    )
                                    browser_instance = (
                                        await browser_provider.get_browser(p)
                                    )
                                    app.log_message("Browser started successfully.")
                                    if tui_emitter:
                                        tui_emitter.emit(
                                            TestFinishedEvent(
                                                type="test_finished",
                                                timestamp=time.time(),
                                                label=t["label"],
                                                status="PASSED",
                                            )
                                        )
                                except Exception as e:
                                    app.log_message(f"Browser setup failed: {e}")
                                    if tui_emitter:
                                        tui_emitter.emit(
                                            TestFinishedEvent(
                                                type="test_finished",
                                                timestamp=time.time(),
                                                label=t["label"],
                                                status="FAILED",
                                                error=str(e),
                                            )
                                        )
                                    browser_instance = None

                        # Run Normal Tests
                        tasks = []
                        for test in normal_tests:
                            tasks.append(
                                execute_test_internal(
                                    test,
                                    browser_instance,
                                    target_dir,
                                    rp_service,
                                    strategy,
                                    event_emitter=tui_emitter,
                                    app_url=app_url,
                                )
                            )
                        return await asyncio.gather(*tasks)

                finally:
                    if close_browser:
                        await browser_provider.close()
                        app_instance.log_message("Browser resource closed.")
            else:
                # No visual tests
                tasks = []
                for test in tests:
                    if test.get("type") == "setup":
                        continue
                    tasks.append(
                        execute_test_internal(
                            test,
                            None,
                            target_dir,
                            rp_service,
                            strategy,
                            event_emitter=tui_emitter,
                            app_url=app_url,
                        )
                    )
                return await asyncio.gather(*tasks)

        results = await execute_all_tests()
        app_instance.results = results
        app_instance.show_completion_message()
        return results

    # Run the TUI and logic concurrently
    app.log_message("Starting run_pipeline_with_tui dashboard loop...")
    app.run_logic_callback = run_logic
    await app.run_async()
    # Note: Textual's run_async returns None.
    # The results are collected via capturing if needed, but here we just wait for completion.
    return getattr(app, "results", [])


@inject
async def run_pipeline(
    target_dir,
    sidecar_url,
    context,
    rp_url=None,
    allure_dir=None,
    strategy="auto",
    custom_instruction=None,
    browser_provider: "browser.BrowserProvider" = Provide[Container.browser_provider],
    use_tui: bool = True,
    event_emitter: EventEmitter = None,
    close_browser: bool = True,
    app_url: str = None,
):
    strategy_disp = f"{strategy} (Custom)" if strategy == "custom" else strategy
    console.print(
        Panel(
            f"[bold blue]Aether Lens[/bold blue] Pipeline Triggered for [cyan]{target_dir}[/cyan] (Strategy: {strategy_disp})",
            expand=False,
        )
    )

    # Resolve App Lifecycle
    config = load_config(target_dir)
    deployment_config = config.get("deployment", {})

    # Determine the context key (e.g. 'docker', 'kubernetes') from the provider
    # We can infer this from the provider class name or a property
    # For now, let's assume we can map the strategy string passed in configurations
    # The 'browser_strategy' is explicitly passed to specific functions, but here
    # run_pipeline receives 'browser_provider' instance.
    # However, init/cli sets 'browser_strategy' in config.

    current_env = config.get("browser_strategy", "local")
    env_deploy = deployment_config.get(current_env)

    deploy_cmd = None
    cleanup_cmd = None
    health_url = (
        config.get("health_check_url") or app_url
    )  # Fallback to global if not in env

    if env_deploy:
        deploy_type = env_deploy.get("type")
        health_url = env_deploy.get("health_check") or health_url

        if deploy_type == "compose":
            compose_file = env_deploy.get("file", "docker-compose.yaml")
            service = env_deploy.get("service", "")
            deploy_cmd = f"docker compose -f {compose_file} up -d {service}"
            cleanup_cmd = f"docker compose -f {compose_file} down"
        elif deploy_type == "kubectl":
            manifests = env_deploy.get("manifests", [])
            if isinstance(manifests, list):
                manifests = " ".join([f"-f {m}" for m in manifests])
            namespace = env_deploy.get("namespace", "default")
            deploy_cmd = f"kubectl apply {manifests} -n {namespace}"
            cleanup_cmd = f"kubectl delete {manifests} -n {namespace}"
        elif deploy_type == "kustomize":
            path = env_deploy.get("path", ".")
            namespace = env_deploy.get(
                "namespace", ""
            )  # Kustomize usually handles NS, but explicit NS might be needed override?
            # Usually 'kubectl apply -k dir' is enough.
            deploy_cmd = f"kubectl apply -k {path}"
            cleanup_cmd = f"kubectl delete -k {path}"
            if namespace:
                deploy_cmd += f" -n {namespace}"
                cleanup_cmd += f" -n {namespace}"
        elif deploy_type == "custom":
            deploy_cmd = env_deploy.get("deploy_command")
            cleanup_cmd = env_deploy.get("cleanup_command")

    # Override with legacy/CLI env vars if present (backward compatibility)
    deploy_cmd = os.getenv("DEPLOY_COMMAND") or deploy_cmd
    cleanup_cmd = os.getenv("CLEANUP_COMMAND") or cleanup_cmd
    health_url = os.getenv("HEALTH_CHECK_URL") or health_url

    if deploy_cmd:
        success, output = run_deployment_hook(deploy_cmd, cwd=target_dir)
        if not success:
            console.print("[red]Aborting pipeline due to deployment failure.[/red]")
            return

    if health_url and deploy_cmd:
        if not await wait_for_health_check(health_url):
            console.print("[yellow]Warning: Application might not be ready.[/yellow]")

    diff = get_git_diff(target_dir)  # Simplified
    if not diff:
        console.print("[yellow]No changes detected.[/yellow]")
        return

    config = load_config(target_dir)

    analysis_results = []
    console.print(f" -> [Pipeline] Analyzing {len(diff)} bytes of diff...")

    # Resolve strategies to run
    if strategy == "auto":
        # Check config for multiple strategies
        strategy = config.get("strategies", "auto")

    if isinstance(strategy, str):
        strategies = [s.strip() for s in strategy.split(",")]
    else:
        strategies = strategy

    console.print(
        f" -> [Pipeline] Strategies: [cyan]{', '.join(strategies)}[/cyan]", style="dim"
    )

    all_tests = []
    seen_tests = set()

    for s in strategies:
        analysis = run_analysis(diff, context, s, custom_instruction)
        analysis_results.append(analysis)

        strategy_tests = analysis.get("recommended_tests", [])
        for t in strategy_tests:
            # Create a unique key for de-duplication
            test_key = (t.get("type"), t.get("label"), t.get("path"), t.get("command"))
            if test_key not in seen_tests:
                all_tests.append(t)
                seen_tests.add(test_key)

    # Merge with explicit tests from config
    config_tests = config.get("tests", [])
    for t in config_tests:
        test_key = (t.get("type"), t.get("label"), t.get("path"), t.get("command"))
        if test_key not in seen_tests:
            all_tests.append(t)
            seen_tests.add(test_key)

    if not all_tests:
        console.print(
            "[yellow]No tests recommended for the selected strategies.[/yellow]"
        )
        return

    # Use the first analysis for the summary panel (or merge them)
    summary_text = "\n---\n".join([res.get("analysis", "") for res in analysis_results])
    console.print(
        Panel(
            f"[bold green]AI Analysis Result[/bold green]\n{summary_text}",
            title="AI Intent",
            expand=False,
        )
    )

    tests = all_tests

    # Check if visual tests exist and prepend Browser Setup task
    has_visual_tests = any(t.get("type") == "visual" for t in tests)
    if has_visual_tests:
        tests.insert(
            0,
            {
                "type": "setup",
                "label": "Prepare Browser Environment",
                "status": "PENDING",
            },
        )

    rp_service = None  # ReportPortal setup simplified

    # Resolve app URL
    if not app_url:
        app_url = os.getenv("APP_BASE_URL", "http://localhost:4321")

    # Auto-switch to host.docker.internal if managed Docker/K8s browser is used
    # check browser_provider type/config
    is_managed = getattr(browser_provider, "launch", False)
    if is_managed and "localhost" in app_url:
        app_url = app_url.replace("localhost", "host.docker.internal")
        console.print(
            f" -> [Pipeline] Auto-switching app URL to [cyan]{app_url}[/cyan] for Docker access.",
            style="dim",
        )

    # Decide execution mode
    # --headless now ONLY refers to the browser being headless.
    # TUI is used by default if it's an interactive terminal.
    can_use_tui = use_tui and sys.stdin.isatty()

    # Try importing Textual if TUI is requested
    if can_use_tui:
        try:
            import textual

            console.print(" -> [Pipeline] Launching Textual TUI...")
        except ImportError:
            console.print(
                "[yellow]Textual not installed. Falling back to plain reporting.[/yellow]"
            )
            can_use_tui = False

    if can_use_tui:
        try:
            results = await run_pipeline_with_tui(
                tests,
                browser_provider,
                strategy,
                target_dir,
                rp_service,
                event_emitter=event_emitter,
                close_browser=close_browser,
                app_url=app_url,
                config=config,
            )
        except ImportError as e:
            # specifically for playwright in TUI
            console.print(
                f"[yellow]TUI dependency missing: {e}. Falling back to plain reporting.[/yellow]"
            )
            can_use_tui = False
        except Exception as e:
            # Fallback for other TUI errors
            console.print(
                f"[yellow]TUI Error: {e}. Falling back to plain reporting.[/yellow]"
            )
            # Use a more descriptive error if it's a known one
            # traceback.print_exc() # For deep debugging
            can_use_tui = False

    if not can_use_tui:
        if not sys.stdin.isatty() and use_tui:
            console.print("[yellow]Non-interactive terminal, TUI skipped.[/yellow]")
        console.print(" -> [Pipeline] Running in Headless/Plain mode...")
        results = await _run_headless(
            tests,
            browser_provider,
            strategy,
            target_dir,
            rp_service,
            close_browser=close_browser,
            app_url=app_url,
            event_emitter=event_emitter,
        )

    # Final summary (Plain table)
    browser_errors = [
        res
        for res in results
        if res.get("type") == "visual"
        and res.get("status") != "PASSED"
        and (
            "Browser" in str(res.get("error", ""))
            or "Playwright" in str(res.get("error", ""))
        )
    ]

    if browser_errors:
        console.print(
            Panel(
                "[bold red]Browser Connection Failed[/bold red]\n"
                "Could not connect to the browser environment.\n"
                "• Ensure Docker/K8s is running if using managed strategy.\n"
                "• Use [bold]--launch-browser[/bold] to automatically start the environment.\n"
                "• If connecting to existing instance, check port/URL.",
                title="Environment Error",
                border_style="red",
            )
        )

    table = Table(title="Lens Loop Summary")
    table.add_column("Type", style="cyan")
    table.add_column("Test Case", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Error", style="yellow")

    for res in results:
        status_style = "green" if res["status"] == "PASSED" else "red"
        error_msg = res.get("error") or ""
        # Truncate long errors
        if len(error_msg) > 50:
            error_msg = error_msg[:47] + "..."

        table.add_row(
            res["type"],
            res["label"],
            f"[{status_style}]{res['status']}[/{status_style}]",
            error_msg,
        )

    console.print(table)
    console.print("[bold blue]Pipeline completed.[/bold blue]")

    # Generate reports
    try:
        html_path = report.generate_conformance_report(results, target_dir)
        allure_path = report.export_to_allure(results, target_dir)

        # Get Allure Config for URL display
        allure_endpoint = os.getenv("ALLURE_ENDPOINT") or "http://localhost:5050"
        allure_project_id = os.getenv("ALLURE_PROJECT_ID", "default")
        allure_ui_url = f"{allure_endpoint.rstrip('/')}/allure-docker-service/projects/{allure_project_id}/reports/latest/index.html"

        console.print("\n -> [Pipeline] [bold green]Report generated![/bold green]")
        console.print(
            f"    - Visual Conformance: [link=file://{html_path}]{html_path}[/link]"
        )
        console.print(
            f"    - Allure Dashboard UI: [bold cyan]{allure_ui_url}[/bold cyan]"
        )
        console.print(
            f"    - Allure Dashboard API: [dim]{allure_endpoint}[/dim]", style="dim"
        )
        console.print(f"    - Allure Results Raw: {allure_path}", style="dim")

        # Sync to remote Allure API if configured
        allure_endpoint = os.getenv("ALLURE_ENDPOINT")
        allure_key = os.getenv("ALLURE_API_KEY")
        if allure_endpoint:
            console.print(f" -> [Pipeline] Syncing to Allure API: {allure_endpoint}...")
            success, msg = report.sync_results_to_allure_api(
                target_dir, api_url=allure_endpoint, api_key=allure_key
            )
            if success:
                console.print(f"    - [green]Sync OK:[/green] {msg}")
            else:
                console.print(f"    - [yellow]Sync Warning:[/yellow] {msg}")

    except Exception as e:
        console.print(f"[yellow]Warning: Failed to generate reports: {e}[/yellow]")

    return {
        "analysis": analysis.get("analysis"),
        "recommended_tests": tests,
        "results": results,
    }
