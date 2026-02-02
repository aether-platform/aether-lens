import asyncio
import json

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Footer, Header, Label, RichLog
except ImportError:
    # Allow import for type checking, but runtime will fail if used
    App = object
    ComposeResult = None
    Binding = None
    Container = Horizontal = Vertical = None
    Message = object
    ModalScreen = object
    Button = DataTable = Footer = Header = Label = RichLog = None


class BrowserConfirmModal(ModalScreen):
    """Modal screen for browser launch confirmation."""

    def __init__(self, question: str = "Launch local browser?") -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        # Use simple yielding to avoid context manager issues in async modal
        yield Vertical(
            Label(self.question, id="question"),
            Horizontal(
                Button("Yes", variant="primary", id="yes"),
                Button("No", variant="error", id="no"),
                id="buttons",
            ),
            id="modal-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)


class TestUpdate(Message):
    """Message to update a test row."""

    def __init__(self, test_id: str, fields: dict) -> None:
        super().__init__()
        self.test_id = test_id
        self.fields = fields


class PipelineLogMessage(Message):
    """Message to add a log entry."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class PipelineDashboard(App):
    """Aether Lens Pipeline Dashboard."""

    CSS = """
    #main-container {
        layout: grid;
        grid-size: 1 2;
        grid-rows: 1fr 1fr;
    }
    #test-table-container {
        border: solid green;
        margin: 1;
    }
    #log-container {
        border: solid blue;
        margin: 1;
    }
    #modal-container {
        width: 40;
        height: 10;
        border: thick $primary;
        background: $surface;
        padding: 1;
        align: center middle;
    }
    #buttons {
        align: center middle;
        height: 3;
    }
    #question {
        content-align: center middle;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, tests_data, strategy_name="auto"):
        super().__init__()
        self.tests_data = tests_data
        self.strategy_name = strategy_name
        self.test_rows = {}  # Map label/id to row key
        self.run_logic_callback = None
        self.log_buffer = []  # Store all logs: (label|None, message)
        self.current_filter_label = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            with Vertical(id="test-table-container"):
                yield Label("[bold]Recommended Tests[/bold]")
                yield DataTable(id="test-table")
            with Vertical(id="log-container"):
                yield Label(
                    "[bold]Current Pipeline Phase:[/bold] [yellow]Initializing...[/yellow]",
                    id="phase-status",
                )
                yield Label("[bold]Execution Logs[/bold]")
                yield RichLog(id="execution-log", markup=True)
        yield Label(
            " [bold blue]Dashboard:[/bold blue] [underline]http://localhost:5050/allure-docker-service/projects/default/reports/latest/index.html[/underline]\n"
            " [dim]Note: TUI shows latest history (auto-scroll). Refer to Allure for full persistent logs.[/dim]",
            id="allure-url",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "#", "Strategy", "Test Name", "Browser Check", "Connection", "Status"
        )

        for i, test in enumerate(self.tests_data):
            label = test.get("label", "Unknown")
            is_visual = test.get("type") == "visual"
            browser_val = "Pending" if is_visual else "N/A"
            conn_val = "Pending" if is_visual else "N/A"

            # Use the actual strategy name passed in
            strategy = self.strategy_name
            row_key = table.add_row(
                str(i + 1), strategy, label, browser_val, conn_val, "Waiting", key=label
            )
            self.test_rows[label] = row_key
            # Store label map for reverse lookup if needed
            # self.row_keys_to_labels[row_key] = label

        if self.run_logic_callback:
            # Run logic as a worker to not block UI
            self.run_worker(self.run_logic_callback(self), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection to filter/highlight logs."""
        # Get label from key
        label = event.row_key.value
        self.current_filter_label = label

        # Refresh Log Widget
        log_widget = self.query_one("#execution-log", RichLog)
        log_widget.clear()

        if label:
            log_widget.write(
                f"[bold cyan]--- Filtering logs for: {label} ---[/bold cyan]"
            )
            for log_label, msg in self.log_buffer:
                if log_label == label or log_label is None:
                    # 'None' means global log, always show or maybe optional?
                    # Let's show global logs + selected test logs
                    log_widget.write(msg)
        else:
            # Show all
            log_widget.write("[bold cyan]--- Showing all logs ---[/bold cyan]")
            for _, msg in self.log_buffer:
                log_widget.write(msg)

    async def ask_browser_confirmation(
        self, question: str, default: bool = True
    ) -> bool:
        """Helper to show modal without blocking the event loop or requiring a worker thread."""
        try:
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            def handle_dismiss(result: bool) -> None:
                if not future.done():
                    future.set_result(result)

            # Use push_screen with a callback instead of push_screen_wait
            # self.app is our PipelineDashboard instance
            self.app.push_screen(BrowserConfirmModal(question), callback=handle_dismiss)

            return await future
        except Exception as e:
            self.log_message(
                f"[yellow]UI Modal Error: {e}. Falling back to default ({default}).[/yellow]"
            )
            return default

    def handle_event(self, event_data: dict):
        """Processes an event received from the executor."""
        etype = event_data.get("type")
        if etype == "test_started":
            self.update_test_status(
                event_data["label"],
                strategy=event_data.get("strategy", ""),
                test_status="実行中...",
            )
        elif etype == "test_progress":
            self.update_test_status(
                event_data["label"], test_status=event_data.get("status_text", "")
            )
        elif etype == "test_finished":
            status = event_data.get("status", "UNKNOWN")
            error = event_data.get("error")
            status_color = "bold green" if status == "PASSED" else "bold red"

            display_status = f"[{status_color}]{status}[/{status_color}]"
            if status != "PASSED" and error:
                # Truncate and clean error for one-line display
                clean_err = error.replace("\n", " ").strip()
                if len(clean_err) > 30:
                    clean_err = clean_err[:27] + "..."
                display_status += f" ([dim]{clean_err}[/dim])"

            self.update_test_status(
                event_data["label"],
                test_status=display_status,
            )
        elif etype == "log":
            msg = event_data.get("message", "")
            if "PHASE:" in msg:
                # Update phase status label
                phase_name = msg.split("PHASE:")[1].split("=")[0].strip()
                self.update_phase_status(phase_name)
            self.log_message(msg)
        elif etype == "result":
            self.show_completion_message()

    def update_test_status(self, label: str, **kwargs):
        """Update a specific test row in the table."""
        self.post_message(TestUpdate(label, kwargs))

    def on_test_update(self, message: TestUpdate) -> None:
        table = self.query_one(DataTable)
        row_key = self.test_rows.get(message.test_id)
        if row_key:
            # Added "#" column at index 0
            col_map = {
                "strategy": 1,
                "label": 2,
                "browser_check": 3,
                "connection": 4,
                "test_status": 5,
            }
            # Access columns list directly to get the column key by index
            cols = list(table.columns.values())
            for key, val in message.fields.items():
                if key in col_map:
                    col_idx = col_map[key]
                    if col_idx < len(cols):
                        table.update_cell(row_key, cols[col_idx].key, val)

    async def stream_executor_events(self, executable, args):
        """Spawns an executor process and streams its events to the dashboard."""
        self.log_message(f"Spawning executor: {executable} {' '.join(args)}")

        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stdout():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                try:
                    event_data = json.loads(line.decode().strip())
                    etype = event_data.get("type")
                    if etype in ["test_started", "test_progress", "test_finished"]:
                        self.call_from_thread(
                            lambda: self.update_test_status(
                                event_data.get("label"),
                                test_status=event_data.get("status")
                                if "status" in event_data
                                else event_data.get("status_text")
                                if "status_text" in event_data
                                else "",
                            )
                        )
                    elif (
                        etype == "log"
                    ):  # Assuming PipelineLogEvent corresponds to type "log"
                        self.call_from_thread(
                            lambda: self.log_message(event_data.get("message"))
                        )
                    else:
                        # Fallback to original handler for other event types or if type is missing
                        self.handle_event(event_data)

                except Exception:
                    # Treat raw text as log
                    self.log_message(line.decode().strip())

        async def read_stderr():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                self.log_message(f"[red]{line.decode().strip()}[/red]")

        await asyncio.gather(read_stdout(), read_stderr())
        await process.wait()
        self.show_completion_message()

    def update_phase_status(self, phase_name: str):
        try:
            label = self.query_one("#phase-status", Label)
            label.update(
                f"[bold]Current Pipeline Phase:[/bold] [yellow]{phase_name}[/yellow]"
            )
        except Exception:
            pass

    def log_message(self, message: str, label: str = None):
        # Buffer the log (limit to 500 lines)
        self.log_buffer.append((label, message))
        if len(self.log_buffer) > 500:
            self.log_buffer.pop(0)

        try:
            log_widget = self.query_one("#execution-log", RichLog)
            log_widget.max_lines = 500

            # Write to widget ONLY if matches filter
            should_write = False
            if self.current_filter_label is None:
                should_write = True
            elif label == self.current_filter_label or label is None:
                should_write = True

            if should_write:
                log_widget.write(message)
        except Exception:
            pass  # Fallback or ignore if TUI isn't ready

    def show_completion_message(self):
        """Show clear completion instruction."""
        try:
            log_widget = self.query_one("#execution-log", RichLog)
            log_widget.write("")
            log_widget.write("=" * 40)
            log_widget.write("Pipeline Execution Completed.")
            log_widget.write("Press 'q' to exit.")
            log_widget.write("=" * 40)
        except Exception:
            pass
