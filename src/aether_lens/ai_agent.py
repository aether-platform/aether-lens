import base64
import json
import os
import sys

# 注: 実際には openai ライブラリ等を使用して LLM API を直接叩く
# import openai


def get_system_prompt(context):
    return f"""
現在の実行環境は Aether 上の K8s クラスター ({context}) です。
あなたは Aether Platform のライブテスト機能 'Aether Vision' の独自解析エージェントです。

タスク:
1. 提供された git diff を解析し、変更が UI またはドキュメントの整合性に与える影響を特定する。
2. **マルチディスプレイサイズ (Desktop, Tablet, Mobile) での表示崩れを防ぐため、最適なビューポート構成を決定する。**
3. Playwright で実行すべきテストセット (複数の解像度、ブラウザ、パス) を提案する。
4. テスト結果は内部の ReportPortal (OSS版) および Allure に記録される必要がある。

回答フォーマット (JSON):
{{
  "analysis": "日本語による解析結果の概要",
  "recommended_tests": [
    {{ "label": "Desktop", "browser": "chromium", "viewport": "1280x720", "path": "/docs/index.html" }},
    {{ "label": "Mobile", "browser": "chromium", "viewport": "390x844", "path": "/docs/index.html" }}
  ],
  "reasoning": "なぜこのマルチディスプレイセットを選んだかの理由"
}}
"""


def main():
    try:
        # stdin から JSON を受け取る想定
        input_data = json.load(sys.stdin)
        diff_base64 = input_data.get("diff", "")
        context = input_data.get("context", "default-aether")

        # LLM API Key の取得 (環境変数から)
        api_key = os.getenv("LLM_API_KEY", "mock-key")

        diff_text = base64.b64decode(diff_base64).decode("utf-8")

        # システムプロンプトの構成
        prompt = get_system_prompt(context)

        # --- LLM API 呼び出しのモック ---
        # 実際には api_key と prompt を使用して API をコールする
        # (Lint fix: variables are considered used in the logs)
        sys.stderr.write(f"DEBUG: Using prompt for context: {context}\n")

        response = {
            "analysis": f"独自エージェントによる解析: {len(diff_text)} bytes の変更を検出。OSS版スタック (Browserless/ReportPortal) 向けのテスト構成を作成します。",
            "recommended_tests": [
                {
                    "label": "Desktop",
                    "browser": "chromium",
                    "viewport": "1280x720",
                    "path": "/starlight/index.html",
                },
                {
                    "label": "Mobile",
                    "browser": "chromium",
                    "viewport": "390x844",
                    "path": "/starlight/index.html",
                },
            ],
            "reasoning": "マルチディスプレイサイズでのレイアウト整合性を確認するため、主要な2つの解像度を推奨します。",
        }

        print(json.dumps(response, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
