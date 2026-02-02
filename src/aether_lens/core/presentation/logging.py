from typing import Any, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

console = Console(stderr=True)


class PipelineFormatter:
    """Utility for formatting pipeline logs and events for the TUI."""

    @staticmethod
    def format_log(label: str, status: str, output: Optional[Any] = None) -> str:
        """Format a test result log message."""
        status_color = "bold green" if status == "PASSED" else "bold red"
        msg = f" -> Test '{label}' [{status_color}]{status}[/{status_color}]"

        if output:
            try:
                if isinstance(output, str):
                    rich_text = Text.from_ansi(output)
                    formatted_output = (
                        rich_text.markup if "\x1b[" in output else escape(output)
                    )
                else:
                    formatted_output = escape(str(output))

                output_color = "dim" if status == "PASSED" else "red"
                msg += f": [{output_color}]{formatted_output}[/{output_color}]"
            except Exception:
                msg += f": [dim]{escape(str(output))}[/dim]"
        return msg

    @staticmethod
    def get_intro_panel(target_dir: str, strategy: str) -> Panel:
        """Create a consistent intro panel for the pipeline."""
        strategy_disp = f"{strategy} (Custom)" if strategy == "custom" else strategy
        msg = f"[bold blue]Aether Lens[/bold blue] Pipeline Triggered for [cyan]{target_dir}[/cyan] (Strategy: {strategy_disp})"
        return Panel(msg, expand=False)

    @staticmethod
    def format_phase(phase: str) -> str:
        """Format a phase transition message."""
        return f"\n[bold magenta]>>> Phase: {phase}[/bold magenta]"

    @staticmethod
    def format_error(message: str) -> str:
        """Format an error message."""
        return f"[bold red]Error:[/bold red] {message}"

    @staticmethod
    def format_warning(message: str) -> str:
        """Format a warning message."""
        return f"[yellow]Warning: {message}[/yellow]"

    @staticmethod
    def format_service_start(name: str, command: str, strategy: str) -> str:
        """Format service startup message."""
        return f" -> [Management] Starting service: [cyan]{name}[/cyan] ({command}) [Strategy: {strategy}]"

    @staticmethod
    def format_sdk_orchestration_message() -> str:
        """Format SDK orchestration message."""
        return "    - [cyan][SDK][/cyan] Orchestrating via Python-on-Whales SDK..."

    @staticmethod
    def format_session_saved(filename: str) -> str:
        """Format session saved message."""
        return f" -> [Execution] Session saved: [cyan]{filename}[/cyan]"

    @staticmethod
    def format_deployment_hook_start(command: str) -> str:
        """Format deployment hook start message."""
        return f" -> [Execution] Running deployment hook: [cyan]{command}[/cyan]"

    @staticmethod
    def format_deployment_hook_success() -> str:
        """Format deployment hook success message."""
        return "    - [green]Deployment OK[/green]"

    @staticmethod
    def format_deployment_hook_failure(error: str) -> str:
        """Format deployment hook failure message."""
        return f"      [red]{error}[/red]"

    @staticmethod
    def format_health_check_start(url: str) -> str:
        """Format health check start message."""
        return f" -> [Management] Waiting for health check: [cyan]{url}[/cyan] ..."

    @staticmethod
    def format_health_check_success() -> str:
        """Format health check success message."""
        return "    - [green]Health Check OK[/green]"

    @staticmethod
    def format_health_check_timeout() -> str:
        """Format health check timeout message."""
        return "    - [red]Health Check Timeout[/red]"
