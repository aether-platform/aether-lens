import argparse
import asyncio
import os
import shutil

from PIL import Image
from playwright.async_api import async_playwright

try:
    from pixelmatch import pixelmatch
except ImportError:
    pixelmatch = None


class VisualTestRunner:
    def __init__(self, base_url: str = None, current_dir: str = None):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.current_dir = current_dir or os.getcwd()
        self.browser_strategy = "local"

    def calculate_pixel_diff(self, img1_path, img2_path, diff_path, threshold=0.1):
        if not pixelmatch:
            return None, "pixelmatch not installed"

        try:
            img1 = Image.open(img1_path).convert("RGBA")
            img2 = Image.open(img2_path).convert("RGBA")
        except FileNotFoundError as e:
            return None, f"Image file not found: {e}"
        except Exception as e:
            return None, f"Error opening images: {e}"

        if img1.size != img2.size:
            img2 = img2.resize(img1.size)

        width, height = img1.size
        diff_data = bytearray(width * height * 4)

        try:
            mismatch = pixelmatch(
                img1.tobytes(),
                img2.tobytes(),
                width,
                height,
                diff_data,
                threshold=threshold,
            )
            if mismatch > 0:
                diff_img = Image.frombytes("RGBA", img1.size, bytes(diff_data))
                diff_img.save(diff_path)
            return mismatch, None
        except Exception as e:
            return 0, str(e)

    async def run_visual_test(
        self,
        page,
        label,
        path_url,
        viewport=None,
        test_id_key="vrt",
        vrt_config=None,
    ):
        vrt_config = vrt_config or {}

        full_url = (
            path_url if path_url.startswith("http") else f"{self.base_url}{path_url}"
        )

        if viewport:
            w, h = map(int, viewport.split("x"))
            await page.set_viewport_size({"width": w, "height": h})

        try:
            await page.goto(full_url, wait_until="networkidle")
        except Exception as e:
            return False, f"Navigation failed: {e}", None

        # Screenshot logic
        baseline_dir = os.path.join(self.current_dir, "tests", "baselines")
        os.makedirs(baseline_dir, exist_ok=True)
        baseline_path = os.path.join(baseline_dir, f"{test_id_key}.png")

        current_path = os.path.join(self.current_dir, f"{test_id_key}_current.png")
        diff_path = os.path.join(self.current_dir, f"{test_id_key}_diff.png")

        await page.screenshot(path=current_path, full_page=True)

        if not os.path.exists(baseline_path):
            shutil.copy(current_path, baseline_path)
            return True, "Baseline created", baseline_path

        # Compare
        threshold = float(vrt_config.get("threshold", 0.1))
        mismatch, err = self.calculate_pixel_diff(
            baseline_path, current_path, diff_path, threshold
        )

        if err:
            return False, f"Comparison error: {err}", None

        if mismatch > 0:
            return False, f"Visual mismatch detected ({mismatch} pixels)", diff_path

        return True, "Visual test passed", None

    async def execute_suite(self, suite_id, parameters):
        from aether_lens.daemon.repository.reg_scenarios import REGISTRY

        scenario_func = REGISTRY.get(suite_id)
        if not scenario_func:
            print(f"Scenario {suite_id} not found")
            return False

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()

            success = True
            try:
                # Execute the scenario function (e.g. login, navigate)
                await scenario_func(page, parameters)

                # Perform VRT snapshot if implicit path is provided or scenario implies it
                # For backward compatibility, we assume layout_check sets up the page and we take a snapshot here
                # OR the scenario function handles assertions itself.

                # Let's enforce taking a snapshot for verification if it's a 'check'
                path = parameters.get("path", "/")
                viewport = parameters.get("viewport", "1280x720")

                s, e, a = await self.run_visual_test(
                    page=page,
                    label=suite_id,
                    path_url=path,
                    viewport=viewport,
                    test_id_key=suite_id,
                    vrt_config=parameters,
                )
                success = s
                status_msg = f"PASSED: {e}" if success else f"FAILED: {e}"
                if a:
                    status_msg += f" (Artifact: {a})"
                print(status_msg)

            except Exception as e:
                print(f"Error executing scenario: {e}")
                success = False
            finally:
                await browser.close()

            return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("suite_id")
    parser.add_argument("--threshold", default=0.1)
    parser.add_argument("--base-url", default="http://localhost:4321")

    args, unknown = parser.parse_known_args()

    params = {"threshold": args.threshold}
    i = 0
    while i < len(unknown):
        key = unknown[i]
        if key.startswith("--"):
            k = key[2:]
            if i + 1 < len(unknown) and not unknown[i + 1].startswith("--"):
                params[k] = unknown[i + 1]
                i += 2
            else:
                params[k] = True
                i += 1
        else:
            i += 1

    runner = VisualTestRunner(base_url=args.base_url)
    asyncio.run(runner.execute_suite(args.suite_id, params))
