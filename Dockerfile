FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY app/ ./app/
COPY config/ ./config/
COPY prompts/ ./prompts/

EXPOSE 8000

CMD ["sh", "-c", "mkdir -p /app/resources/db /app/resources/checkpoint /app/resources/data /app/resources/es && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]