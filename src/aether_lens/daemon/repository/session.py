import asyncio
import base64
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


class LocalLensLoopHandler:
    """
    Handles a single synchronization and trigger event for the local development loop.
    """

    def __init__(
        self,
        target_dir,
        pod_name,
        namespace,
        remote_path,
        browser_strategy="inpod",
        browser_url=None,
    ):
        self.target_dir = Path(target_dir)
        self.pod_name = pod_name
        self.namespace = namespace
        self.remote_path = remote_path
        self.browser_strategy = browser_strategy
        self.browser_url = browser_url

    async def sync_and_trigger(self, changed_file_path=None):
        try:
            # 1. Get Diff (Git)
            diff = await self.get_git_diff()
            diff_b64 = base64.b64encode(diff.encode("utf-8")).decode("utf-8")

            # 2. Sync File (kubectl cp)
            if changed_file_path:
                rel_path = Path(changed_file_path).relative_to(self.target_dir)
                dest_path = (Path(self.remote_path) / rel_path).as_posix()

                proc = await asyncio.create_subprocess_exec(
                    "kubectl",
                    "cp",
                    "-n",
                    self.namespace,
                    str(changed_file_path),
                    f"{self.namespace}/{self.pod_name}:{dest_path}",
                    "-c",
                    "aether-lens",
                )
                await proc.wait()

            # 3. Trigger Remote Agent (kubectl exec)
            env_vars = f"AETHER_DIFF_B64={diff_b64} TARGET_DIR={self.remote_path}"
            browser_opts = f"--browser-strategy {self.browser_strategy}"
            if self.browser_url:
                browser_opts += f" --browser-url {self.browser_url}"

            trigger_cmd = (
                f"{env_vars} aether-lens run {browser_opts} {self.remote_path}"
            )

            proc = await asyncio.create_subprocess_exec(
                "kubectl",
                "exec",
                "-n",
                self.namespace,
                self.pod_name,
                "-c",
                "aether-lens",
                "--",
                "bin/sh",
                "-c",
                trigger_cmd,
            )
            await proc.wait()

        except Exception as e:
            console.print(f"[bold red]Sync Error:[/bold red] {e}")

    async def get_git_diff(self):
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(self.target_dir),
                "diff",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            diff = stdout.decode().strip()

            if not diff:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "-C",
                    str(self.target_dir),
                    "diff",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                diff = stdout.decode().strip()

            return diff
        except Exception:
            return ""
