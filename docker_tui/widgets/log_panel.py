from textual.binding import Binding
from textual.widgets import RichLog


class LogPanel(RichLog):
    BINDINGS: list[Binding] = [
        Binding("w", "scroll_up", show=False),
        Binding("s", "scroll_down", show=False),
    ]
