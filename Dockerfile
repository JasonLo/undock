FROM ghcr.io/astral-sh/uv:python3.14-alpine

# Metadata labels <https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images>
LABEL org.opencontainers.image.source="https://github.com/jasonlo/docker_tui"
LABEL org.opencontainers.image.description="Terminal user interface (TUI) for managing Docker containers"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

# Install non-project dependencies
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# Copy the application
COPY . .
RUN uv sync --no-dev

# Place the venv binaries on the PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD [ "docker_tui" ]
