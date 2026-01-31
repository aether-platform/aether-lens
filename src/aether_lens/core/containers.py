from dependency_injector import containers, providers

from . import browser


class Container(containers.DeclarativeContainer):
    """DI container for core components."""

    config = providers.Configuration()

    # Browser Provider Selector: Switch between local, docker, and inpod strategies.
    browser_provider = providers.Selector(
        config.browser_strategy,
        local=providers.Factory(browser.LocalBrowserProvider, headless=True),
        docker=providers.Factory(
            browser.CDPBrowserProvider, endpoint_url=config.browser_url
        ),
        inpod=providers.Factory(
            browser.CDPBrowserProvider, endpoint_url=config.browser_url
        ),
    )
