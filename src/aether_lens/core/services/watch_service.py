import os
import signal

from rich.console import Console

from aether_lens.core.pipeline import (
    run_deployment_hook,
    start_background_process,
    wait_for_health_check,
)
from aether_lens.core.watcher import start_watcher

console = Console(stderr=True)


class WatchService:
    def __init__(self):
        self.cleanup_data = None  # Stores {"cmd": str, "proc": Popen}

    async def setup_deployment(self, target_dir, browser_strategy, config):
        """Standardized deployment hook logic."""
        deployment_config = config.get("deployment", {})
        current_env = browser_strategy.replace("-", "_")
        env_deploy = deployment_config.get(current_env)

        deploy_cmd = None
        cleanup_cmd = None
        health_check_url = config.get("health_check_url")

        if env_deploy:
            deploy_type = env_deploy.get("type")
            health_check_url = env_deploy.get("health_check") or health_check_url

            if deploy_type == "compose":
                compose_file = env_deploy.get("file", "docker-compose.yaml")
                service = env_deploy.get("service", "")
                deploy_cmd = f"docker compose -f {compose_file} up -d {service}"
                cleanup_cmd = f"docker compose -f {compose_file} down"
            elif deploy_type == "kubectl":
                manifests = env_deploy.get("manifests", [])
                if isinstance(manifests, list):
                    manifests = " ".join([f"-f {m}" for m in manifests])
                namespace = env_deploy.get("namespace", "default")
                deploy_cmd = f"kubectl apply {manifests} -n {namespace}"
                cleanup_cmd = f"kubectl delete {manifests} -n {namespace}"
            elif deploy_type == "kustomize":
                path = env_deploy.get("path", ".")
                namespace = env_deploy.get("namespace", "")
                deploy_cmd = f"kubectl apply -k {path}"
                cleanup_cmd = f"kubectl delete -k {path}"
                if namespace:
                    deploy_cmd += f" -n {namespace}"
                    cleanup_cmd += f" -n {namespace}"
            elif deploy_type == "custom":
                deploy_cmd = env_deploy.get("deploy_command")
                cleanup_cmd = env_deploy.get("cleanup_command")

        # Overrides
        deploy_cmd = os.getenv("DEPLOY_COMMAND") or deploy_cmd
        cleanup_cmd = os.getenv("CLEANUP_COMMAND") or cleanup_cmd
        is_background = env_deploy.get("background", False) if env_deploy else False

        if deploy_cmd:
            if is_background:
                proc = start_background_process(deploy_cmd, cwd=target_dir)
                if not proc:
                    raise RuntimeError("Failed to start background process.")
                self.cleanup_data = {"cmd": cleanup_cmd, "proc": proc}
            else:
                success, _ = run_deployment_hook(deploy_cmd, cwd=target_dir)
                if not success:
                    raise RuntimeError("Deployment hook failed.")
                self.cleanup_data = {"cmd": cleanup_cmd, "proc": None}

            if health_check_url:
                os.environ["HEALTH_CHECK_URL"] = health_check_url
                if not await wait_for_health_check(health_check_url):
                    raise RuntimeError(f"Health check failed for {health_check_url}")

        return self.cleanup_data

    def start_watching(self, target_dir, on_change_callback):
        return start_watcher(target_dir, on_change_callback, blocking=False)

    async def perform_cleanup(self, target_dir):
        if not self.cleanup_data:
            return

        cleanup_cmd = self.cleanup_data.get("cmd")
        proc = self.cleanup_data.get("proc")

        if proc:
            console.print(
                f"\n[bold cyan]Stopping background process (PID: {proc.pid})...[/bold cyan]"
            )
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()

        if cleanup_cmd:
            console.print("\n[bold cyan]Running Cleanup Command...[/bold cyan]")
            run_deployment_hook(cleanup_cmd, cwd=target_dir)

        self.cleanup_data = None
