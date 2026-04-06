FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY a2a_agent/pyproject.toml ./
# Create dummy folder for uv to see the package during first sync
RUN mkdir a2a_agent && touch a2a_agent/__init__.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

COPY a2a_agent /app/a2a_agent/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
EXPOSE 8000
CMD ["python", "-m", "a2a_agent.server"]
