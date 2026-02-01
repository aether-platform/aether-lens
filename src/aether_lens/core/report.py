import base64
import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


def image_to_base64(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    except Exception:
        return None


def generate_conformance_report(results, target_dir, strategies=None):
    """
    Generates a standalone HTML report with embedded Base64 images.
    """
    target_path = Path(target_dir).absolute()
    report_dir = target_path / ".aether"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.html"

    # helper for resolving paths
    def resolve_image(p):
        if not p:
            return None
        abs_p = Path(p)
        if not abs_p.is_absolute():
            abs_p = target_path / p
        return image_to_base64(str(abs_p))

    # Group results by strategy if possible, or use 'default'
    results_by_strategy = {}
    total_tests = len(results)
    passed_tests = 0
    failed_tests = 0
    new_baselines = 0

    for res in results:
        # Clone to avoid mutating original
        item = res.copy()

        if item["status"] == "PASSED":
            passed_tests += 1
        else:
            failed_tests += 1

        strategy = item.get("strategy", "unknown")
        if strategy not in results_by_strategy:
            results_by_strategy[strategy] = []

        # Process images for visual tests
        if item["type"] == "visual":
            # Current screenshot or diff
            item["screenshot_b64"] = resolve_image(item.get("artifact"))

            # Baseline
            item["baseline_b64"] = resolve_image(item.get("baseline"))

            # If artifact is a diff, we might want to distinguish them
            if item.get("artifact") and "diff_" in os.path.basename(item["artifact"]):
                item["diff_b64"] = item["screenshot_b64"]
                # We don't have the "current" non-diff screenshot here anymore if we replaced it
                # But that's okay for PoC.

            # If it was a NEW BASELINE, count it
            if "NEW BASELINE" in str(
                item.get("error", "")
            ):  # Error field used for status in TUI sometimes
                new_baselines += 1

        results_by_strategy[strategy].append(item)

    # Load template
    template_path = Path(__file__).parent / "report_template.html"
    if not template_path.exists():
        # Fallback to a very simple internal template if file missing
        html = f"<html><body><h1>Aether Lens Report</h1><pre>{json.dumps(results, indent=2)}</pre></body></html>"
    else:
        with open(template_path, "r") as f:
            template = f.read()

        # Simple manual template rendering
        # (Since we didn't add Jinja2 to dependencies yet)
        html = template
        html = html.replace(
            "{{ timestamp }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        html = html.replace("{{ target_dir }}", str(target_dir))
        html = html.replace("{{ total_tests }}", str(total_tests))
        html = html.replace("{{ passed_tests }}", str(passed_tests))
        html = html.replace("{{ failed_tests }}", str(failed_tests))
        html = html.replace("{{ new_baselines }}", str(new_baselines))

        # Build the strategy blocks
        blocks_html = ""
        for strategy, tests in results_by_strategy.items():
            test_rows = ""
            for t in tests:
                status_class = (
                    "bg-green-500/20 text-green-400 border border-green-500/50"
                    if t["status"] == "PASSED"
                    else "bg-red-500/20 text-red-400 border border-red-500/50"
                )
                glow_class = "success-glow" if t["status"] == "PASSED" else "error-glow"

                visual_section = f"""
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
                    {f'<div><span class="text-xs text-slate-500 uppercase font-bold mb-2 block tracking-wider">Baseline</span><div class="rounded-lg overflow-hidden border border-white/10 bg-black/20"><img src="data:image/png;base64,{t["baseline_b64"]}" class="w-full h-auto" loading="lazy"></div></div>' if t.get("baseline_b64") else ""}
                    <div>
                        <span class="text-xs text-slate-500 uppercase font-bold mb-2 block tracking-wider">Current Result</span>
                        <div class="rounded-lg overflow-hidden border border-white/10 bg-black/20 {glow_class}">
                            <img src="data:image/png;base64,{t.get("screenshot_b64", "")}" class="w-full h-auto" loading="lazy">
                        </div>
                    </div>
                    {f'<div><span class="text-xs text-slate-500 uppercase font-bold mb-2 block tracking-wider neon-red">Visual Diff</span><div class="rounded-lg overflow-hidden border border-red-500/30 bg-red-950/10 error-glow"><img src="data:image/png;base64,{t.get("diff_b64")}" class="w-full h-auto" loading="lazy"></div></div>' if t.get("diff_b64") else ""}
                </div>
                """

                error_section = ""
                if t.get("error") and t["type"] != "visual":
                    error_section = f"""
                    <div class="mt-4 p-4 rounded-lg bg-black/40 border border-white/5 font-mono text-sm overflow-x-auto whitespace-pre">
                        <code class="text-red-400">{t["error"]}</code>
                    </div>
                    """

                test_rows += f"""
                <div class="p-6 transition-colors hover:bg-white/[0.02]">
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h3 class="text-xl font-bold mb-1">{t["label"]}</h3>
                            <p class="text-sm text-slate-500 font-mono">{t["type"]} | {t.get("artifact", t.get("command", ""))}</p>
                        </div>
                        <span class="px-4 py-1 rounded-full text-sm font-bold {status_class}">
                            {t["status"]}
                        </span>
                    </div>
                    {visual_section}
                    {error_section}
                </div>
                """

            blocks_html += f"""
            <div class="glass rounded-2xl overflow-hidden mb-6">
                <div class="bg-white/5 p-4 flex justify-between items-center border-b border-white/5">
                    <h2 class="text-lg font-semibold flex items-center gap-2">
                        <span class="px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-400 uppercase tracking-widest">{strategy}</span>
                        Strategy Results
                    </h2>
                </div>
                <div class="divide-y divide-white/5">
                    {test_rows}
                </div>
            </div>
            """

        # Replace the marker
        html = html.replace("<!-- {{ CONTENT }} -->", blocks_html)

        # The template has been cleaned up to use simple replacement markers.
        pass

    with open(report_path, "w") as f:
        f.write(html)

    return str(report_path)


def export_to_allure(results, target_dir):
    """
    Exports results to Allure-compatible JSON files in .aether/allure-results.
    """
    allure_dir = Path(target_dir) / ".aether" / "allure-results"
    allure_dir.mkdir(parents=True, exist_ok=True)

    for res in results:
        test_uuid = str(uuid.uuid4())
        history_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, res["label"] + res["type"]))

        start_time = int(time.time() * 1000)
        end_time = start_time + 100  # Mock duration

        allure_result = {
            "uuid": test_uuid,
            "historyId": history_id,
            "fullName": f"{res.get('strategy', 'unknown')}.{res['label']}",
            "labels": [
                {"name": "suite", "value": res.get("strategy", "unknown")},
                {"name": "testClass", "value": res["type"]},
                {"name": "framework", "value": "aether-lens"},
            ],
            "name": res["label"],
            "status": "passed" if res["status"] == "PASSED" else "failed",
            "stage": "finished",
            "start": start_time,
            "stop": end_time,
            "attachments": [],
        }

        if not res.get("success", True):
            allure_result["statusDetails"] = {
                "message": res.get("error", "Unknown error"),
                "trace": "",
            }

        # Handle attachments
        if res.get("artifact") and os.path.exists(res["artifact"]):
            src_path = Path(res["artifact"])
            ext = src_path.suffix.lower()
            mime = "image/png" if ext == ".png" else "text/plain"
            attachment_uuid = str(uuid.uuid4()) + ext
            dst_path = allure_dir / attachment_uuid

            shutil.copy(src_path, dst_path)

            allure_result["attachments"].append(
                {"name": "Artifact", "source": attachment_uuid, "type": mime}
            )

        # Write the allure result file
        result_file = allure_dir / f"{test_uuid}-result.json"
        with open(result_file, "w") as f:
            json.dump(allure_result, f, indent=2)

    return str(allure_dir)


def sync_results_to_allure_api(
    target_dir, api_url="http://localhost:5050", project_id="default", api_key=None
):
    """
    Syncs results from .aether/allure-results to a remote Allure Docker Service via API.
    """
    import httpx

    allure_dir = Path(target_dir) / ".aether" / "allure-results"
    if not allure_dir.exists():
        return False, "No allure-results directory found."

    results_data = []
    for file in allure_dir.glob("*"):
        if file.is_file():
            with open(file, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
                results_data.append({"file_name": file.name, "content_base64": content})

    if not results_data:
        return False, "No results to sync."

    payload = {"results": results_data}
    sync_url = f"{api_url.rstrip('/')}/send-results?project_id={project_id}"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(sync_url, json=payload, headers=headers, timeout=30.0)
        if response.status_code == 200:
            return True, "Successfully synced results to Allure Dashboard."
        else:
            return (
                False,
                f"API Error ({response.status_code}): {response.text.strip()[:100]}",
            )
    except Exception as e:
        return False, f"Failed to connect to Allure API: {e}"


class KubernetesAllureProvider:
    """Handles ephemeral Allure Dashboard lifecycle in Kubernetes."""

    def __init__(self, namespace="default", port=5050):
        self.namespace = namespace
        self.port = port
        self.pod_name = None
        self._pf_process = None
        self.endpoint_url = f"http://localhost:{port}"

    async def start(self):
        import subprocess

        self.pod_name = f"allure-dash-{uuid.uuid4().hex[:8]}"
        console.print(
            f" -> [Allure] Spawning ephemeral Allure Dashboard pod/{self.pod_name}...",
            style="dim",
        )
        try:
            # Simple run command, we don't need a full deployment for ephemeral use
            subprocess.run(
                [
                    "kubectl",
                    "run",
                    self.pod_name,
                    "--image=frankescobar/allure-docker-service:latest",
                    f"--namespace={self.namespace}",
                    "--port=5050",
                    "--env=CHECK_RESULTS_EVERY_SECONDS=3",
                    "--env=KEEP_HISTORY=1",
                    "--restart=Never",
                ],
                check=True,
                capture_output=True,
            )

            console.print(
                " -> [Allure] Waiting for Dashboard to be ready...", style="dim"
            )
            subprocess.run(
                [
                    "kubectl",
                    "wait",
                    "--for=condition=Ready",
                    f"pod/{self.pod_name}",
                    f"--namespace={self.namespace}",
                    "--timeout=60s",
                ],
                check=True,
                capture_output=True,
            )

            console.print(
                f" -> [Allure] Port-forwarding {self.pod_name} 5050 -> {self.port}...",
                style="dim",
            )
            self._pf_process = subprocess.Popen(
                [
                    "kubectl",
                    "port-forward",
                    f"pod/{self.pod_name}",
                    f"{self.port}:5050",
                    f"--namespace={self.namespace}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            return self.endpoint_url

        except Exception as e:
            console.print(f"[red]Allure launch failed: {e}[/red]")
            await self.stop()
            raise

    async def stop(self):
        import subprocess

        if self._pf_process:
            self._pf_process.terminate()
            self._pf_process.wait()
            self._pf_process = None

        if self.pod_name:
            console.print(
                f" -> [Allure] Cleaning up Dashboard pod/{self.pod_name}...",
                style="dim",
            )
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    "pod",
                    self.pod_name,
                    f"--namespace={self.namespace}",
                    "--force",
                    "--grace-period=0",
                ],
                capture_output=True,
            )
            self.pod_name = None


class DockerAllureProvider:
    """Handles Allure Dashboard lifecycle in Docker."""

    def __init__(self, port=5050):
        self.port = port
        self.container_name = "aether-allure-dash"
        self.endpoint_url = f"http://localhost:{port}"

    async def start(self):
        import docker

        console.print(
            f" -> [Allure] Ensuring Allure Dashboard (Docker) on port {self.port}...",
            style="dim",
        )
        try:
            client = docker.from_env()

            # Check if container exists
            try:
                container = client.containers.get(self.container_name)
                if container.status == "running":
                    console.print(
                        f" -> [Allure] Dashboard already running at {self.endpoint_url}",
                        style="dim",
                    )
                    return self.endpoint_url

                # Exists but stopped
                container.start()
                console.print(
                    f" -> [Allure] Dashboard started at {self.endpoint_url}",
                    style="dim",
                )
                return self.endpoint_url

            except docker.errors.NotFound:
                # Create new
                client.containers.run(
                    "frankescobar/allure-docker-service:latest",
                    name=self.container_name,
                    detach=True,
                    ports={"5050/tcp": self.port},
                    environment={
                        "CHECK_RESULTS_EVERY_SECONDS": "3",
                        "KEEP_HISTORY": "1",
                    },
                )
                console.print(
                    f" -> [Allure] Dashboard created and started at {self.endpoint_url}",
                    style="dim",
                )
                return self.endpoint_url

        except Exception as e:
            console.print(
                f"[yellow]Warning: Docker Allure launch failed: {e}. Reporting might be local-only.[/yellow]"
            )
            return None

    async def stop(self):
        # We might not want to kill it every time to keep history,
        # but providing the method for completeness.
        pass
