import sys
from os import environ

from dependency_injector import containers, providers


class Container(containers.DeclarativeContainer):
    """DI container for core components."""

    @staticmethod
    def validate_environment():
        """Proactively check for environment issues like missing SOCKS support."""
        for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
            val = environ.get(var)
            if val and "socks" in val.lower():
                try:
                    import socksio  # noqa: F401
                except ImportError:
                    print(
                        f"\n[bold red]Error:[/bold red] Environment variable '{var}' is set to use SOCKS ({val}), "
                        "but the 'socksio' package is not installed."
                    )
                    print(
                        "Please install it with: [bold]pip install 'httpx[socks]'[/bold] or unset the proxy variable.\n"
                    )
                    sys.exit(1)

    config = providers.Configuration()

    @staticmethod
    def _create_check_service():
        from .services.check_service import CheckService

        return CheckService()

    @staticmethod
    def _create_execution_controller(config, test_runner, planner, **kwargs):
        from aether_lens.daemon.controller.execution import ExecutionController

        return ExecutionController(
            config=config, test_runner=test_runner, planner=planner
        )

    @staticmethod
    def _create_watch_controller(execution_ctrl, **kwargs):
        from aether_lens.daemon.controller.watcher import WatchController

        return WatchController(
            target_dir=None, on_change_callback=None, orchestrator=execution_ctrl
        )

    @staticmethod
    def _create_test_runner(config, **kwargs):
        from aether_lens.daemon.repository.runner import VisualTestRunner

        return VisualTestRunner(base_url=None, current_dir=None)

    @staticmethod
    def _create_test_planner(**kwargs):
        from aether_lens.core.planning.ai import TestPlanner

        return TestPlanner()

    @staticmethod
    def _create_init_service():
        from .services.init_service import InitService

        return InitService()

    @staticmethod
    def _create_report_service():
        from .services.report_service import ReportService

        return ReportService()

    @staticmethod
    def _create_lifecycle_registry():
        from aether_lens.daemon.repository.lifecycle import LifecycleRegistry

        return LifecycleRegistry()

    @staticmethod
    def _create_loop_handler(
        target_dir=None, pod_name=None, namespace=None, remote_path=None, **kwargs
    ):
        from aether_lens.daemon.repository.session import LocalLensLoopHandler

        return LocalLensLoopHandler(
            target_dir=target_dir,
            pod_name=pod_name,
            namespace=namespace,
            remote_path=remote_path,
        )

    lifecycle_registry = providers.Singleton(_create_lifecycle_registry)
    loop_handler = providers.Factory(_create_loop_handler)

    check_service = providers.Factory(_create_check_service)

    test_runner = providers.Factory(_create_test_runner, config=config.provider)
    test_planner = providers.Factory(_create_test_planner)

    execution_service = providers.Factory(
        _create_execution_controller,
        config=config.provider,
        test_runner=test_runner,
        planner=test_planner,
        lifecycle_registry=lifecycle_registry,
    )
    watch_service = providers.Factory(
        _create_watch_controller, execution_ctrl=execution_service
    )
    init_service = providers.Factory(_create_init_service)
    report_service = providers.Factory(_create_report_service)
