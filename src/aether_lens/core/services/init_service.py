import json
from pathlib import Path


class InitService:
    def generate_default_config(
        self,
        target_dir=".",
        strategy="auto",
        browser_strategy="local",
        allure_strategy="managed",
        **kwargs,
    ):
        """
        Generates a default aether-lens.config.json.
        """
        config_path = Path(target_dir) / "aether-lens.config.json"

        config = {
            "strategy": strategy,
            "browser_strategy": browser_strategy,
            "allure_strategy": allure_strategy,
            "dev_loop": {
                "browser_targets": ["desktop", "tablet", "mobile"],
                "debounce_seconds": 2,
            },
            "tests": [
                {
                    "type": "command",
                    "label": "Lint Check",
                    "command": "npm run lint || echo 'Skip lint'",
                }
            ],
        }
        config.update(kwargs)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        return str(config_path)

    def update_config(self, target_dir, updates):
        config_path = Path(target_dir) / "aether-lens.config.json"
        if not config_path.exists():
            return self.generate_default_config(target_dir, **updates)

        with open(config_path, "r") as f:
            config = json.load(f)

        config.update(updates)

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        return str(config_path)
