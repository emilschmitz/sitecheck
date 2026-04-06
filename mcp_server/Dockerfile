FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY mcp_server/pyproject.toml ./
# Create dummy folder for uv to see the package during first sync
RUN mkdir mcp_server && touch mcp_server/__init__.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

COPY mcp_server /app/mcp_server/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
EXPOSE 8001
CMD ["fastmcp", "run", "mcp_server/server.py", "--transport", "sse", "--port", "8001"]
