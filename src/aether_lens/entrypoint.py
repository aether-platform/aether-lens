import argparse
import base64
import json
import os
import subprocess
import sys
import time

from .ai_agent import main as run_ai_agent
from .watcher import start_watcher


def get_git_diff(target_dir):
    try:
        # ウォッチモード時は HEAD との比較、またはワークツリー内の変更を取得
        result = subprocess.run(
            ["git", "-C", target_dir, "diff", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        # diff が空なら、未コミットの変更のみ取得を試みる
        if not result.stdout:
            result = subprocess.run(
                ["git", "-C", target_dir, "diff"],
                capture_output=True,
                text=True,
                check=True,
            )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error getting git diff: {e}")
        return ""


async def run_visual_test(browser_url, viewport, path_url, allure_logger=None):
    import uuid

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        print(f" -> [Browserless] Connecting to {browser_url}...")
        browser = await p.chromium.connect_over_cdp(browser_url)
        context = await browser.new_context(
            viewport={"width": viewport["width"], "height": viewport["height"]}
        )
        page = await context.new_page()

        test_id = str(uuid.uuid4())
        success = False
        error_msg = None
        screenshot_path = None

        try:
            base_url = os.getenv("APP_BASE_URL", "http://localhost:4321")
            full_url = f"{base_url}项目完成状況：{path_url}"
            print(f" -> [Page] Navigating to {full_url}...")
            await page.goto(full_url, wait_until="networkidle")

            screenshot_path = f"screenshot_{test_id}.png"
            await page.screenshot(path=screenshot_path)
            success = True
        except Exception as e:
            error_msg = str(e)
            print(f" -> [Error] Test failed: {e}")
        finally:
            await browser.close()

        return success, error_msg, screenshot_path


def run_pipeline(target_dir, sidecar_url, context, rp_url=None, allure_dir=None):
    import asyncio

    print(f"\n[Aether Lens] Triggering Pipeline for {target_dir}...")

    # 1. git diff の取得
    diff = os.getenv("AETHER_DIFF")
    if not diff:
        diff = get_git_diff(target_dir)

    if not diff:
        print("[Aether Lens] No changes detected.")
        return

    print("[Aether Lens] Changes detected. Analyzing via AI...")

    # 2. AI Agent へのリクエスト
    input_data = {
        "diff": base64.b64encode(diff.encode("utf-8")).decode("utf-8"),
        "context": context,
        "target": "public/docs",
    }

    from io import StringIO

    old_stdin = sys.stdin
    sys.stdin = StringIO(json.dumps(input_data))
    old_stdout = sys.stdout
    sys.stdout = result_stdout = StringIO()

    try:
        run_ai_agent()
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    analysis_json = result_stdout.getvalue()
    try:
        analysis = json.loads(analysis_json)
    except json.JSONDecodeError:
        print(f"Error decoding AI analysis: {analysis_json}")
        return

    print(
        f"[Aether Lens] AI Analysis: {analysis.get('analysis', 'No analysis summary')}"
    )

    # ReportPortal Setup
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

    # 3. テスト実行 (Browserless 連携)
    for test in analysis.get("recommended_tests", []):
        label = test.get("label")
        vp = test.get("viewport")
        path_url = test.get("path")
        print(f" -> [Executing] {label} at {vp} for {path_url}...")

        success, error, screenshot = asyncio.run(
            run_visual_test(sidecar_url, vp, path_url)
        )

        # 4. レポート記録
        if rp_service:
            status = "PASSED" if success else "FAILED"
            rp_service.start_test_item(name=label, item_type="STEP")
            if not success:
                rp_service.log(message=f"Test failed: {error}", level="ERROR")
            rp_service.finish_test_item(
                end_time=str(int(time.time() * 1000)), status=status
            )

        if allure_dir:
            print(f" -> [Allure] Result stored for {label} (Screenshot: {screenshot})")

    if rp_service:
        rp_service.finish_launch(end_time=str(int(time.time() * 1000)))

    print("[Aether Lens] Pipeline completed.")


def main():
    parser = argparse.ArgumentParser(description="Aether Lens Agent")
    parser.add_argument("target", nargs="?", help="Target directory to monitor")
    parser.add_argument(
        "--watch", action="store_true", help="Enable watch mode (In-Pod)"
    )
    parser.add_argument(
        "--loop", action="store_true", help="Enable Lens Loop (Local Orchestrator)"
    )
    parser.add_argument("--pod", help="Target Pod name for loop mode")
    parser.add_argument("--namespace", default="aether-system", help="Target Namespace")
    args = parser.parse_args()

    target_dir = (
        args.target
        or os.getenv("TARGET_DIR")
        or ("c:/workspace/vibecoding-platform/app/public/docs")
    )
    sidecar_url = os.getenv("TEST_RUNNER_URL")
    context = os.getenv("KILOCODE_CONTEXT", "default-aether")
    rp_url = os.getenv("REPORTPORTAL_URL")
    allure_dir = os.getenv("ALLURE_RESULTS_DIR")

    if args.loop:
        from .loop import run_local_loop

        pod_name = args.pod or os.getenv("LENS_POD_NAME")
        if not pod_name:
            print("[Error] --loop mode requires --pod or LENS_POD_NAME env var.")
            sys.exit(1)

        # ローカル実行時のリモートパス (Pod内)
        remote_path = os.getenv("REMOTE_TARGET_DIR", "/app/project")
        run_local_loop(target_dir, pod_name, args.namespace, remote_path)

    elif args.watch:
        print(f"[Lens Loop] Starting Watch Mode on {target_dir}...")
        # 初回実行
        run_pipeline(target_dir, sidecar_url, context, rp_url, allure_dir)

        # 監視開始
        def on_change(path):
            run_pipeline(target_dir, sidecar_url, context, rp_url, allure_dir)

        start_watcher(target_dir, on_change)
    else:
        run_pipeline(target_dir, sidecar_url, context, rp_url, allure_dir)


if __name__ == "__main__":
    main()
