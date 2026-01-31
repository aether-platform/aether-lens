Aether Lens (Aether Vision) PoC 実装引き継ぎドキュメント
Aether Platform 向けのライブテスト機能「Aether Lens」の PoC 基盤実装が完了しました。WSL 側のエージェントがスムーズに作業を継続するためのガイドです。

1. プロジェクトの目的
Aether Platform (code-server) に、設定不要 (Zero Config) でテスト・可視化・AI 解析が連動する機能を統合する。

マルチサイズ検証: AI がモバイル/デスクトップ等の最適な検証セットを提案。
ハイブリッド実行: ローカル (オンデマンド) と K8s (サイドカー) の両対応。
2. コンポーネント構成 (src 構成)
標準的な src レイアウトを採用し、aether-lens コマンドとしてインストール可能です。

aether-lens/
├── src/
│   └── aether_lens/
│       ├── __init__.py
│       ├── ai_agent.py       # LLM 直接連携による解析ロジック (現在はプロンプト設計とモック)
│       └── entrypoint.py     # パイプライン制御 (git diff 解析 -> AI 推奨 -> テスト実行)
├── pyproject.toml            # パッケージ定義 (aether-lens コマンドとして公開)
├── README.md                 # 総合ガイド
├── TILT_GUIDE.md             # Tilt 環境への統合手順
└── deployment.yaml           # Browserless OSS サイドカー用の K8s マニフェスト
3. 採用済みの OSS スタック
追加コストを抑えつつ、プラットフォームとして成立させるための選定です。

Browserless (OSS): ブラウザ実行基盤。
ReportPortal (OSS): テスト結果の集約・管理。
Allure: テスト結果の可視化 (レポート生成)。
独自エージェント: KiloCode への依存を排除し、LLM API を直接利用する内製 Python スクリプト。
4. 現在の状態
 プロジェクト構造の整備 (src 構成, pyproject.toml導入)
 AI エージェントのプロンプト設計と基本フレームワークの実装
 ハイブリッド実行 (LOCAL/SIDECAR) の自動判別ロジックの実装
 Tilt 連携ガイドの作成
5. 次のステップ (引き継ぎ事項)
WSL 側のエージェントで以下の実装を進めてください：

Playwright 連携の具体化: 
entrypoint.py
 内のテスト実行ループを、実際の Playwright API 呼び出しに置き換える。
ReportPortal API 連携: テスト結果を ReportPortal OSS に送信するロジックの実装。
LLM API 実装: 
ai_agent.py
 内のモック部分を、実際の LLM (OpenAI/Anthropic 等) への API 呼び出しに接続。
code-server UI 統合: Aether UI 上にテスト結果を表示する IF/Tab の実装検討。
6. セットアップ方法
cd c:/workspace/vibecoding-platform/aether-lens
pip install -e .
# 実行
aether-lens

Comment
Ctrl+Alt+M
