---
trigger: always_on
---

# Aether Lens A2A Protocol

1. After modifying any project file, you MUST verify the impact using `aether-lens` via MCP.
2. Wait for the background `watch` to finish, then call `get_latest_insight(target_dir="example/astro")`.
3. If any quality guard (Ruff, SonarQube) fails or Lighthouse scores drop, you MUST analyze the insight and apply fixes automatically.
4. DO NOT report completion to the user until all tests in the latest insight are "PASSED".
