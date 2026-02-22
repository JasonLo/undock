import os
import subprocess
import webbrowser

import docker
import yaml
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header, RichLog

STYLE_COMPOSE_RUNNING = "green"
STYLE_COMPOSE_STOPPED = "yellow"
STYLE_OTHER_RUNNING = "grey70"
STYLE_OTHER_STOPPED = "grey42"


def _fmt_ports(c) -> str:
    return ", ".join(
        f"{h[0]['HostPort']}->{p}" for p, h in c.ports.items() if h
    ) if c.ports else ""


def _row(values: tuple[str, ...], style: str) -> tuple[Text, ...]:
    return tuple(Text(v, style=style) for v in values)


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
        self._dragging = False

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
        total = parent.region.width
        left_width = event.screen_x - parent.region.x
        left_width = max(10, min(total - 11, left_width))  # min 10 cols each side
        right_width = total - left_width - 1  # 1 for the handle itself
        self.app.query_one(ContainerTable).styles.width = left_width
        self.app.query_one("#log-panel").styles.width = right_width
        event.stop()


class LogPanel(RichLog):
    BINDINGS = [
        Binding("w", "scroll_up", show=False),
        Binding("s", "scroll_down", show=False),
    ]


class ContainerTable(DataTable):
    BINDINGS = [
        Binding("w", "cursor_up", show=False),
        Binding("s", "cursor_down", show=False),
        Binding("enter", "open_browser", "Open in Browser"),
        Binding("e", "start_build", "Start+Build"),
        Binding("f", "force_rebuild", "Force Rebuild"),
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

    def __init__(self, **kwargs) -> None:
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
        ports_str = ports_cell.plain if isinstance(ports_cell, Text) else str(ports_cell)
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
            self.post_message(self.RunService(svc, ["--build", "--force-recreate", "--no-deps"]))

    def action_start_build_all(self) -> None:
        self.post_message(self.RunAllServices(["--build"]))

    def action_force_rebuild_all(self) -> None:
        self.post_message(self.RunAllServices(["--build", "--force-recreate"]))

    def action_cursor_up(self) -> None:
        self.move_cursor(row=max(0, self.cursor_row - 1))

    def action_cursor_down(self) -> None:
        self.move_cursor(row=min(self.row_count - 1, self.cursor_row + 1))


class DockerTUI(App):
    TITLE = "docker-tui"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("l", "toggle_logs", "Toggle Logs"),
    ]
    CSS = """
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
            yield LogPanel(id="log-panel", highlight=True, markup=False, wrap=False, auto_scroll=False)
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

        # Seed widths from column labels
        col_keys = list(table.columns.keys())
        col_widths = {
            key: len(col.label.plain if hasattr(col.label, "plain") else str(col.label))
            for key, col in table.columns.items()
        }
        # Expand to fit actual cell content
        for row_key in table.rows:
            for i, key in enumerate(col_keys):
                cell = table.get_row(row_key)[i]
                col_widths[key] = max(
                    col_widths[key],
                    len(cell.plain if isinstance(cell, Text) else str(cell)),
                )

        # +2 per column for cell padding, +1 for the row cursor indicator
        table_width = sum(w + 2 for w in col_widths.values()) + 1
        table_width = max(20, min(table_width, total - 21))
        log_width = total - table_width - 1  # -1 for the resize handle
        table.styles.width = table_width
        self.query_one("#log-panel").styles.width = log_width

    def _load_compose_services(self) -> dict:
        for name in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
            if os.path.exists(name):
                with open(name) as f:
                    data = yaml.safe_load(f)
                return data.get("services", {}) or {}
        return {}

    def refresh_all(self) -> None:
        try:
            client = self._docker
            compose_services = self._load_compose_services()
            compose_names = set(compose_services.keys())
            all_containers = client.containers.list(all=True)
        except Exception:
            return

        compose_container: dict[str, object | None] = {name: None for name in compose_names}
        for c in all_containers:
            try:
                svc = c.labels.get("com.docker.compose.service")
                if svc in compose_names:
                    compose_container[svc] = c
            except Exception:
                continue

        other_containers = []
        for c in all_containers:
            try:
                if c.labels.get("com.docker.compose.service") not in compose_names:
                    other_containers.append(c)
            except Exception:
                continue

        table = self.query_one(ContainerTable)
        saved_row = table.cursor_row
        table._compose_services = compose_names
        table.clear()

        for svc_name, config in compose_services.items():
            image = (config or {}).get("image", "<build>")
            c = compose_container[svc_name]
            try:
                if c is None:
                    style, status, ports = STYLE_COMPOSE_STOPPED, "not created", ""
                elif c.status == "running":
                    style, status, ports = STYLE_COMPOSE_RUNNING, c.status, _fmt_ports(c)
                else:
                    style, status, ports = STYLE_COMPOSE_STOPPED, c.status, _fmt_ports(c)
            except Exception:
                style, status, ports = STYLE_COMPOSE_STOPPED, "unknown", ""
            table.add_row(*_row((svc_name, image, status, ports), style))

        for c in other_containers:
            try:
                image = c.image.tags[0] if c.image.tags else c.image.short_id
                style = STYLE_OTHER_RUNNING if c.status == "running" else STYLE_OTHER_STOPPED
                table.add_row(*_row((c.name, image, c.status, _fmt_ports(c)), style))
            except Exception:
                continue

        if table.row_count > 0:
            restored = min(saved_row, table.row_count - 1)
            table.move_cursor(row=restored, animate=False)

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        try:
            table = self.query_one(ContainerTable)
            row = table.get_row(event.row_key)
            cell = row[0]
            name = cell.plain if isinstance(cell, Text) else str(cell)
            self._load_logs(name)
        except Exception:
            return

    @work(thread=True, exclusive=True)
    def _load_logs(self, name: str) -> None:
        try:
            client = docker.from_env()
            try:
                container = client.containers.get(name)
            except docker.errors.NotFound:
                matches = client.containers.list(
                    all=True,
                    filters={"label": f"com.docker.compose.service={name}"},
                )
                if not matches:
                    self.call_from_thread(self._render_logs, name, [Text("(container not created)", style="dim")])
                    return
                container = matches[0]

            raw = container.logs(tail=300, timestamps=True)
            lines = raw.decode("utf-8", errors="replace").splitlines()
            content = [Text.from_ansi(l) for l in lines] if lines else [Text("(no logs)", style="dim")]
        except Exception as e:
            content = [Text(f"Error: {e}", style="red")]

        self.call_from_thread(self._render_logs, name, content)

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

    @work(thread=True)
    def _compose_up_all(self, extra_flags: list[str]) -> None:
        cmd = ["docker", "compose", "up", "-d", *extra_flags]
        self.notify("Starting all compose services…", title="docker compose")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.notify("All services started", title="docker compose")
        else:
            self.notify(result.stderr or "unknown error", title="Failed", severity="error")
        self.call_from_thread(self.refresh_all)

    @work(thread=True)
    def _compose_up(self, service: str, extra_flags: list[str]) -> None:
        cmd = ["docker", "compose", "up", "-d", *extra_flags, service]
        self.notify(f"Starting {service}…", title="docker compose")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.notify(f"{service} started", title="docker compose")
        else:
            self.notify(result.stderr or "unknown error", title=f"Failed: {service}", severity="error")
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
    DockerTUI().run()


if __name__ == "__main__":
    main()
