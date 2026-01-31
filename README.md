# Aether Lens (Aether Vision) - ライブテスト & AI 解析機能

Aether Platform 上で動作する、設定不要（Zero Config）なライブテスト、ビジュアル検証、および AI による解析を統合した PoC 実装です。

## 1. コンポーネント構成 & ツール選定

| コンポーネント   | 選定ツール           | ライセンス区分  | 実装上の注意点                                      |
| :--------------- | :------------------- | :-------------- | :-------------------------------------------------- |
| **K8s実行基盤**  | **Browserless**      | OSS版           | セルフホストにより無料で運用開始。管理機能は自作。  |
| **テスト集約**   | **ReportPortal**     | OSS版           | 基本機能を活用。AI分析は外部LLM（GPT-4等）で代替。  |
| **テスト可視化** | **Allure**           | Framework (OSS) | TestOpsではなく、無料のレポート生成機能のみを利用。 |
| **AI解析**       | **独自エージェント** | 内製/OSS接続    | API経由でLLM（GPT-4等）を直接叩き、解析を実行。     |

## 2. プリイン構成のゴール

Aether 上で起動する開発環境に、以下の機能を組み込み、テスト・可視化・AI解析が連動する状態を提供します。

- **Multi-Display Focus**: Mobile, Tablet, Desktop の各解像度での表示崩れを AI が自動検知・提案。
- **Hybrid Execution**: ローカル開発時のオンデマンド実行と、プラットフォーム上のサイドカー実行の両方に対応。
- **Direct LLM Analysis**: 独自エージェントが LLM API を直接利用し、日本語での解析とテストセット推奨を実行。
- **Transparent Reporting**: Allure による可視化と ReportPortal による履歴管理。

## 3. ハイブリッド実行モデル

実行環境に応じて以下の2つのプロセスを自動判別します。

### A. オンデマンド実行 (LOCAL)

ローカルでのリソース消費を最小化するため、テスト実行時のみブラウザを起動します。

- 起動コマンド: `pip install -e . && aether-lens`

### B. サイドカー構成 (SIDECAR)

プラットフォーム（K8s）上でのクリーンな実行環境と、ブラウザ画面のストリーミングを提供します。

- マニフェスト: `deployment.yaml`
- 変数設定: `TEST_RUNNER_URL` (WebSocket URL)

## 4. プロジェクト構成 (src レイアウト)

```text
aether-lens/
├── pyproject.toml
├── src/
│   └── aether_lens/
│       ├── __init__.py
│       ├── ai_agent.py
│       └── entrypoint.py
└── deployment.yaml
```

## 5. 始め方

1. `vibecoding-platform/aether-lens` ディレクトリでパッケージをインストールします。
   ```bash
   pip install -e .
   ```
2. ターゲットディレクトリを指定して実行します。
   ```bash
   aether-lens c:/workspace/vibecoding-platform/app/public/docs
   ```
<- Sync Test Sat Jan 31 15:29:16 JST 2026 -->
<- Sync Test 2 Sat Jan 31 15:31:07 JST 2026 -->
<- Sync Test 3 Sat Jan 31 15:34:01 JST 2026 -->
<- Sync Test 4 Sat Jan 31 15:34:27 JST 2026 -->
<- Sync Test 5 Sat Jan 31 15:35:02 JST 2026 -->
