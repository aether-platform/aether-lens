import asyncio
import json
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


class CheckService:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def log(self, msg, style=""):
        if self.verbose:
            console.print(msg, style=style)

    async def check_prerequisites(self, target_dir="."):
        """
        Core logic to check environment and configuration.
        Returns: dict with check results
        """
        results = {
            "config": {"status": "skipped", "error": None},
            "tools": {},
            "valid": True,
        }

        self.log("[bold blue]Running Prerequisite Checks...[/bold blue]")

        # 1. Config Check
        config_path = Path(target_dir) / "aether-lens.config.json"
        if not config_path.exists():
            self.log(f"[yellow]⚠ Config not found at {config_path}[/yellow]")
            results["config"]["status"] = "missing"
        else:
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)

                # Simple Schema Validation
                required_keys = ["strategy", "browser_strategy"]
                missing = [k for k in required_keys if k not in config]

                if missing:
                    self.log(f"[red]✖ Config Invalid. Missing keys: {missing}[/red]")
                    results["config"] = {
                        "status": "invalid",
                        "error": f"Missing: {missing}",
                    }
                    results["valid"] = False
                else:
                    self.log(
                        f"[green]✔ Config Integrity OK[/green] (Strategy: {config.get('strategy')})"
                    )
                    results["config"]["status"] = "ok"

                    # Check tools based on config
                    browser_strategy = config.get("browser_strategy", "local")
                    if browser_strategy == "docker":
                        await self._check_tool(results, "docker", "docker --version")
                    elif browser_strategy in ["kubernetes", "inpod", "k8s"]:
                        await self._check_tool(
                            results, "kubectl", "kubectl version --client"
                        )

            except json.JSONDecodeError as e:
                self.log(f"[red]✖ Config JSON Error: {e}[/red]")
                results["config"] = {"status": "error", "error": str(e)}
                results["valid"] = False

        # 2. Common Tools Check
        await self._check_tool(results, "node", "node --version")
        await self._check_tool(results, "npm", "npm --version", critical=False)
        await self._check_tool(results, "git", "git --version")

        if results["valid"]:
            self.log("\n[bold green]All checks passed![/bold green]")
        else:
            self.log(
                "\n[bold red]Checks failed. Please review errors above.[/bold red]"
            )

        return results

    async def _check_tool(self, results, tool_name, check_cmd, critical=True):
        try:
            proc = await asyncio.create_subprocess_shell(
                check_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0:
                self.log(f"[green]✔ Tool '{tool_name}' found[/green]")
                results["tools"][tool_name] = True
            else:
                raise RuntimeError("Tool failed")
        except Exception:
            style = "red" if critical else "yellow"
            msg = f"[{style}]✖ Tool '{tool_name}' not found or failed[/{style}]"
            self.log(msg)
            results["tools"][tool_name] = False
            if critical:
                results["valid"] = False
