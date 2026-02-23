import logging
import os

import yaml

logger = logging.getLogger(__name__)

COMPOSE_FILE_NAMES: tuple[str, ...] = (
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
)


def find_compose_file() -> str | None:
    for name in COMPOSE_FILE_NAMES:
        if os.path.exists(name):
            return name
    return None


def load_compose_services() -> dict[str, dict[str, object]]:
    """Returns {} on missing file or parse error (logged at WARNING)."""
    path = find_compose_file()
    if path is None:
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to load compose file %r: %s", path, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("Compose file %r has unexpected structure", path)
        return {}
    services = data.get("services", {}) or {}
    if not isinstance(services, dict):
        return {}
    return services
