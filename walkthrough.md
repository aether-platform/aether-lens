# Aether Lens (Aether Vision) 実装ドキュメント

# walkthrough.md

## Core Directory Reorganization

The `aether_lens.core` directory has been reorganized into sub-packages for better maintainability:

- **domain**: Contains domain models (`models.py`) and events (`events.py`).
- **execution**: Contains pipeline execution logic (`pipeline.py`, `runner.py`, `watcher.py`, `reg_scenarios.py`, `session.py`).
- **planning**: Contains AI planning logic (`ai.py`, `tests.yaml`).
- **presentation**: Contains presentation layer code (`tui.py`, `report.py`, `report_template.html`).

Imports have been updated across the codebase (`client`, `daemon`, `services`) to reflect these changes.
Browser management logic has been simplified, removing `browser.py` and consolidating visual testing into `runner.py`.

## Verification Summary

- Verified that all imports in `src/aether_lens` point to the new locations.
- Verified that `pipeline.py` correctly handles visual tests using `VisualTestRunner`.
- Verified that `client/cli` and `client/mcp` commands are updated.
  Platform 向けのライブテスト機能「Aether Lens」の PoC 基盤実装です。

## 1. 機能概要

- **Lens Loop**: ローカルのコード変更を検知し、K8s 上のコンテナに即座に同期してテストを実行する開発ループ。
- **AI 解析 & マルチストラテジー**: 変更内容 (Git Diff) を AI が解析し、複数のストラテジー（frontend, seo 等）を組み合わせて最適なテストプランを提案。
- **VRT (Visual Regression Testing)**: `pixelmatch` を使用して、前回の実行結果（Baseline）と現在のスクリーンショットをピクセル単位で比較。
- **Conformance Dashboard**: 実行結果や VRT の差分をブラウザで直感的に確認できる HTML レポートと、Allure 互換のデータ出力を提供。
- **リモート実行**: ローカル環境のリソースを使わず、Docker/K8s 上の Browserless コンテナを使用してテストを実行。

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

#### 4. マルチストラテジー設定

`aether-lens.config.json` で複数のストラテジーを定義すると、それらを同時に実行できます。

```json
{
  "strategies": ["frontend", "seo"]
}
```

#### 6. リアルタイム・ダッシュボード (Allure Docker Service)

既存の **Allure Docker Service** を活用することで、リアルタイムなテスト結果の可視化が可能です。このサービスは `.aether/allure-results` ディレクトリを監視し、結果が更新されるたびにダッシュボードを自動更新します。

```bash
# Kubernetes に Allure Dashboard をデプロイ
kubectl apply -f allure-dashboard.yaml
```

## Verification Summary

- **Allure Docker Integration**:
  - `allure-dashboard.yaml` を作成し、既存の Allure イメージを使用してリアルタイム更新を実現しました。
  - 自作のポーリングロジックを削除し、業界標準の Allure ツールに統合しました。
    モードや非 TTY 環境での TUI 起動を抑制し、ハングアップを防止しました。
