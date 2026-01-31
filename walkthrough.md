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
│       ├── core/             # 共有ロジック (AI, Pipeline, Watcher)
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

- Docker
- Kind
- kubectl
- Python 3.10+

### ローカル開発環境の構築

```bash
# クラスターとレジストリのセットアップ、イメージのビルド・デプロイ
./scripts/setup_local_env.sh
```

### Lens Loop の開始

ローカルの変更を監視し、Kind 上のポッドでテストを実行します。

```bash
# ターゲットポッド名は `kubectl get pods -n aether-system` で確認、または自動検出
aether-lens . --loop --pod <POD_NAME> --namespace aether-system
```

### 実行フロー

1. ローカルファイルの変更を検知。
2. 変更ファイルを `kubectl cp` でポッドに同期。
3. ローカルで `git diff` を取得し、`AETHER_DIFF_B64` 環境変数としてポッドに注入。
4. ポッド内で `aether-lens` コマンドが実行され、AI 解析とテストが行われる。
5. 結果がコンソールに出力される。
