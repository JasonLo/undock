from textual import events
from textual.widget import Widget


class ResizeHandle(Widget):
    DEFAULT_CSS = """
    ResizeHandle {
        width: 1;
        height: 1fr;
        background: $surface-darken-2;
    }
    ResizeHandle:hover {
        background: $accent-darken-1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._dragging: bool = False

    def render(self) -> str:
        return ""

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._dragging = False
        self.release_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        parent = self.parent
        if not isinstance(parent, Widget):
            return
        total = parent.region.width
        left_width = event.screen_x - parent.region.x
        left_width = max(10, min(total - 11, left_width))  # min 10 cols each side
        right_width = total - left_width - 1  # 1 for the handle itself
        self.app.query_one("#main-table").styles.width = left_width
        self.app.query_one("#log-panel").styles.width = right_width
        event.stop()
