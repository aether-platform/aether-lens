import base64
import os
import subprocess

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
        self.target_dir = target_dir
        self.pod_name = pod_name
        self.namespace = namespace
        self.remote_path = remote_path
        self.browser_strategy = browser_strategy
        self.browser_url = browser_url

    def sync_and_trigger(self, changed_file_path=None):
        try:
            # 1. Get Diff (Git)
            diff = self.get_git_diff()
            diff_b64 = base64.b64encode(diff.encode("utf-8")).decode("utf-8")

            # 2. Sync File (kubectl cp)
            if changed_file_path:
                rel_path = os.path.relpath(changed_file_path, self.target_dir)
                dest_path = os.path.join(self.remote_path, rel_path).replace("\\", "/")

                subprocess.run(
                    [
                        "kubectl",
                        "cp",
                        "-n",
                        self.namespace,
                        changed_file_path,
                        f"{self.namespace}/{self.pod_name}:{dest_path}",
                        "-c",
                        "aether-lens",
                    ],
                    check=True,
                )

            # 3. Trigger Remote Agent (kubectl exec)
            env_vars = f"AETHER_DIFF_B64={diff_b64} TARGET_DIR={self.remote_path}"
            browser_opts = f"--browser-strategy {self.browser_strategy}"
            if self.browser_url:
                browser_opts += f" --browser-url {self.browser_url}"

            subprocess.run(
                [
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
                    f"{env_vars} aether-lens run {browser_opts} {self.remote_path}",
                ],
                check=True,
            )
        except Exception as e:
            console.print(f"[bold red]Sync Error:[/bold red] {e}")

    def get_git_diff(self):
        try:
            result = subprocess.run(
                ["git", "-C", self.target_dir, "diff", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            if not result.stdout:
                result = subprocess.run(
                    ["git", "-C", self.target_dir, "diff"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            return result.stdout
        except Exception:
            return ""
