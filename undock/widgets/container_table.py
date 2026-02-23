import webbrowser
from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable


class ContainerTable(DataTable):
    BINDINGS: list[Binding] = [
        Binding("w", "cursor_up", show=False),
        Binding("s", "cursor_down", show=False),
        Binding("enter", "open_browser", "Open in Browser"),
        Binding("e", "start_build", "Start+Build"),
        Binding("f", "force_rebuild", "Force Rebuild"),
        Binding("x", "stop", "Stop"),
        Binding("E", "start_build_all", "Start+Build All"),
        Binding("F", "force_rebuild_all", "Rebuild All"),
    ]

    class RunService(Message):
        def __init__(self, service: str, extra_flags: list[str]) -> None:
            super().__init__()
            self.service = service
            self.extra_flags = extra_flags

    class RunAllServices(Message):
        def __init__(self, extra_flags: list[str]) -> None:
            super().__init__()
            self.extra_flags = extra_flags

    class StopContainer(Message):
        def __init__(self, name: str, is_compose: bool) -> None:
            super().__init__()
            self.name = name
            self.is_compose = is_compose

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._compose_services: set[str] = set()

    def _selected_service(self) -> str | None:
        if self.row_count == 0:
            return None
        row = self.get_row_at(self.cursor_row)
        name = row[0].plain if isinstance(row[0], Text) else str(row[0])
        return name if name in self._compose_services else None

    def action_open_browser(self) -> None:
        if self.row_count == 0:
            return
        row = self.get_row_at(self.cursor_row)
        ports_cell = row[3]
        ports_str = (
            ports_cell.plain if isinstance(ports_cell, Text) else str(ports_cell)
        )
        if not ports_str.strip():
            self.app.notify("No ports exposed", severity="warning")
            return
        host_port = ports_str.split(",")[0].split("->")[0].strip()
        webbrowser.open(f"http://localhost:{host_port}")

    def action_start_build(self) -> None:
        if svc := self._selected_service():
            self.post_message(self.RunService(svc, ["--build"]))

    def action_force_rebuild(self) -> None:
        if svc := self._selected_service():
            self.post_message(
                self.RunService(svc, ["--build", "--force-recreate", "--no-deps"])
            )

    def action_start_build_all(self) -> None:
        self.post_message(self.RunAllServices(["--build"]))

    def action_force_rebuild_all(self) -> None:
        self.post_message(self.RunAllServices(["--build", "--force-recreate"]))

    def action_stop(self) -> None:
        if self.row_count == 0:
            return
        row = self.get_row_at(self.cursor_row)
        name = row[0].plain if isinstance(row[0], Text) else str(row[0])
        status = row[2].plain if isinstance(row[2], Text) else str(row[2])
        if status != "running":
            self.app.notify("Container is not running", severity="warning")
            return
        self.post_message(self.StopContainer(name, name in self._compose_services))

    def action_cursor_up(self) -> None:
        self.move_cursor(row=max(0, self.cursor_row - 1))

    def action_cursor_down(self) -> None:
        self.move_cursor(row=min(self.row_count - 1, self.cursor_row + 1))
