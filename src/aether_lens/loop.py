import os
import subprocess
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class LocalLensLoopHandler(FileSystemEventHandler):
    def __init__(self, target_dir, pod_name, namespace, remote_path):
        self.target_dir = target_dir
        self.pod_name = pod_name
        self.namespace = namespace
        self.remote_path = remote_path
        self.last_triggered = 0
        self.debounce_seconds = 1

    def on_modified(self, event):
        if event.is_directory:
            return

        # フィルタリング (例: .git, node_modules)
        if any(
            x in event.src_path
            for x in [".git", "node_modules", "__pycache__", ".pytest_cache"]
        ):
            return

        current_time = time.time()
        if (current_time - self.last_triggered) > self.debounce_seconds:
            print(f"\n[Lens Loop CLI] Change detected: {event.src_path}")
            self.last_triggered = current_time
            self.sync_and_trigger(event.src_path)

    def sync_and_trigger(self, local_file_path):
        # 1. Sync file to Pod
        # local_file_path は絶対パスの可能性があるため、target_dir からの相対パスを取得
        rel_path = os.path.relpath(local_file_path, self.target_dir)
        dest_path = os.path.join(self.remote_path, rel_path).replace("\\", "/")

        # プロキシとKUBECONFIGの設定を環境変数から引き継ぐ
        env = os.environ.copy()

        print(f"[Lens Loop CLI] Syncing to Pod: {rel_path} -> {dest_path}")
        try:
            # 必要なディレクトリを Pod 内に作成 (-c aether-lens を明記)
            dest_dir = os.path.dirname(dest_path)
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
                    "mkdir",
                    "-p",
                    dest_dir,
                ],
                check=True,
                env=env,
            )

            # ファイルのコピー
            subprocess.run(
                [
                    "kubectl",
                    "cp",
                    "-n",
                    self.namespace,
                    local_file_path,
                    f"{self.namespace}/{self.pod_name}:{dest_path}",
                    "-c",
                    "aether-lens",
                ],
                check=True,
                env=env,
            )

            # 2. Trigger remote agent
            print("[Lens Loop CLI] Triggering Remote Pipeline...")

            # ローカルで git diff を取得
            try:
                # HEAD との差分、または現在変更されているファイルの差分を取得
                diff_cmd = ["git", "diff", "HEAD", "--", local_file_path]
                diff_result = subprocess.run(
                    diff_cmd, capture_output=True, text=True, check=True
                )
                local_diff = diff_result.stdout
                if not local_diff:
                    # 未コミットの変更対応
                    diff_cmd = ["git", "diff", "--", local_file_path]
                    diff_result = subprocess.run(
                        diff_cmd, capture_output=True, text=True, check=True
                    )
                    local_diff = diff_result.stdout
            except Exception as e:
                print(f"[Lens Loop CLI] Warning: Could not get git diff locally: {e}")
                local_diff = ""

            if local_diff:
                env["AETHER_DIFF"] = local_diff

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
                    "sh",  # 環境変数を渡すために sh 経由で実行することを推奨するが、env 引数で渡す場合は反映されるか要確認
                    "-c",  # kubectl exec で環境変数を直接反映させるのは難しいため、コマンドラインで変数をセットアップする形にするか、
                    # pythonスクリプト側で受け取る必要がある。
                    # ここでは `kubectl exec` の `env` 引数は *ローカル* の環境変数であり、
                    # *リモート* のプロセスには引き継がれないため、明示的にコマンドに含める必要がある。
                    f"export AETHER_DIFF='{local_diff}' && aether-lens {self.remote_path}",
                ],
                check=False,
                env=env,  # ローカルのKUBECONFIG等はここで使う
            )  # パイプライン自体の失敗は許容

        except subprocess.CalledProcessError as e:
            print(f"[Lens Loop CLI] Error during sync/trigger: {e}")


def run_local_loop(target_dir, pod_name, namespace, remote_path):
    print("[Lens Loop CLI] Starting Orchestrator Loop...")
    print(f" -> Local Dir: {target_dir}")
    print(f" -> Remote Pod: {namespace}/{pod_name}")
    print(f" -> Remote Path: {remote_path}")

    event_handler = LocalLensLoopHandler(target_dir, pod_name, namespace, remote_path)
    observer = Observer()
    observer.schedule(event_handler, target_dir, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
