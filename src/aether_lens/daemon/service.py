from aether_lens.core.pipeline import run_pipeline
from aether_lens.core.watcher import start_watcher


class LensDaemon:
    """
    Aether Lens Daemon service that manages the life cycle of background tasks.
    """

    def __init__(self):
        pass

    def run_watch_loop(
        self,
        target_dir,
        sidecar_url,
        context,
        rp_url=None,
        allure_dir=None,
        strategy="auto",
        custom_instruction=None,
    ):
        """
        Starts the file watcher and executes the pipeline on changes.
        """

        def on_change(path):
            run_pipeline(
                target_dir,
                sidecar_url,
                context,
                rp_url,
                allure_dir,
                strategy=strategy,
                custom_instruction=custom_instruction,
            )

        # Initial execution
        run_pipeline(
            target_dir,
            sidecar_url,
            context,
            rp_url,
            allure_dir,
            strategy=strategy,
            custom_instruction=custom_instruction,
        )

        # Enter watch loop
        start_watcher(target_dir, on_change)
