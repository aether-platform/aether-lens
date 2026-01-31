import sys
from abc import ABC, abstractmethod

from rich.console import Console
from rich.prompt import Confirm

console = Console(stderr=True)


class BrowserProvider(ABC):
    """Base class for browser strategy providers."""

    def __init__(self):
        self._browser = None

    @abstractmethod
    async def start(self, playwright):
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

    def __init__(self, headless: bool = True):
        super().__init__()
        self.headless = headless

    async def start(self, playwright):
        if sys.stdin.isatty():
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
    """Strategy that connects to a browser via CDP (Chrome DevTools Protocol)."""

    def __init__(self, endpoint_url: str):
        super().__init__()
        self.endpoint_url = endpoint_url

    async def start(self, playwright):
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
            if sys.stdin.isatty():
                if Confirm.ask("Launch local browser as fallback?", default=True):
                    console.print(
                        " -> [Browser] Switching to Local Browser strategy...",
                        style="dim",
                    )
                    self._browser = await playwright.chromium.launch()
                    console.print(
                        " -> [Browser] Local browser started (fallback).", style="dim"
                    )
                    return
            raise

    async def get_browser(self, playwright):
        return await super().get_browser(playwright)
