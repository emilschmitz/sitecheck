FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Copy workspace context
COPY pyproject.toml uv.lock ./
COPY a2a_agent/pyproject.toml /app/a2a_agent/pyproject.toml
COPY a2a_agent/a2a_agent/ /app/a2a_agent/a2a_agent/

# Sync package
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package a2a-sitecheck

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/a2a_agent"
EXPOSE 8000
# Update command to new path
CMD ["python", "-m", "a2a_agent.server"]
