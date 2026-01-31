import asyncio
import json
import os
import subprocess
import time
import uuid

from dependency_injector.wiring import Provide, inject
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aether_lens.core import browser
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


async def run_visual_test(
    viewport,
    path_url,
    browser_instance=None,
    update_callback=None,
    test_id_key=None,
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

    try:
        context = await browser_instance.new_context(viewport=vp)
        page = await context.new_page()

        base_url = os.getenv("APP_BASE_URL", "http://localhost:4321")
        full_url = f"{base_url}{path_url}"

        if update_callback:
            update_callback(test_id_key, test_status="[cyan]Navigating...[/cyan]")

        await page.goto(full_url, wait_until="networkidle")

        screenshot_path = f"screenshot_{test_uid}.png"
        if update_callback:
            update_callback(test_id_key, test_status="[cyan]Capturing...[/cyan]")

        await page.screenshot(path=screenshot_path)
        success = True
        await context.close()
    except Exception as e:
        error_msg = str(e)

    return success, error_msg, screenshot_path


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
    test, browser_instance, target_dir, rp_service, strategy, update_callback=None
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
            success, error, artifact = await run_visual_test(
                vp,
                path_url=path_or_cmd,
                browser_instance=browser_instance,
                update_callback=update_callback,
                test_id_key=label,
            )
    elif test_type == "command":
        success, error, artifact = await run_command_test(
            path_or_cmd,
            cwd=target_dir,
            update_callback=update_callback,
            test_id_key=label,
        )
    else:
        success, error, artifact = (False, f"Unknown test type: {test_type}", None)

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
    }


async def run_pipeline_with_tui(
    tests, browser_provider, strategy, target_dir, rp_service
):
    """Executes the pipeline within the Textual TUI."""
    from playwright.async_api import async_playwright

    from aether_lens.core.tui import PipelineDashboard

    app = PipelineDashboard(tests)

    async def run_logic():
        # Wait for app to be ready
        while not app.is_mounted:
            await asyncio.sleep(0.1)

        browser_instance = None
        has_visual = any(t.get("type") == "visual" for t in tests)

        if has_visual:
            app.log_message("Starting Playwright...")
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
                        )
                    )

                results = await asyncio.gather(*test_tasks)
                return results
        else:
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
                    )
                )
            results = await asyncio.gather(*test_tasks)
            return results

    # Run the TUI and logic concurrently
    # Textual App.run_async is better for integration
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

    analysis = run_analysis(diff, context, strategy, custom_instruction)
    console.print(
        Panel(
            f"[bold green]AI Analysis Result[/bold green]\n{analysis.get('analysis', 'No analysis summary')}",
            title="AI Intent",
            expand=False,
        )
    )

    rp_service = None  # ReportPortal setup simplified

    tests = analysis.get("recommended_tests", [])

    # Check if we should use TUI
    if sys.stdin.isatty():
        results = await run_pipeline_with_tui(
            tests, browser_provider, strategy, target_dir, rp_service
        )
    else:
        # Fallback to plain reporting if not a TTY
        results = []  # Existing logic...
        console.print("[yellow]Non-interactive terminal, TUI skipped.[/yellow]")

    # Final summary (Plain table)
    table = Table(title="Lens Loop Summary")
    table.add_column("Type", style="cyan")
    table.add_column("Test Case", style="white")
    table.add_column("Status", style="bold")

    for res in results:
        status_style = "green" if res["status"] == "PASSED" else "red"
        table.add_row(
            res["type"],
            res["label"],
            f"[{status_style}]{res['status']}[/{status_style}]",
        )

    console.print(table)
    console.print("[bold blue]Pipeline completed.[/bold blue]")

    return {
        "analysis": analysis.get("analysis"),
        "recommended_tests": tests,
        "results": results,
    }


import sys
