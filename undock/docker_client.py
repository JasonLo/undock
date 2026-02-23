import logging
import subprocess
from dataclasses import dataclass

import docker
import docker.errors
import docker.models.containers
from rich.text import Text

from docker_tui.config import (
    STYLE_COMPOSE_RUNNING,
    STYLE_COMPOSE_STOPPED,
    STYLE_OTHER_RUNNING,
    STYLE_OTHER_STOPPED,
)

logger = logging.getLogger(__name__)


class DockerClientError(Exception):
    pass


@dataclass
class ContainerRow:
    name: str
    image: str
    status: str
    ports: str
    style: str
    is_compose: bool


def fmt_ports(container: docker.models.containers.Container) -> str:
    return (
        ", ".join(f"{h[0]['HostPort']}->{p}" for p, h in container.ports.items() if h)
        if container.ports
        else ""
    )


def make_text_row(
    values: tuple[str, str, str, str], style: str
) -> tuple[Text, Text, Text, Text]:
    a, b, c, d = values
    return (
        Text(a, style=style),
        Text(b, style=style),
        Text(c, style=style),
        Text(d, style=style),
    )


def fetch_container_rows(
    client: docker.DockerClient,
    compose_services: dict[str, dict[str, object]],
) -> list[ContainerRow]:
    """Raises DockerClientError on daemon failure. Skips malformed containers (DEBUG log)."""
    try:
        all_containers: list[docker.models.containers.Container] = (
            client.containers.list(all=True)
        )
    except docker.errors.DockerException as e:
        raise DockerClientError(str(e)) from e

    compose_names = set(compose_services.keys())

    # Map compose service name → container (or None if not created)
    compose_container: dict[str, docker.models.containers.Container | None] = {
        name: None for name in compose_names
    }
    for c in all_containers:
        try:
            svc = c.labels.get("com.docker.compose.service")
            if svc in compose_names:
                compose_container[svc] = c
        except (AttributeError, KeyError) as e:
            logger.debug("Skipping container in compose pass: %s", e)
            continue

    other_containers: list[docker.models.containers.Container] = []
    for c in all_containers:
        try:
            if c.labels.get("com.docker.compose.service") not in compose_names:
                other_containers.append(c)
        except (AttributeError, KeyError) as e:
            logger.debug("Skipping container in other pass: %s", e)
            continue

    rows: list[ContainerRow] = []

    for svc_name, config in compose_services.items():
        image = (config or {}).get("image", "<build>")
        c = compose_container[svc_name]
        try:
            if c is None:
                style, status, ports = STYLE_COMPOSE_STOPPED, "not created", ""
            elif c.status == "running":
                style, status, ports = STYLE_COMPOSE_RUNNING, c.status, fmt_ports(c)
            else:
                style, status, ports = STYLE_COMPOSE_STOPPED, c.status, fmt_ports(c)
        except (AttributeError, KeyError) as e:
            logger.debug("Error reading compose container %r: %s", svc_name, e)
            style, status, ports = STYLE_COMPOSE_STOPPED, "unknown", ""
        rows.append(
            ContainerRow(
                name=svc_name,
                image=str(image) if image is not None else "<build>",
                status=status,
                ports=ports,
                style=style,
                is_compose=True,
            )
        )

    for c in other_containers:
        try:
            image = c.image.tags[0] if c.image.tags else c.image.short_id
            style = (
                STYLE_OTHER_RUNNING if c.status == "running" else STYLE_OTHER_STOPPED
            )
            rows.append(
                ContainerRow(
                    name=c.name,
                    image=image,
                    status=c.status,
                    ports=fmt_ports(c),
                    style=style,
                    is_compose=False,
                )
            )
        except (AttributeError, KeyError) as e:
            logger.debug("Skipping other container: %s", e)
            continue

    return rows


def get_container_logs(name: str, tail: int = 300) -> list[Text]:
    """Creates its own docker client (thread safety). Returns dim message if not found."""
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
                return [Text("(container not created)", style="dim")]
            container = matches[0]

        raw = container.logs(tail=tail, timestamps=True)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if lines:
            return [Text.from_ansi(line) for line in lines]
        return [Text("(no logs)", style="dim")]
    except Exception as e:
        logger.warning("Failed to load logs for %r: %s", name, e)
        return [Text(f"Error: {e}", style="red")]


def run_compose_up(
    service: str | None, extra_flags: list[str]
) -> subprocess.CompletedProcess[str]:
    if service is not None:
        cmd = ["docker", "compose", "up", "-d", *extra_flags, service]
    else:
        cmd = ["docker", "compose", "up", "-d", *extra_flags]
    return subprocess.run(cmd, capture_output=True, text=True)


def run_stop_container(name: str, is_compose: bool) -> subprocess.CompletedProcess[str]:
    cmd = (
        ["docker", "compose", "stop", name] if is_compose else ["docker", "stop", name]
    )
    return subprocess.run(cmd, capture_output=True, text=True)
