from pathlib import Path
from typing import Any, Dict, List

import yaml

from aether_lens.core.domain.models import TestCase


class TestPlanner:
    def __init__(self, definition_file: str = "tests.yaml"):
        self.definition_path = Path(__file__).parent / definition_file
        self.definitions: List[Dict] = self._load_definitions()

    def _load_definitions(self) -> List[Dict]:
        if self.definition_path.exists():
            try:
                with open(self.definition_path, "r") as f:
                    return yaml.safe_load(f) or []
            except Exception:
                return []
        return []

    def run_analysis(
        self,
        diff: str,
        context: str = "",
        strategy: str = "auto",
        custom_instruction: str = "",
    ) -> Dict[str, Any]:
        """
        Analyzes the changes and generates a test plan.
        """
        analysis_text = f"Analyzed {len(diff)} chars of diff."

        recommended_tests = []

        for test_def in self.definitions:
            # Convert YAML dict to TestCase model
            # Ensuring we handle defaults
            t = TestCase(
                id=test_def.get("id"),
                type="command",
                label=test_def.get("label", test_def.get("id")),
                command=test_def.get("command"),
                description=test_def.get("description"),
                tags=test_def.get("tags", []),
            )

            recommended_tests.append(
                {
                    "type": t.type,
                    "label": t.label,
                    "command": t.command,
                    "description": t.description,
                }
            )

        if not recommended_tests:
            # Fallback
            recommended_tests.append(
                {
                    "type": "command",
                    "label": "Home Layout Check (Fallback)",
                    "command": "python3 -m aether_lens.core.runner layout_check",
                }
            )

        return {
            "change_type": "Frontend" if strategy != "backend" else "Backend",
            "impact_analysis": analysis_text,
            "recommended_tests": recommended_tests,
        }


# Singleton instance
_planner = TestPlanner()
run_analysis = _planner.run_analysis


def main():
    pass


if __name__ == "__main__":
    main()
