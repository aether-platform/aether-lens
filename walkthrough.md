# Aether Lens (Aether Vision) 実装ドキュメント

Aether Platform 向けのライブテスト機能「Aether Lens」の PoC 基盤実装です。

## 1. 機能概要

- **Lens Loop**: ローカルのコード変更を検知し、K8s 上のコンテナに即座に同期してテストを実行する開発ループ。
- **AI 解析**: 変更内容 (Git Diff) を AI が解析し、影響範囲に基づいた最適なテストプラン（解像度、ブラウザ、パス）を提案。
- **リモート実行**: ローカル環境のリソースを使わず、K8s クラスター上の Browserless コンテナを使用してテストを実行。

## 2. コンポーネント構成

```text
aether-lens/
├── src/
│   └── aether_lens/
│       ├── core/             # 共有ロジック (AI, Pipeline, Watcher, Browser)
│       ├── client/
│       │   ├── cli/          # CLI エントリポイントおよび Loop 管理
│       │   └── mcp/          # MCP サーバー実装
│       └── daemon/           # 将来のバックグラウンドプロセス用
├── pyproject.toml            # パッケージ定義 (aether_lens.client.cli.main:main)
├── deployment.yaml           # K8s マニフェスト
└── scripts/
    └── setup_local_env.sh    # ローカル開発環境セットアップ
```

## 3. セットアップと実行

### 前提条件

- Docker (または Kubernetes クラスター)
- Python 3.10+
- uv (推奨)

### インストールと実行

`uvx` を使用して、インストールなしで直接実行できます。ブラウザ機能を使用する場合は `[browser]` オプションを指定してください。

```bash
# 基本実行 (Dry Run)
uvx --from . aether-lens run --browser dry-run

# ブラウザテスト (Managed Docker)
uvx --from ".[browser]" aether-lens run --browser docker --launch-browser
```

### コマンドとブラウザ戦略

#### 1. 単発実行 (`run`)

パイプラインを1回だけ実行します。CI環境などに適しています。
実行完了後、自動起動したブラウザコンテナは**即座に削除**されます。

```bash
aether-lens run [TARGET_DIR] [OPTIONS]
```

#### 2. 監視実行 (`watch`)

ファイル変更を監視してパイプラインを再実行します。開発中の使用に適しています。
**ブラウザコンテナは初回に起動され、セッション中は維持されます。** 終了 (`Ctrl+C`) 時にクリーンアップされます。

```bash
aether-lens watch [TARGET_DIR] [OPTIONS]
```

#### 3. ブラウザ戦略オプション (`--browser` / `--launch-browser`)

テスト実行に使用するブラウザ環境を指定します。

| `--browser` 指定  | `--launch-browser` | 挙動概要                                                     |
| :---------------- | :----------------: | :----------------------------------------------------------- |
| `local` (default) |       (無視)       | ローカルのPlaywrightブラウザを使用 (要 `playwright install`) |
| `docker`          |      `False`       | 既存のDockerコンテナ (`localhost:9222`) に接続               |
| `docker`          |       `True`       | **推奨**: Dockerコンテナを自動起動・接続・削除               |
| `k8s`             |      `False`       | 指定されたURL (env: `TEST_RUNNER_URL`) へ接続                |
| `k8s`             |       `True`       | **推奨**: K8s Podを自動起動・接続・削除 (要 `kubectl`)       |
| `inpod`           |      `False`       | Pod内部実行用 (Sidecar等へ接続)                              |
| `dry-run`         |         -          | ブラウザを使用せずログ出力のみ                               |

#### 実行例

**マネージドDocker (手軽に環境分離)**

```bash
# 明示的指定
aether-lens run --browser docker --launch-browser

# 省略形 (Headlessモードで自動的にDockerを起動)
aether-lens run --headless
```

## Verification Summary

- **Browser Connection Robustness**:
  - Replaced `subprocess` with `docker` Python SDK for reliable container management.
  - Implemented random port assignment (port 0 binding) to prevent conflicts.
  - Added exponential backoff (up to 60s) using `httpx` for reliable readiness checks.
- **Persistent Watch Session**:
  - Updated `watch` command to keep the browser container alive during the session.
  - Browser is only launched once and reused for all pipeline runs in watch mode.
  - Proper cleanup ensures container is removed on exit (Ctrl+C).
- **Core Refactoring**:
  - Validated `aether-lens` package structure and `uvx` compatibility.
  - Verified `run` (ephemeral) vs `watch` (persistent) behavior.
