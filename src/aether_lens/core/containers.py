from dependency_injector import containers, providers

from . import browser


class Container(containers.DeclarativeContainer):
    """DI container for core components."""

    config = providers.Configuration()

    # Browser Provider Selector: Switch between local, docker, and inpod strategies.
    browser_provider = providers.Selector(
        config.browser_strategy,
        local=providers.Factory(browser.LocalBrowserProvider, headless=config.headless),
        docker=providers.Factory(
            browser.CDPBrowserProvider,
            endpoint_url=config.browser_url,
            launch=config.launch_browser,
        ),
        k8s=providers.Factory(
            browser.KubernetesBrowserProvider,
            endpoint_url=config.browser_url,
            launch=config.launch_browser,
        ),
        inpod=providers.Factory(
            browser.CDPBrowserProvider, endpoint_url=config.browser_url, launch=False
        ),
        dry_run=providers.Factory(browser.LogOnlyBrowserProvider),
    )

    # Services (Using Factory to avoid circular imports during class definition)
    @staticmethod
    def _create_check_service():
        from .services.check_service import CheckService

        return CheckService()

    @staticmethod
    def _create_execution_service(config, **kwargs):
        from .services.execution_service import ExecutionService

        return ExecutionService(config=config)

    @staticmethod
    def _create_watch_service(**kwargs):
        from .services.watch_service import WatchService

        return WatchService()

    @staticmethod
    def _create_init_service():
        from .services.init_service import InitService

        return InitService()

    @staticmethod
    def _create_report_service():
        from .services.report_service import ReportService

        return ReportService()

    @staticmethod
    def _create_daemon_service():
        from .services.daemon_service import DaemonService

        return DaemonService()

    check_service = providers.Factory(_create_check_service)
    execution_service = providers.Factory(
        _create_execution_service, config=config.provider
    )
    watch_service = providers.Factory(_create_watch_service)
    init_service = providers.Factory(_create_init_service)
    report_service = providers.Factory(_create_report_service)
    daemon_service = providers.Factory(_create_daemon_service)
