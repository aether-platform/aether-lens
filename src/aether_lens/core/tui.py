from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, Log


class BrowserConfirmModal(ModalScreen[bool]):
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            with Vertical(id="test-table-container"):
                yield Label("[bold]Recommended Tests[/bold]")
                yield DataTable(id="test-table")
            with Vertical(id="log-container"):
                yield Label("[bold]Execution Logs[/bold]")
                yield Log(id="execution-log")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "#", "Strategy", "Test Name", "Browser Check", "Connection", "Status"
        )

        for i, test in enumerate(self.tests_data):
            label = test.get("label", "Unknown")
            # Use the actual strategy name passed in
            strategy = self.strategy_name
            row_key = table.add_row(
                str(i + 1), strategy, label, "Pending", "Pending", "Waiting", key=label
            )
            self.test_rows[label] = row_key

    async def ask_browser_confirmation(
        self, question: str, default: bool = True
    ) -> bool:
        """Helper to show modal from outside the event loop if needed."""
        # This will be called from the pipeline logic
        return await self.push_screen_wait(BrowserConfirmModal(question))

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

    def log_message(self, message: str):
        self.query_one(Log).write_line(message)
