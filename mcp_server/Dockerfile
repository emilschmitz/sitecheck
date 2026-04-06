FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Copy workspace context
COPY pyproject.toml uv.lock ./
COPY mcp_server/pyproject.toml /app/mcp_server/pyproject.toml
COPY mcp_server/mcp_server/ /app/mcp_server/mcp_server/

# Sync package
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package mcp-sitecheck

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/mcp_server"
EXPOSE 8001
# Update command to use internal package
CMD ["fastmcp", "run", "mcp_server/mcp_server/server.py", "--transport", "sse", "--port", "8001"]
