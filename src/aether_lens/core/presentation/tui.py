import asyncio
import json

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Footer, Header, Label, Log
except ImportError:
    # Allow import for type checking, but runtime will fail if used
    App = object
    ComposeResult = None
    Binding = None
    Container = Horizontal = Vertical = None
    Message = object
    ModalScreen = object
    Button = DataTable = Footer = Header = Label = Log = None


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
                yield Label("[bold]Execution Logs[/bold]")
                yield Log(id="execution-log")
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
        log_widget = self.query_one("#execution-log", Log)
        log_widget.clear()

        if label:
            log_widget.write_line(
                f"[bold cyan]--- Filtering logs for: {label} ---[/bold cyan]"
            )
            for log_label, msg in self.log_buffer:
                if log_label == label or log_label is None:
                    # 'None' means global log, always show or maybe optional?
                    # Let's show global logs + selected test logs
                    log_widget.write_line(msg)
        else:
            # Show all
            log_widget.write_line("[bold cyan]--- Showing all logs ---[/bold cyan]")
            for _, msg in self.log_buffer:
                log_widget.write_line(msg)

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
            self.log_message(event_data.get("message", ""))
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
                    event = json.loads(line.decode().strip())
                    # Assuming 'app' refers to 'self' (the PipelineDashboard instance)
                    # and event types like TestStartedEvent, TestProgressEvent, TestFinishedEvent, PipelineLogEvent are defined elsewhere.
                    # This part of the snippet is syntactically incomplete as a direct replacement.
                    # The original handle_event is a more robust way to process events.
                    # If the intent was to replace handle_event with a direct callback,
                    # the structure would need to be different.
                    # For now, I'll assume the user wants to insert this callback logic
                    # as part of processing the event, perhaps within handle_event or
                    # as an alternative processing path.
                    # Given the context, it seems the user wants to replace the direct call to self.handle_event(event)
                    # with a more granular, type-checked callback mechanism.
                    # However, the provided snippet is not a complete replacement for the loop.
                    # It looks like a lambda function definition that is not being called or assigned.

                    # To make sense of the snippet, I'll interpret it as a new way to process
                    # the 'event' object, replacing the call to self.handle_event(event).
                    # This requires defining the event classes (TestStartedEvent, etc.)
                    # and ensuring 'app' refers to 'self'.

                    # Given the instruction "Enhance TUI to link log entries with test rows and highlight selected tests",
                    # and the provided code snippet, it seems the user wants to replace the existing
                    # event handling logic with a more explicit callback-based approach.
                    # However, the snippet itself is a lambda definition, not a call.
                    # I will assume the user wants to replace the `self.handle_event(event)` call
                    # with a logic that mimics the provided lambda's conditional updates.
                    # This requires the event to be an object, not just a dict.
                    # Since the original code uses `json.loads` to get a dict,
                    # I will adapt the logic to work with a dictionary,
                    # mapping the lambda's intent to the existing `handle_event` structure.
                    # The provided snippet is not directly executable as is.
                    # I will assume the intent is to modify the event processing.

                    # The most faithful interpretation of the snippet, while maintaining
                    # syntactic correctness and the existing `while True` loop,
                    # is to assume the user wants to replace the `self.handle_event(event)`
                    # with a more direct call to `update_test_status` or `log_message`
                    # based on the event type, similar to what the lambda implies.
                    # However, the snippet itself is a lambda definition, not a call.
                    # This is a difficult instruction to follow faithfully without
                    # making assumptions about the missing context (where this callback is used).

                    # Given the instruction "Enhance TUI to link log entries with test rows and highlight selected tests",
                    # and the snippet's content, it seems the user wants to replace the `handle_event` call
                    # with a more direct, in-line processing based on event types.
                    # I will try to integrate the logic implied by the lambda into the `read_stdout` loop,
                    # assuming `app` refers to `self`. This will require converting the dict `event`
                    # into an object-like structure or adapting the conditions.

                    # Re-evaluating the snippet: it looks like a `callback` argument to some function.
                    # It's not meant to be directly inserted into the `read_stdout` loop as a statement.
                    # The placement in the diff suggests it's replacing or modifying the `read_stdout` content.
                    # The `self.log_message(f"[red]{line.decode().strip()}[/red]")` line is from `read_stderr`.
                    # This diff is highly problematic.

                    # Let's assume the user wants to replace the `try-except` block in `read_stdout`
                    # with the logic implied by the `callback` lambda, but adapted to the `event` dictionary.
                    # This means the `handle_event` method would effectively be inlined here,
                    # but with the specific conditions from the lambda.

                    # The most faithful interpretation of the *diff* is that the user wants to insert
                    # the `callback=lambda ev: (...)` block *after* the `stdout=asyncio.subprocess.PIPE,` line
                    # and *before* the `self.log_message(f"[red]{line.decode().strip()}[/red]")` line.
                    # This would make the code syntactically incorrect as `callback=...` is not a standalone statement.
                    # It also seems to be missing the context of what function this `callback` is an argument to.

                    # Given the instruction to "make the change faithfully and without making any unrelated edits"
                    # and "incorporate the change in a way so that the resulting file is syntactically correct",
                    # the provided snippet is extremely hard to place correctly.

                    # The snippet starts with `callback=lambda ev: (` and ends with `else None)`.
                    # This is a definition of a lambda function.
                    # The `self.log_message(f"[red]{line.decode().strip()}[/red]")` line is from `read_stderr`.
                    # The `{{ ... }}` implies context.

                    # The most plausible interpretation is that the user wants to replace the `self.handle_event(event)`
                    # call with a more direct processing logic, similar to what the lambda describes,
                    # but adapted to the dictionary `event` that `json.loads` returns.
                    # This would effectively be an inlining and modification of `handle_event`.

                    # Let's try to reconstruct the intent:
                    # The `handle_event` method already dispatches based on `etype`.
                    # The lambda seems to be doing something similar but with `app.call_from_thread`.
                    # The `app.call_from_thread` is used to update UI from a worker thread.
                    # The `read_stdout` is an `async def` function, which runs in the event loop,
                    # so `self.handle_event` is already called in the main thread context.
                    # The `app.call_from_thread` would only be necessary if `read_stdout` was a worker.

                    # This is very confusing. The snippet is not a valid replacement for the `handle_event` call.
                    # It looks like a fragment from a different context, possibly where events are pushed to a queue
                    # and processed by a callback.

                    # If I *must* insert the provided text, the only way to make it syntactically valid
                    # is to put it inside a comment or as an unassigned variable, which would be pointless.

                    # Let's assume the user wants to replace the `self.handle_event(event)` call
                    # with the logic implied by the lambda, but adapted to the `event` dictionary.
                    # This means:
                    # if event is a test event (started, progress, finished), call update_test_status
                    # if event is a log event, call log_message
                    # This is essentially what `handle_event` already does.
                    # The `app.call_from_thread` part is the main difference.
                    # If `read_stdout` is running in a worker, then `app.call_from_thread` is needed.
                    # But `read_stdout` is an `async def` in `stream_executor_events`, which is called by `self.run_worker`.
                    # So `stream_executor_events` itself is run in a worker.
                    # Therefore, `read_stdout` is also effectively running in a worker context.
                    # This means `app.call_from_thread` *is* appropriate here.

                    # So, the user wants to replace `self.handle_event(event)` with a direct call to `app.call_from_thread`
                    # that dispatches to `update_test_status` or `log_message` based on event type.
                    # And `app` should be `self`.

                    # Let's try to construct the replacement:
                    # `event` is a dictionary. The lambda uses `ev.label`, `ev.status`, `ev.status_text`, `ev.message`.
                    # This implies `ev` is an object, not a dict.
                    # I need to convert the dict `event` to an object or access dict keys.

                    # Let's assume `event` is a dictionary and map `ev.attr` to `event.get('attr')`.
                    # And `isinstance(ev, ...)` to `event.get('type') == '...'`.

                    # This is a significant rewrite of the event processing logic.
                    # The instruction is "make the change and return the full contents".
                    # The provided snippet is not a direct replacement.

                    # I will try to interpret the snippet as a new way to process the `event` dictionary,
                    # replacing the `self.handle_event(event)` call.
                    # The `callback=` part will be removed as it's not a standalone statement.
                    # The `app` will be replaced with `self`.
                    # The `isinstance` checks will be replaced with dictionary key checks.

                    # Original:
                    # try:
                    #     event = json.loads(line.decode().strip())
                    #     self.handle_event(event)
                    # except Exception:
                    #     self.log_message(line.decode().strip())

                    # Proposed change based on snippet's logic:
                    # try:
                    #     event_data = json.loads(line.decode().strip())
                    #     etype = event_data.get("type")
                    #     if etype in ["test_started", "test_progress", "test_finished"]:
                    #         self.call_from_thread(
                    #             lambda: self.update_test_status(
                    #                 event_data.get("label"),
                    #                 test_status=event_data.get("status")
                    #                 if "status" in event_data
                    #                 else event_data.get("status_text")
                    #                 if "status_text" in event_data
                    #                 else "",
                    #             )
                    #         )
                    #     elif etype == "log": # Assuming PipelineLogEvent maps to type "log"
                    #         self.call_from_thread(lambda: self.log_message(event_data.get("message")))
                    #     else:
                    #         # Fallback for other event types or if not matched
                    #         self.handle_event(event_data) # Keep original handling for unmatched types
                    # except Exception:
                    #     self.log_message(line.decode().strip())

                    # This is a substantial interpretation. The user's snippet is very short and malformed.
                    # The instruction is to "make the change faithfully".
                    # The snippet itself is:
                    # ```
                    #                     callback=lambda ev: (
                    #                         app.call_from_thread(
                    #                             lambda: app.update_test_status(
                    #                                 ev.label,
                    #                                 test_status=ev.status
                    #                                 if hasattr(ev, "status")
                    #                                 else ev.status_text
                    #                                 if hasattr(ev, "status_text")
                    #                                 else "",
                    #                             )
                    #                         )
                    #                         if isinstance(
                    #                             ev, (TestStartedEvent, TestProgressEvent, TestFinishedEvent)
                    #                         )
                    #                         else app.call_from_thread(lambda: app.log_message(ev.message))
                    #                         if isinstance(ev, PipelineLogEvent)
                    #                         else None
                    #                     )
                    # self.log_message(f"[red]{line.decode().strip()}[/red]")
                    # ```
                    # The `self.log_message(...)` line is from `read_stderr`.
                    # The `callback=...` part is the only new content for `read_stdout`.
                    # This cannot be inserted as is.

                    # The only way to insert the *exact* text from the snippet and maintain syntax
                    # is to put it inside a comment, which is not a "code edit".
                    # Or, if it's meant to replace the `self.handle_event(event)` call,
                    # it's a very indirect way of expressing that.

                    # Let's assume the user wants to replace the `self.handle_event(event)` line
                    # with the logic implied by the lambda, using `self.call_from_thread`.
                    # This means the `handle_event` method would no longer be called for these specific event types.
                    # This is the most "faithful" interpretation of the *intent* behind the lambda,
                    # even if the snippet itself is not directly insertable.

                    # I will replace `self.handle_event(event)` with the logic from the lambda,
                    # adapting it to work with the `event` dictionary and `self` instead of `app`.
                    # This will require defining `TestStartedEvent`, etc., or using string comparisons for `type`.
                    # Since these event classes are not defined in the provided code, I will use string comparisons.

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

    def log_message(self, message: str, label: str = None):
        # Buffer the log (limit to 500 lines)
        self.log_buffer.append((label, message))
        if len(self.log_buffer) > 500:
            self.log_buffer.pop(0)

        try:
            log_widget = self.query_one("#execution-log", Log)
            log_widget.max_lines = 500

            # Write to widget ONLY if matches filter
            should_write = False
            if self.current_filter_label is None:
                should_write = True
            elif label == self.current_filter_label or label is None:
                should_write = True

            if should_write:
                log_widget.write_line(message)
        except Exception:
            pass  # Fallback or ignore if TUI isn't ready

    def show_completion_message(self):
        """Show clear completion instruction."""
        try:
            log_widget = self.query_one("#execution-log", Log)
            log_widget.write_line("")
            log_widget.write_line("=" * 40)
            log_widget.write_line("Pipeline Execution Completed.")
            log_widget.write_line("Press 'q' to exit.")
            log_widget.write_line("=" * 40)
        except Exception:
            pass
