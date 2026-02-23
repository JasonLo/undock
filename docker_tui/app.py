import logging

import docker
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header

from docker_tui.compose import load_compose_services
from docker_tui.docker_client import (
    DockerClientError,
    fetch_container_rows,
    get_container_logs,
    make_text_row,
    run_compose_up,
    run_stop_container,
)
from docker_tui.widgets import ContainerTable, LogPanel, ResizeHandle

logger = logging.getLogger(__name__)


class UndockTUI(App[None]):
    TITLE: str = "undock"
    BINDINGS: list[Binding] = [
        Binding("l", "toggle_logs", "Toggle Logs"),
        Binding("q", "quit", "Quit"),
    ]
    CSS: str = """
    Horizontal { height: 1fr; }
    ContainerTable { width: 1fr; }
    #log-panel {
        width: 1fr;
        border: solid $surface-darken-2;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ContainerTable(id="main-table", cursor_type="row")
            yield ResizeHandle()
            yield LogPanel(
                id="log-panel",
                highlight=True,
                markup=False,
                wrap=False,
                auto_scroll=False,
            )
        yield Footer()

    def on_mount(self) -> None:
        self._saved_split: tuple[int, int] | None = None
        self._docker = docker.from_env()
        self.query_one(ContainerTable).add_columns("Name", "Image", "Status", "Ports")
        self.refresh_all()
        self.set_interval(1, self.refresh_all)
        self.call_after_refresh(self._set_initial_split)

    def _set_initial_split(self) -> None:
        table = self.query_one(ContainerTable)
        total = self.size.width

        col_keys = list(table.columns.keys())
        col_widths = {
            key: len(col.label.plain if hasattr(col.label, "plain") else str(col.label))
            for key, col in table.columns.items()
        }
        for row_key in table.rows:
            for i, key in enumerate(col_keys):
                cell = table.get_row(row_key)[i]
                col_widths[key] = max(
                    col_widths[key],
                    len(cell.plain if isinstance(cell, Text) else str(cell)),
                )

        table_width = sum(w + 2 for w in col_widths.values()) + 1
        table_width = max(20, min(table_width, total - 21))
        log_width = total - table_width - 1
        table.styles.width = table_width
        self.query_one("#log-panel").styles.width = log_width

    def refresh_all(self) -> None:
        compose_services = load_compose_services()
        try:
            rows = fetch_container_rows(self._docker, compose_services)
        except DockerClientError as e:
            logger.warning("Docker daemon error: %s", e)
            self.notify(str(e), title="Docker error", severity="error")
            return

        compose_names = set(compose_services.keys())
        table = self.query_one(ContainerTable)
        saved_row = table.cursor_row
        table._compose_services = compose_names
        table.clear()

        for row in rows:
            table.add_row(
                *make_text_row((row.name, row.image, row.status, row.ports), row.style)
            )

        if table.row_count > 0:
            restored = min(saved_row, table.row_count - 1)
            table.move_cursor(row=restored, animate=False)

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        table = self.query_one(ContainerTable)
        row = table.get_row(event.row_key)
        cell = row[0]
        name = cell.plain if isinstance(cell, Text) else str(cell)
        self._load_logs(name)

    @work(thread=True, exclusive=True)
    def _load_logs(self, name: str) -> None:
        lines = get_container_logs(name)
        self.call_from_thread(self._render_logs, name, lines)

    def _render_logs(self, name: str, lines: list[Text]) -> None:
        log = self.query_one("#log-panel", LogPanel)
        at_bottom = log.scroll_y >= log.max_scroll_y
        saved_y = log.scroll_y
        log.border_title = f" {name} "
        log.clear()
        for line in lines:
            log.write(line)
        if at_bottom:
            log.scroll_end(animate=False)
        else:
            log.scroll_to(y=min(saved_y, log.max_scroll_y), animate=False)

    @on(ContainerTable.RunService)
    def handle_run_service(self, event: ContainerTable.RunService) -> None:
        self._compose_up(event.service, event.extra_flags)

    @on(ContainerTable.RunAllServices)
    def handle_run_all(self, event: ContainerTable.RunAllServices) -> None:
        self._compose_up_all(event.extra_flags)

    @on(ContainerTable.StopContainer)
    def handle_stop_container(self, event: ContainerTable.StopContainer) -> None:
        self._stop_container(event.name, event.is_compose)

    @work(thread=True)
    def _stop_container(self, name: str, is_compose: bool) -> None:
        self.notify(f"Stopping {name}…", title="docker")
        result = run_stop_container(name, is_compose)
        if result.returncode == 0:
            self.notify(f"{name} stopped", title="docker")
        else:
            self.notify(
                result.stderr or "unknown error",
                title=f"Failed: {name}",
                severity="error",
            )
        self.call_from_thread(self.refresh_all)

    @work(thread=True)
    def _compose_up_all(self, extra_flags: list[str]) -> None:
        self.notify("Starting all compose services…", title="docker compose")
        result = run_compose_up(None, extra_flags)
        if result.returncode == 0:
            self.notify("All services started", title="docker compose")
        else:
            self.notify(
                result.stderr or "unknown error", title="Failed", severity="error"
            )
        self.call_from_thread(self.refresh_all)

    @work(thread=True)
    def _compose_up(self, service: str, extra_flags: list[str]) -> None:
        self.notify(f"Starting {service}…", title="docker compose")
        result = run_compose_up(service, extra_flags)
        if result.returncode == 0:
            self.notify(f"{service} started", title="docker compose")
        else:
            self.notify(
                result.stderr or "unknown error",
                title=f"Failed: {service}",
                severity="error",
            )
        self.call_from_thread(self.refresh_all)

    def action_toggle_logs(self) -> None:
        log = self.query_one("#log-panel", LogPanel)
        handle = self.query_one(ResizeHandle)
        table = self.query_one(ContainerTable)
        if log.display:
            self._saved_split = (table.region.width, log.region.width)
            log.display = False
            handle.display = False
            table.styles.width = "1fr"
        else:
            log.display = True
            handle.display = True
            if self._saved_split:
                table.styles.width = self._saved_split[0]
                log.styles.width = self._saved_split[1]


def main() -> None:
    logging.basicConfig(
        filename="undock.log",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    UndockTUI().run()


if __name__ == "__main__":
    main()
