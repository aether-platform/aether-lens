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

console = Console(stderr=True)


def load_config(target_dir):
    config_path = os.path.join(target_dir, "aether-lens.config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load config file: {e}[/yellow]")
    return {}


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
    update_callback=None,
    app_url="http://localhost:4321",
):
    test_type = test.get("type", "visual")
    label = test.get("label")
    vp = test.get("viewport")
    path_or_cmd = test.get("path") or test.get("command")

    if update_callback:
        update_callback(
            label,
            strategy=f"[blue]{strategy}[/blue]",
            browser_check="[green]OK[/green]"
            if test_type == "visual"
            else "[dim]-[/dim]",
            connection="[green]OK[/green]" if test_type == "visual" else "[dim]-[/dim]",
            test_status="[cyan]実行中...[/cyan]",
        )

    if test_type == "visual":
        if not browser_instance:
            success, error, artifact = (False, "Browser not available", None)
        else:
            success, error, artifact, baseline_path = await run_visual_test(
                vp,
                path_url=path_or_cmd,
                base_url=app_url,
                browser_instance=browser_instance,
                update_callback=update_callback,
                test_id_key=label,
                target_dir=target_dir,
            )
    elif test_type == "command":
        # Handle ENOENT or missing npm by ensuring we run in shell (already doing)
        # But maybe we should log CWD for clarity
        success, error, artifact = await run_command_test(
            path_or_cmd,
            cwd=target_dir,
            update_callback=update_callback,
            test_id_key=label,
        )
        baseline_path = None
    else:
        success, error, artifact = (False, f"Unknown test type: {test_type}", None)
        baseline_path = None

    status = "PASSED" if success else "FAILED"
    status_color = "bold green" if success else "bold red"

    if update_callback:
        update_callback(
            label,
            test_status=f"[{status_color}]{status}[/{status_color}]",
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
                    # Non-interactive start
                    await browser_provider.start(p, display_callback=None)
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
                            update_callback=None,
                            app_url=app_url,
                        )
                    )
                results = await asyncio.gather(*test_tasks)

                # Cleanup
                if browser_instance and close_browser:
                    await browser_provider.close()

        except ImportError:
            console.print("[red]Playwright not installed. Skipping visual tests.[/red]")
            # Skip visual tests, run others
            for test in tests:
                if test.get("type") == "visual":
                    results.append(
                        {**test, "status": "SKIPPED", "error": "Playwright missing"}
                    )
                else:
                    test_tasks.append(
                        execute_test_internal(
                            test,
                            None,
                            target_dir,
                            rp_service,
                            strategy,
                            update_callback=None,
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
                    update_callback=None,
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
    close_browser=True,
    app_url="http://localhost:4321",
):
    """Executes the pipeline within the Textual TUI."""
    # This import is guarded in run_pipeline, so it should be safe here if we passed checks
    from aether_lens.core.tui import PipelineDashboard

    # Check for playwright before starting TUI if we have visual tests
    has_visual = any(t.get("type") == "visual" for t in tests)
    if has_visual:
        try:
            import playwright
        except ImportError:
            # Should not happen if caller checked, but just in case
            raise ImportError("Playwright is required for visual tests in TUI mode.")

    app = PipelineDashboard(tests, strategy_name=strategy)

    async def run_logic():
        # Wait for app to be ready
        while not app.is_mounted:
            await asyncio.sleep(0.1)

        browser_instance = None
        app.log_message(f"Run Logic started. Has Visual: {has_visual}")

        if has_visual:
            app.log_message("Starting Playwright...")
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    try:
                        # Provide modal confirmation callback to the provider
                        await browser_provider.start(
                            p, display_callback=app.ask_browser_confirmation
                        )
                        browser_instance = await browser_provider.get_browser(p)
                        app.log_message("Browser started successfully.")
                    except Exception as e:
                        app.log_message(f"Browser setup failed: {e}")

                    test_tasks = []
                    for test in tests:
                        test_tasks.append(
                            execute_test_internal(
                                test,
                                browser_instance,
                                target_dir,
                                rp_service,
                                strategy,
                                update_callback=app.update_test_status,
                                app_url=app_url,
                            )
                        )

                    results = await asyncio.gather(*test_tasks)
                    return results

            finally:
                # Ensure browser is closed even if cancellations or errors occur
                if close_browser:
                    await browser_provider.close()
                    app.log_message("Browser resource closed.")
                app.show_completion_message()
        else:
            # Command only tests
            test_tasks = []
            for test in tests:
                test_tasks.append(
                    execute_test_internal(
                        test,
                        None,
                        target_dir,
                        rp_service,
                        strategy,
                        update_callback=app.update_test_status,
                        app_url=app_url,
                    )
                )
            results = await asyncio.gather(*test_tasks)
            app.show_completion_message()
            return results

    # Run the TUI and logic concurrently
    app.log_message("Starting run_pipeline_with_tui dashboard loop...")
    logic_task = asyncio.create_task(run_logic())
    await app.run_async()
    return await logic_task


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
        console.print(" -> [Pipeline] Launching Textual TUI...")
        try:
            import textual

            results = await run_pipeline_with_tui(
                tests,
                browser_provider,
                strategy,
                target_dir,
                rp_service,
                close_browser=close_browser,
                app_url=app_url,
            )
        except ImportError:
            console.print(
                "[yellow]Textual not installed or TUI disabled. Falling back to plain reporting.[/yellow]"
            )
            can_use_tui = False
        except Exception as e:
            # Fallback for other TUI errors
            console.print(
                f"[yellow]TUI Error: {e}. Falling back to plain reporting.[/yellow]"
            )
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
        console.print("\n -> [Pipeline] [bold green]Report generated![/bold green]")
        console.print(
            f"    - Visual Conformance: [link=file://{html_path}]{html_path}[/link]"
        )
        console.print(
            "    - Allure Dashboard: [bold cyan]http://localhost:5050[/bold cyan] (Real-time)"
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
