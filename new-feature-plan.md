# Plan: Docker Context Switching

## Context

The app currently uses `docker.from_env()` everywhere, which relies on the system's default Docker daemon. Users working with remote Docker hosts (e.g., `ssh://clo36@bear-dev`) need a way to switch contexts from within the TUI and have the selection persist across sessions via a `.env` file.

## Approach

1. Create `undock/context.py` — context data model, `.env` I/O, `docker context ls` integration
2. Create `undock/widgets/context_modal.py` — `ModalScreen` for picking a context
3. Modify `undock/docker_client.py` — make all Docker calls accept context endpoint
4. Modify `undock/app.py` — load context at startup, add `c` binding, wire endpoint into workers
5. Modify `undock/widgets/__init__.py` — export `ContextModal`

No new dependencies needed. `.env` is parsed with stdlib only.

---

## Critical Files

- `undock/app.py` — main app class (line 57: `docker.from_env()`, line 122: `get_container_logs`, lines 153/167/179: subprocess workers)
- `undock/docker_client.py` — `get_container_logs` (line 142), `run_compose_up` (line 164), `run_stop_container` (line 174)
- `undock/widgets/__init__.py` — add `ContextModal` export

---

## New File: `undock/context.py`

```python
from __future__ import annotations
import json
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)
ENV_FILE = ".env"
ENV_KEY = "DOCKER_CONTEXT"


@dataclass(frozen=True)
class DockerContext:
    name: str
    endpoint: str  # e.g. "ssh://clo36@bear-dev" or "unix:///var/run/docker.sock"
    is_ssh: bool   # drives use_ssh_client=True in DockerClient

    @staticmethod
    def from_dict(d: dict) -> "DockerContext":
        endpoint = d.get("DockerEndpoint", "")
        return DockerContext(name=d["Name"], endpoint=endpoint, is_ssh=endpoint.startswith("ssh://"))


def list_contexts() -> list[DockerContext]:
    """Shell out to `docker context ls --format json` (NDJSON output). Returns [] on failure."""
    try:
        result = subprocess.run(
            ["docker", "context", "ls", "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.warning("docker context ls failed: %s", result.stderr)
            return []
        contexts = []
        for line in result.stdout.strip().splitlines():
            try:
                contexts.append(DockerContext.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Skipping context line %r: %s", line, e)
        return contexts
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Failed to list Docker contexts: %s", e)
        return []


def load_context_from_env() -> str | None:
    """Parse .env in CWD for DOCKER_CONTEXT=<name>. Returns name or None."""
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == ENV_KEY:
                    return value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to read %s: %s", ENV_FILE, e)
    return None


def save_context_to_env(name: str) -> None:
    """Write DOCKER_CONTEXT=<name> into .env, preserving all other lines."""
    existing: list[str] = []
    try:
        with open(ENV_FILE) as f:
            existing = f.readlines()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to read %s before write: %s", ENV_FILE, e)
        return

    new_line = f"{ENV_KEY}={name}\n"
    replaced = False
    result: list[str] = []
    for line in existing:
        if line.strip().startswith(f"{ENV_KEY}="):
            result.append(new_line)
            replaced = True
        else:
            result.append(line)
    if not replaced:
        result.append(new_line)

    try:
        with open(ENV_FILE, "w") as f:
            f.writelines(result)
    except OSError as e:
        logger.warning("Failed to write %s: %s", ENV_FILE, e)


def resolve_active_context(all_contexts: list[DockerContext]) -> DockerContext | None:
    """Priority: .env name → first in list. Returns None if list is empty."""
    saved = load_context_from_env()
    if saved:
        for ctx in all_contexts:
            if ctx.name == saved:
                return ctx
        logger.warning("Saved context %r not in docker context ls; falling back", saved)
    return all_contexts[0] if all_contexts else None
```

---

## New File: `undock/widgets/context_modal.py`

```python
from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option
from undock.context import DockerContext


class ContextModal(ModalScreen[DockerContext | None]):
    DEFAULT_CSS = """
    ContextModal { align: center middle; }
    ContextModal > Vertical {
        width: 70; height: auto; max-height: 22;
        border: solid $accent; background: $surface; padding: 1 2;
    }
    ContextModal Label { width: 100%; text-align: center; margin-bottom: 1; }
    """
    BINDINGS: list[Binding] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, contexts: list[DockerContext], active_name: str | None) -> None:
        super().__init__()
        self._contexts = contexts
        self._active_name = active_name

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Select Docker Context")
            options = [
                Option(
                    f"{'[*] ' if ctx.name == self._active_name else '    '}"
                    f"{ctx.name}  ({ctx.endpoint})",
                    id=ctx.name,
                )
                for ctx in self._contexts
            ]
            yield OptionList(*options, id="context-list")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected_id = event.option.id
        for ctx in self._contexts:
            if ctx.name == selected_id:
                self.dismiss(ctx)
                return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

---

## Changes to `undock/docker_client.py`

**`get_container_logs`** — add `base_url` and `use_ssh_client` params:
```python
def get_container_logs(
    name: str,
    tail: int = 300,
    base_url: str | None = None,
    use_ssh_client: bool = False,
) -> list[Text]:
    try:
        client = (
            docker.DockerClient(base_url=base_url, use_ssh_client=use_ssh_client)
            if base_url
            else docker.from_env()
        )
        # ... rest unchanged
```

**`run_compose_up`** — add `docker_host` param, inject into subprocess env:
```python
import os  # add at top if not present

def run_compose_up(
    service: str | None, extra_flags: list[str], docker_host: str | None = None
) -> subprocess.CompletedProcess[str]:
    if service is not None:
        cmd = ["docker", "compose", "up", "-d", *extra_flags, service]
    else:
        cmd = ["docker", "compose", "up", "-d", *extra_flags]
    env = {**os.environ, "DOCKER_HOST": docker_host} if docker_host else None
    return subprocess.run(cmd, capture_output=True, text=True, env=env)
```

**`run_stop_container`** — same pattern:
```python
def run_stop_container(
    name: str, is_compose: bool, docker_host: str | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = (
        ["docker", "compose", "stop", name] if is_compose else ["docker", "stop", name]
    )
    env = {**os.environ, "DOCKER_HOST": docker_host} if docker_host else None
    return subprocess.run(cmd, capture_output=True, text=True, env=env)
```

---

## Changes to `undock/app.py`

**New imports:**
```python
from undock.context import DockerContext, list_contexts, resolve_active_context, save_context_to_env
from undock.widgets.context_modal import ContextModal
```

**Add binding:**
```python
BINDINGS: list[Binding] = [
    Binding("c", "switch_context", "Context"),
    Binding("l", "toggle_logs", "Toggle Logs"),
    Binding("q", "quit", "Quit"),
]
```

**Update `on_mount`** (replace `docker.from_env()` line):
```python
def on_mount(self) -> None:
    self._saved_split: tuple[int, int] | None = None
    self._all_contexts: list[DockerContext] = list_contexts()
    self._active_context: DockerContext | None = resolve_active_context(self._all_contexts)
    self._docker = self._make_docker_client()
    self._update_subtitle()
    self.query_one(ContainerTable).add_columns("Name", "Image", "Status", "Ports")
    self.refresh_all()
    self.set_interval(1, self.refresh_all)
    self.call_after_refresh(self._set_initial_split)
```

**New helper methods** (add before `action_toggle_logs`):
```python
def _make_docker_client(self) -> docker.DockerClient:
    ctx = self._active_context
    if ctx is None:
        return docker.from_env()
    return docker.DockerClient(base_url=ctx.endpoint, use_ssh_client=ctx.is_ssh)

def _update_subtitle(self) -> None:
    self.sub_title = self._active_context.name if self._active_context else ""

def action_switch_context(self) -> None:
    if not self._all_contexts:
        self.notify("No Docker contexts found", severity="warning")
        return
    active_name = self._active_context.name if self._active_context else None
    self.push_screen(ContextModal(self._all_contexts, active_name), callback=self._on_context_selected)

def _on_context_selected(self, result: DockerContext | None) -> None:
    if result is None or (self._active_context and result.name == self._active_context.name):
        return
    try:
        self._docker.close()
    except Exception:
        pass
    self._active_context = result
    try:
        self._docker = self._make_docker_client()
    except Exception as e:
        self.notify(str(e), title="Context error", severity="error")
        return
    save_context_to_env(result.name)
    self._update_subtitle()
    self.refresh_all()
    self.notify(f"Switched to: {result.name}", title="Docker Context")
```

**Update `_load_logs`** worker to pass endpoint:
```python
@work(thread=True, exclusive=True)
def _load_logs(self, name: str) -> None:
    ctx = self._active_context
    lines = get_container_logs(
        name,
        base_url=ctx.endpoint if ctx else None,
        use_ssh_client=ctx.is_ssh if ctx else False,
    )
    self.call_from_thread(self._render_logs, name, lines)
```

**Update `_stop_container`, `_compose_up`, `_compose_up_all`** — pass `docker_host`:
```python
# In each worker, add at top:
docker_host = self._active_context.endpoint if self._active_context else None
# Then pass to the subprocess call:
result = run_stop_container(name, is_compose, docker_host=docker_host)
result = run_compose_up(service, extra_flags, docker_host=docker_host)
result = run_compose_up(None, extra_flags, docker_host=docker_host)
```

---

## Changes to `undock/widgets/__init__.py`

```python
from undock.widgets.container_table import ContainerTable
from undock.widgets.context_modal import ContextModal
from undock.widgets.log_panel import LogPanel
from undock.widgets.resize_handle import ResizeHandle

__all__ = ["ContainerTable", "ContextModal", "LogPanel", "ResizeHandle"]
```

---

## Data Flow

**Startup:**
```
on_mount()
  → list_contexts()           # docker context ls --format json → NDJSON
  → resolve_active_context()  # read .env DOCKER_CONTEXT, match by name
  → _make_docker_client()     # docker.DockerClient(base_url=endpoint, use_ssh_client=is_ssh)
  → _update_subtitle()        # Header shows active context name
```

**Context switch (`c` key):**
```
action_switch_context()
  → push ContextModal (OptionList of all contexts, active marked [*])
  → user selects → dismiss(DockerContext)
  → _on_context_selected()
      → close old client
      → _make_docker_client()         # new SDK client with new endpoint
      → save_context_to_env(name)     # write .env
      → _update_subtitle()            # update Header
      → refresh_all()                 # reload container list
```

**Subprocess calls (compose up/stop):**
```
DOCKER_HOST=ssh://clo36@bear-dev injected into subprocess env
→ docker CLI uses SSH transport natively
```

---

## `.env` Format

```
DOCKER_CONTEXT=clo36@bear-dev
```

Created/updated automatically on context switch. Parsed on startup. All other keys in the file are preserved.

---

## Verification

1. Run `uv run undock` — subtitle should show the active context name (or be blank if no contexts)
2. Press `c` — modal opens showing all Docker contexts from `docker context ls`
3. Select a remote context (e.g., `bear-dev`) — subtitle updates, container list reloads from remote daemon
4. Quit and re-launch — `.env` file has `DOCKER_CONTEXT=bear-dev`, app reconnects to same context
5. Run `uv run ruff check .` — no lint errors
6. Run `uv run ty check` — no type errors
