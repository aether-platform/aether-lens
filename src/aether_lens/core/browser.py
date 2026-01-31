import subprocess
import sys
import time
import uuid
from abc import ABC, abstractmethod
from unittest.mock import AsyncMock

import docker
import docker.errors
import httpx
from rich.console import Console
from rich.prompt import Confirm

console = Console(stderr=True)


class BrowserProvider(ABC):
    """Base class for browser strategy providers."""

    def __init__(self, launch: bool = False, headless: bool = False):
        self._browser = None
        self.launch = launch
        self.headless = headless

    @abstractmethod
    async def start(self, playwright, display_callback=None):
        """Pre-starts/connects the browser, possibly prompting the user."""
        pass

    async def get_browser(self, playwright):
        """Returns the started Playwright browser instance."""
        if not self._browser:
            await self.start(playwright)
        return self._browser

    async def close(self):
        """Closes the browser instance if it was started."""
        if self._browser:
            await self._browser.close()
            self._browser = None


class LocalBrowserProvider(BrowserProvider):
    """Strategy that launches a local Playwright browser."""

    def __init__(self, launch: bool = True, headless: bool = False):
        # Local always launches
        super().__init__(launch=launch, headless=headless)

    async def start(self, playwright, display_callback=None):
        if display_callback:
            confirmed = await display_callback("Launch local browser?", default=True)
            if not confirmed:
                raise RuntimeError("Local browser launch cancelled by user.")
        elif sys.stdin.isatty():
            if not Confirm.ask(
                "[white] -> [Browser] Launch local browser?[/white]", default=True
            ):
                raise RuntimeError("Local browser launch cancelled by user.")

        console.print(" -> [Browser] Starting local browser...", style="dim")
        self._browser = await playwright.chromium.launch(headless=self.headless)
        console.print(" -> [Browser] Local browser started.", style="dim")

    async def get_browser(self, playwright):
        return await super().get_browser(playwright)


class CDPBrowserProvider(BrowserProvider):
    """Strategy that connects to a browser via CDP, optionally launching a container."""

    def __init__(
        self,
        endpoint_url: str,
        launch: bool = False,
        port: int = 9222,
        image: str = "browserless/chrome:latest",
        headless: bool = True,
    ):
        super().__init__(launch=launch, headless=headless)
        self.endpoint_url = endpoint_url
        self.port = port
        self.image = image
        self.container_id = None

    async def _launch_container(self):
        console.print(
            f" -> [Browser] Starting Docker container ({self.image})...", style="dim"
        )
        try:
            client = docker.from_env()
            container = client.containers.run(
                self.image,
                detach=True,
                ports={"3000/tcp": None},  # Random port
                extra_hosts={"host.docker.internal": "host-gateway"},
                remove=True,
            )
            self.container_id = container.id

            # Reload to get ports
            container.reload()
            ports = container.ports
            if not ports or "3000/tcp" not in ports or not ports["3000/tcp"]:
                raise RuntimeError("Docker failed to assign a port to the container.")

            host_port = ports["3000/tcp"][0]["HostPort"]
            self.port = int(host_port)

            console.print(
                f" -> [Browser] Container started: {self.container_id[:12]} on port {self.port}",
                style="dim",
            )

            # Brief pause to allow the container's internal processes to bind to port 3000
            time.sleep(2)

            # Wait for readiness with Exponential Backoff
            max_wait = 60
            start_time = time.time()
            url = f"http://127.0.0.1:{self.port}/json/version"
            ready = False
            last_error = None
            delay = 0.5

            with console.status(
                f"[bold blue]Waiting for browser at {url}...[/bold blue]"
            ) as status:
                attempt = 0
                while time.time() - start_time < max_wait:
                    # Fail fast if container died
                    container.reload()
                    if container.status != "running":
                        raise RuntimeError(
                            f"Container stopped unexpectedly. Status: {container.status}"
                        )

                    attempt += 1
                    try:
                        response = httpx.get(url, timeout=2.0)
                        if response.status_code == 200:
                            ready = True
                            break
                    except Exception as e:
                        last_error = e
                        if attempt > 1:
                            elapsed = int(time.time() - start_time)
                            # Show error class/msg partially
                            err_str = str(e).split("(")[0]  # Simplified error
                            status.update(
                                f"[bold yellow]Connecting to browser... [{err_str}] ({elapsed}s)[/bold yellow]"
                            )
                        time.sleep(delay)
                        delay = min(delay * 1.5, 5.0)

            if not ready:
                raise RuntimeError(
                    f"Browser container failed to become ready at {url} after {max_wait}s. Last error: {last_error}"
                )

            # Update endpoint URL
            self.endpoint_url = f"ws://127.0.0.1:{self.port}"

        except docker.errors.DockerException as e:
            console.print(f"[red]Docker start failed: {e}[/red]")
            raise RuntimeError(f"Failed to start Docker container: {e}") from e

    async def start(self, playwright, display_callback=None):
        if self._browser and self._browser.is_connected():
            return

        if self.launch and not self.container_id:
            await self._launch_container()

        try:
            console.print(
                f" -> [Browser] Connecting to {self.endpoint_url}...", style="dim"
            )
            self._browser = await playwright.chromium.connect_over_cdp(
                self.endpoint_url
            )
            console.print(" -> [Browser] Connected to remote browser.", style="dim")
        except Exception as e:
            console.print(
                f"[bold yellow][Warning] Could not connect to {self.endpoint_url}: {e}[/bold yellow]"
            )
            if self.launch:
                await self.close()
                raise e

            console.print(
                "[blue]Tip: Use --launch-browser to automatically start a container/pod.[/blue]"
            )

            # Fallback
            confirmed = False
            if display_callback:
                confirmed = await display_callback(
                    "Launch local browser as fallback?", default=True
                )
            elif sys.stdin.isatty():
                confirmed = Confirm.ask(
                    "Launch local browser as fallback?", default=True
                )

            if confirmed:
                console.print(
                    " -> [Browser] Switching to Local Browser strategy...", style="dim"
                )
                self._browser = await playwright.chromium.launch()
                console.print(
                    " -> [Browser] Local browser started (fallback).", style="dim"
                )
                return
            raise

    async def get_browser(self, playwright):
        return await super().get_browser(playwright)

    async def close(self):
        await super().close()
        if self.container_id:
            console.print(
                f" -> [Browser] Stopping container {self.container_id[:12]}...",
                style="dim",
            )
            try:
                client = docker.from_env()
                container = client.containers.get(self.container_id)
                container.stop()
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to stop container {self.container_id}: {e}[/yellow]"
                )
            self.container_id = None


class LogOnlyBrowserProvider(BrowserProvider):
    """Strategy that only logs the actions without running a real browser."""

    def __init__(self, launch: bool = False):
        super().__init__(launch=launch)

    async def start(self, playwright, display_callback=None):
        console.print(" -> [Browser] Using Log-Only strategy (Dry Run).", style="dim")
        self._browser = AsyncMock()
        context = AsyncMock()
        page = AsyncMock()
        self._browser.new_context.return_value = context
        context.new_page.return_value = page

        async def mock_goto(url, **kwargs):
            console.print(f" -> [DryRun] Navigating to: [cyan]{url}[/cyan]")

        page.goto.side_effect = mock_goto

        async def mock_screenshot(path=None, **kwargs):
            console.print(f" -> [DryRun] Capturing screenshot to: [cyan]{path}[/cyan]")

        page.screenshot.side_effect = mock_screenshot

        self._browser.close = AsyncMock()


class KubernetesBrowserProvider(BrowserProvider):
    """Strategy that uses Kubernetes, optionally launching a Pod."""

    def __init__(
        self,
        endpoint_url: str = None,
        launch: bool = False,
        namespace: str = "default",
        image: str = "browserless/chrome:latest",
    ):
        super().__init__(launch=launch)
        self.endpoint_url = endpoint_url
        self.namespace = namespace
        self.image = image
        self.pod_name = None
        self.local_port = 9222
        self._pf_process = None

    async def _launch_pod(self):
        self.pod_name = f"aether-browser-{uuid.uuid4().hex[:8]}"
        console.print(
            f" -> [Browser] Spawning K8s Pod {self.pod_name} ({self.image})...",
            style="dim",
        )
        try:
            subprocess.run(
                [
                    "kubectl",
                    "run",
                    self.pod_name,
                    f"--image={self.image}",
                    f"--namespace={self.namespace}",
                    "--port=3000",
                    "--restart=Never",
                ],
                check=True,
                capture_output=True,
            )

            console.print(" -> [Browser] Waiting for Pod to be ready...", style="dim")
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
                f" -> [Browser] Port-forwarding pod/{self.pod_name} 3000 -> {self.local_port}...",
                style="dim",
            )
            self._pf_process = subprocess.Popen(
                [
                    "kubectl",
                    "port-forward",
                    f"pod/{self.pod_name}",
                    f"{self.local_port}:3000",
                    f"--namespace={self.namespace}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            self.endpoint_url = f"ws://localhost:{self.local_port}"

        except subprocess.CalledProcessError as e:
            console.print(
                f"[red]K8s Pod launch failed: {e.stderr if e.stderr else str(e)}[/red]"
            )
            await self.close()
            raise RuntimeError("Failed to start K8s browser pod") from e

    async def start(self, playwright, display_callback=None):
        if self.launch:
            await self._launch_pod()

        # If not launching, we expect endpoint_url to be already set (e.g. from env var)
        if not self.endpoint_url:
            raise RuntimeError(
                "No browser URL provided and launch=False for K8s strategy."
            )

        try:
            self._browser = await playwright.chromium.connect_over_cdp(
                self.endpoint_url
            )
            console.print(" -> [Browser] Connected to K8s Browser.", style="dim")
        except Exception as e:
            console.print(f"[red]Failed to connect to K8s Browser: {e}[/red]")
            await self.close()
            # No local driver fallback for K8s strategy usually
            raise e

    async def close(self):
        await super().close()
        if self._pf_process:
            self._pf_process.terminate()
            self._pf_process.wait()
            self._pf_process = None
        if self.pod_name:
            console.print(f" -> [Browser] Deleting Pod {self.pod_name}...", style="dim")
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
