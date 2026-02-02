import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse


class SiteAuditor:
    def __init__(self, base_url: str = None, current_dir: str = None):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.current_dir = Path(current_dir or Path.cwd())

    async def run_external_tool(self, cmd, label):
        print(f" -> Running {label}: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def audit_site(self, parameters):
        """Use linkinator to discover URLs and lighthouse to audit them."""
        print(f"Starting Site Health Audit via External Tools on {self.base_url}...")

        # 1. Discover URLs via linkinator
        linkinator_cmd = [
            "npx",
            "-y",
            "linkinator",
            self.base_url,
            "--recurse",
            "--format",
            "json",
            "--dry-run",
        ]

        rc, out, err = await self.run_external_tool(
            linkinator_cmd, "Linkinator (Crawler)"
        )
        if rc != 0:
            print(f"Linkinator failed: {err}")
            return False

        try:
            data = json.loads(out)
            links = data.get("links", [])
        except Exception as e:
            print(f"Failed to parse Linkinator output: {e}")
            return False

        # Filter internal successful HTML-like URLs
        base_parsed = urlparse(self.base_url)
        urls_to_test = set()
        for link in links:
            u = link.get("url")
            if not u or link.get("status") != 200:
                continue
            parsed = urlparse(u)
            if parsed.netloc != base_parsed.netloc:
                continue

            path = parsed.path.lower()
            if any(
                path.endswith(ext)
                for ext in [
                    ".js",
                    ".css",
                    ".png",
                    ".jpg",
                    ".svg",
                    ".ico",
                    ".json",
                    ".xml",
                ]
            ):
                continue
            if path.startswith("/@") or "/node_modules/" in path:
                continue

            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            urls_to_test.add(clean_url)

        print(f"Discovered {len(urls_to_test)} pages to audit.")

        # 2. Audit each URL via Lighthouse
        success = True
        # To avoid extreme slowness, we limit the number of pages in audit
        max_audit = int(parameters.get("max_pages", 5))
        pages = sorted(list(urls_to_test))[:max_audit]

        for url in pages:
            print(f"\n--- Auditing: {url} ---")
            lh_cmd = [
                "npx",
                "-y",
                "lighthouse",
                url,
                "--output",
                "json",
                "--only-categories=accessibility,best-practices,performance,seo",
                "--chrome-flags=--headless",
                "--quiet",
            ]

            rc, out, err = await self.run_external_tool(lh_cmd, "Lighthouse")
            if rc != 0:
                print(f"FAILED: Lighthouse audit for {url}")
                success = False
                continue

            try:
                report = json.loads(out)
                scores = {k: v["score"] * 100 for k, v in report["categories"].items()}
                print(f"PASSED: {url} | Scores: {scores}")

                threshold = float(parameters.get("min_score", 80))
                for cat, score in scores.items():
                    if score < threshold:
                        print(
                            f"  [WARNING] {cat} score is below threshold: {score} < {threshold}"
                        )
            except Exception as e:
                print(f"Error parsing Lighthouse report for {url}: {e}")
                success = False

        return success

    async def execute_suite(self, suite_id, parameters):
        if suite_id == "site_audit":
            return await self.audit_site(parameters)

        print(
            f"Error: Unknown orchestrated suite '{suite_id}'. Individual scenarios should be run via their own external tools."
        )
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aether Lens Site Auditor")
    parser.add_argument("suite_id", help="Suite to run (e.g., site_audit)")
    parser.add_argument("--threshold", default=0.1, help="Test failure threshold")
    parser.add_argument(
        "--base-url", default="http://localhost:4321", help="Target base URL"
    )

    # Capture additional parameters as key=value or --key=value
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

    auditor = SiteAuditor(base_url=args.base_url)
    asyncio.run(auditor.execute_suite(args.suite_id, params))
