from aether_lens.daemon.loop_daemon import run_loop_daemon
from aether_lens.daemon.registry import stop_loop


class DaemonService:
    def start_loop(
        self,
        target_dir,
        pod_name,
        namespace="aether-system",
        remote_path="/app/project",
        blocking=False,
        browser_strategy="inpod",
        browser_url=None,
    ):
        return run_loop_daemon(
            target_dir,
            pod_name,
            namespace,
            remote_path,
            blocking=blocking,
            browser_strategy=browser_strategy,
            browser_url=browser_url,
        )

    def stop_loop(self, target_dir):
        return stop_loop(target_dir)
