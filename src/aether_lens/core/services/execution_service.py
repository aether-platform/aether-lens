import os

from aether_lens.core.pipeline import load_config, run_pipeline


class ExecutionService:
    def __init__(self, config):
        self.config = config

    async def run_once(
        self,
        target_dir=".",
        strategy=None,
        browser_strategy=None,
        browser_url=None,
        launch_browser=None,
        headless=False,
        app_url=None,
        allure_strategy=None,
        allure_endpoint=None,
        allure_project_id=None,
        allure_api_key=None,
        use_tui=True,
        event_emitter=None,
    ):
        target_dir = target_dir or "."
        target_dir = os.path.abspath(target_dir)
        config = load_config(target_dir)

        # Resolve browser strategy
        env_browser = os.getenv("AETHER_BROWSER")
        config_browser = config.get("browser_strategy")

        if not browser_strategy and not env_browser and not config_browser:
            if headless:
                browser_strategy = "docker"
                if launch_browser is None:
                    launch_browser = True
            else:
                browser_strategy = "local"
        else:
            browser_strategy = (
                browser_strategy or env_browser or config_browser or "local"
            )

        if launch_browser is None:
            launch_browser = False

        if not browser_url:
            if browser_strategy == "docker":
                browser_url = "ws://localhost:9222"
            elif browser_strategy == "inpod":
                browser_url = os.getenv(
                    "TEST_RUNNER_URL", "ws://aether-lens-sidecar:9222"
                )

        self.config.browser_strategy.from_value(browser_strategy.replace("-", "_"))
        self.config.browser_url.from_value(browser_url)
        self.config.launch_browser.from_value(launch_browser)
        self.config.headless.from_value(headless)

        selected_strategy = (
            strategy or os.getenv("AETHER_ANALYSIS") or config.get("strategy", "auto")
        )
        custom_instruction = (
            config.get("custom_instruction", "")
            if selected_strategy == "custom"
            else None
        )

        context = os.getenv("KILOCODE_CONTEXT", "default-aether")
        rp_url = os.getenv("REPORTPORTAL_URL")
        allure_dir = os.getenv("ALLURE_RESULTS_DIR")

        # Allure Config
        allure_strategy = (
            allure_strategy
            or os.getenv("ALLURE_STRATEGY")
            or config.get("allure_strategy")
        )
        allure_endpoint = (
            allure_endpoint
            or os.getenv("ALLURE_ENDPOINT")
            or config.get("allure_endpoint")
        )
        allure_project_id = (
            allure_project_id
            or os.getenv("ALLURE_PROJECT_ID")
            or config.get("allure_project_id", "default")
        )
        allure_api_key = (
            allure_api_key
            or os.getenv("ALLURE_API_KEY")
            or config.get("allure_api_key")
        )

        if allure_endpoint:
            os.environ["ALLURE_ENDPOINT"] = allure_endpoint
        if allure_project_id:
            os.environ["ALLURE_PROJECT_ID"] = allure_project_id
        if allure_api_key:
            os.environ["ALLURE_API_KEY"] = allure_api_key

        return await run_pipeline(
            target_dir,
            browser_url,
            context,
            rp_url=rp_url,
            allure_dir=allure_dir,
            strategy=selected_strategy,
            custom_instruction=custom_instruction,
            app_url=app_url,
            use_tui=use_tui,
            event_emitter=event_emitter,
        )
