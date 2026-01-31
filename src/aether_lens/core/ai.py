import base64
import json
import sys


def get_system_prompt(context, strategy="auto", custom_instruction=None):
    strategy_instruction = ""
    if strategy == "frontend":
        strategy_instruction = "IMPORTANT: Force 'Frontend Strategy'. Treat all changes as UI-impacting and actively propose visual tests."
    elif strategy == "backend":
        strategy_instruction = "IMPORTANT: Force 'Backend Strategy'. Focus on logic/API impacts and do not propose visual tests unless explicitly necessary."
    elif strategy == "microservice":
        strategy_instruction = "IMPORTANT: Force 'Microservice Strategy'. Analyze impacts across multiple repositories/services in the workspace. Check interface compatibility."
    elif strategy == "custom":
        strategy_instruction = f"IMPORTANT: Force 'Custom Strategy'. Follow these specific user instructions:\n{custom_instruction}"

    return f"""
現在の実行環境は Aether 上の K8s クラスター ({context}) です。
Strategy Mode: {strategy}
{strategy_instruction}

あなたは Aether Platform のライブテスト機能 'Aether Vision' の独自解析エージェントです。

タスク:
1. 提供された git diff を解析し、変更が UI またはドキュメントの整合性に与える影響を特定する。
   現在、以下の分岐判断を行ってください:

   [Frontend Change]
   - *.tsx, *.vue, *.css, *.astro 等の変更の場合。
   - 変更の影響を受けるURLを推論し、積極的に Visual Crawl (Playwright) を提案してください。

   [Backend Change]
   - *.go, *.py, *.java 等の API/DB ロジック変更の場合。
   - UI に波及する可能性があるか？ (APIスキーマ変更等) を推論してください。
   - もし UI への影響がなさそうであれば、無理に crawl せず、"Backend logic update detected" と報告してください。

2. **マルチディスプレイサイズ (Desktop, Tablet, Mobile) での表示崩れを防ぐため、最適なビューポート構成を決定する。**
3. Playwright で実行すべきテストセット (複数の解像度、ブラウザ、パス) を提案する。
4. テスト結果は内部の ReportPortal (OSS版) および Allure に記録される必要がある。

3. **実行すべきテストセットを提案する。**
   - type: "visual" -> PlaywrightによるUI検証 (path, viewport必須)
   - type: "command" -> 任意のシェルコマンド実行 (command必須, npm test 等)

回答フォーマット (JSON):
{{
  "change_type": "Frontend | Backend | Mixed",
  "analysis": "日本語による解析結果の概要",
  "recommended_tests": [
    {{ "type": "visual", "label": "Desktop Home", "viewport": "1280x720", "path": "/docs/index.html" }},
    {{ "type": "command", "label": "Unit Test", "command": "npm test" }}
  ],
  "reasoning": "なぜこのテストセットを選んだかの理由"
}}
"""


def run_analysis(
    diff_text, context="default-aether", strategy="auto", custom_instruction=None
):
    # システムプロンプトの構成
    get_system_prompt(context, strategy, custom_instruction)

    # --- LLM API 呼び出しのモック ---
    # 実際には api_key と prompt を使用して API をコールする
    sys.stderr.write(
        f"DEBUG: Using prompt for context: {context}, strategy: {strategy}\n"
    )

    response = {
        "change_type": "Frontend",
        "analysis": f"Aether Lens Docs 解析: {len(diff_text)} bytes の変更を検出。VTI コンセプトに基づき、ビジュアル回帰およびビルド整合性を検証します。",
        "recommended_tests": [
            {
                "type": "visual",
                "label": "Desktop Home (Aesthetics)",
                "browser": "chromium",
                "viewport": "1280x720",
                "path": "/",
            },
            {
                "type": "visual",
                "label": "Mobile Home (Responsive)",
                "browser": "chromium",
                "viewport": "375x667",
                "path": "/",
            },
            {
                "type": "command",
                "label": "Production Build & Link Check",
                "command": "npm run build",
            },
        ],
        "reasoning": "ブランドサイトとしての整合性を守るため、主要な Hero セクションのマルチデバイス表示と、ドキュメントのビルド健全性を優先して推奨します。",
    }
    return response


def main():
    try:
        # stdin から JSON を受け取る想定
        input_data = json.load(sys.stdin)
        diff_base64 = input_data.get("diff", "")
        context = input_data.get("context", "default-aether")
        strategy = input_data.get("strategy", "auto")
        custom_instruction = input_data.get("custom_instruction")

        diff_text = base64.b64decode(diff_base64).decode("utf-8")

        response = run_analysis(diff_text, context, strategy, custom_instruction)
        print(json.dumps(response, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
