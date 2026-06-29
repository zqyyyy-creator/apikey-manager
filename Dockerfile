# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.9.18-python3.13-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

COPY --from=builder /app /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
