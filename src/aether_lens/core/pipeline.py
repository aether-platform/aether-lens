import asyncio
import base64
import json
import os
import subprocess
import time
import uuid

from dependency_injector.wiring import Provide, inject
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
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
        # ウォッチモード時は HEAD との比較、またはワークツリー内の変更を取得
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
    progress=None,
    task_id=None,
):
    if not browser_instance:
        return False, "No active browser instance provided", None

    if isinstance(viewport, str) and "x" in viewport:
        w, h = viewport.split("x")
        vp = {"width": int(w), "height": int(h)}
    else:
        vp = viewport

    test_id = str(uuid.uuid4())
    success = False
    error_msg = None
    screenshot_path = None

    try:
        # Create a private context for this test
        context = await browser_instance.new_context(viewport=vp)
        page = await context.new_page()

        base_url = os.getenv("APP_BASE_URL", "http://localhost:4321")
        full_url = f"{base_url}{path_url}"

        if progress and task_id:
            progress.update(
                task_id,
                test_status="[cyan]Navigating...[/cyan]",
            )
        await page.goto(full_url, wait_until="networkidle")

        screenshot_path = f"screenshot_{test_id}.png"
        if progress and task_id:
            progress.update(
                task_id,
                test_status="[cyan]Capturing...[/cyan]",
            )
        await page.screenshot(path=screenshot_path)
        success = True
        await context.close()
    except Exception as e:
        error_msg = str(e)

    return success, error_msg, screenshot_path


async def run_command_test(command, cwd=None, progress=None, task_id=None):
    if progress and task_id:
        progress.update(task_id, test_status="[cyan]Running...[/cyan]")
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
    test, progress, task_id, browser_instance, target_dir, rp_service, strategy
):
    test_type = test.get("type", "visual")
    label = test.get("label")
    vp = test.get("viewport")
    path_or_cmd = test.get("path") or test.get("command")

    # Update columns
    progress.update(
        task_id,
        strategy=f"[blue]{strategy}[/blue]",
        label=label,
        browser_check="[green]OK[/green]",
        connection="[green]OK[/green]",
        test_status="[cyan]実行中...[/cyan]",
    )

    if test_type == "visual":
        if not browser_instance:
            success, error, artifact = (False, "Browser not available", None)
        else:
            success, error, artifact = await run_visual_test(
                vp,
                path_or_cmd,
                browser_instance=browser_instance,
                progress=progress,
                task_id=task_id,
            )
    elif test_type == "command":
        # Command tests don't need browser
        progress.update(
            task_id, browser_check="[dim]-[/dim]", connection="[dim]-[/dim]"
        )
        success, error, artifact = await run_command_test(
            path_or_cmd, cwd=target_dir, progress=progress, task_id=task_id
        )
    else:
        success, error, artifact = (False, f"Unknown test type: {test_type}", None)

    status = "PASSED" if success else "FAILED"
    status_color = "bold green" if success else "bold red"

    progress.update(
        task_id,
        test_status=f"[{status_color}]{status}[/{status_color}]",
        completed=1,
    )

    if rp_service:
        rp_service.start_test_item(name=label, item_type="STEP")
        if not success:
            rp_service.log(message=f"Test failed: {error}", level="ERROR")
        rp_service.finish_test_item(
            end_time=str(int(time.time() * 1000)), status=status
        )

    return {
        "type": test_type,
        "label": label,
        "status": status,
        "error": error,
        "artifact": artifact,
    }


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

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task1 = progress.add_task("[green]Analyzing changes (Git Diff)...", total=1)
        diff_b64 = os.getenv("AETHER_DIFF_B64")
        if diff_b64:
            try:
                diff = base64.b64decode(diff_b64).decode("utf-8")
            except Exception as e:
                console.print(f"[red]Error decoding AETHER_DIFF_B64:[/red] {e}")
                diff = None
        else:
            diff = os.getenv("AETHER_DIFF")

        if not diff:
            diff = get_git_diff(target_dir)

        progress.update(task1, completed=1)

    if not diff:
        console.print("[yellow]No changes detected.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task2 = progress.add_task(
            f"[purple]Consulting AI Agent ({strategy})...", total=1
        )
        analysis = run_analysis(diff, context, strategy, custom_instruction)
        progress.update(task2, completed=1)

    console.print(
        Panel(
            f"[bold green]AI Analysis Result[/bold green]\n{analysis.get('analysis', 'No analysis summary')}",
            title="AI Intent",
            expand=False,
        )
    )

    rp_service = None
    if rp_url:
        from reportportal_client import RPClient

        token = os.getenv("REPORTPORTAL_TOKEN")
        project = os.getenv("REPORTPORTAL_PROJECT", "aether-lens")
        if token:
            rp_service = RPClient(endpoint=rp_url, token=token, project=project)
            rp_service.start_launch(
                name="Lens Loop Launch", start_time=str(int(time.time() * 1000))
            )

    tests = analysis.get("recommended_tests", [])
    results = []

    # Custom columns as requested: ストラテジー | 名称 | 起動チェック | 接続 | テスト状況
    with Progress(
        TextColumn("[bold blue]{task.fields[strategy]} [/bold blue]"),
        TextColumn("[white]{task.fields[label]} [/white]"),
        TextColumn("{task.fields[browser_check]}"),
        TextColumn("{task.fields[connection]}"),
        TextColumn("{task.fields[test_status]}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=False,
        console=console,
    ) as progress:
        browser_instance = None
        has_visual = any(t.get("type") == "visual" for t in tests)

        if has_visual:
            # We need a dummy task for browser setup visibility
            bt_id = progress.add_task(
                "",
                total=1,
                strategy=f"[blue]{strategy}[/blue]",
                label="[bold]Browser Setup[/bold]",
                browser_check="[yellow]待機中...[/yellow]",
                connection="[yellow]待機中...[/yellow]",
                test_status="-",
            )
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                try:
                    progress.update(
                        bt_id,
                        browser_check="[yellow]実行中...[/yellow]",
                        connection="[yellow]準備中...[/yellow]",
                    )
                    await browser_provider.start(p)
                    browser_instance = await browser_provider.get_browser(p)
                    progress.update(
                        bt_id,
                        browser_check="[green]OK[/green]",
                        connection="[green]OK[/green]",
                        test_status="[green]起動済み[/green]",
                        completed=1,
                    )
                except Exception as e:
                    progress.update(
                        bt_id,
                        browser_check="[red]FAILED[/red]",
                        connection="[red]FAILED[/red]",
                        test_status=f"[red]{e}[/red]",
                        completed=1,
                    )

                test_tasks = []
                for test in tests:
                    tid = progress.add_task(
                        "",
                        total=1,
                        strategy=f"[blue]{strategy}[/blue]",
                        label=test.get("label"),
                        browser_check="[dim]待機中[/dim]",
                        connection="[dim]待機中[/dim]",
                        test_status="[dim]Pending[/dim]",
                    )
                    test_tasks.append(
                        execute_test_internal(
                            test,
                            progress,
                            tid,
                            browser_instance,
                            target_dir,
                            rp_service,
                            strategy,
                        )
                    )
                results = await asyncio.gather(*test_tasks)
        else:
            test_tasks = []
            for test in tests:
                tid = progress.add_task(
                    "",
                    total=1,
                    strategy=f"[blue]{strategy}[/blue]",
                    label=test.get("label"),
                    browser_check="[dim]-[/dim]",
                    connection="[dim]-[/dim]",
                    test_status="[dim]Pending[/dim]",
                )
                test_tasks.append(
                    execute_test_internal(
                        test,
                        progress,
                        tid,
                        None,
                        target_dir,
                        rp_service,
                        strategy,
                    )
                )
            results = await asyncio.gather(*test_tasks)

    if rp_service:
        rp_service.finish_launch(end_time=str(int(time.time() * 1000)))

    table = Table(title="Lens Loop Summary")
    table.add_column("Type", style="cyan")
    table.add_column("Test Case", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    for res in results:
        status_style = "green" if res["status"] == "PASSED" else "red"
        table.add_row(
            res["type"],
            res["label"],
            f"[{status_style}]{res['status']}[/{status_style}]",
            res["error"] or "-",
        )

    console.print(table)
    console.print("[bold blue]Pipeline completed.[/bold blue]")
