FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY app/ ./app/
COPY config/ ./config/
COPY prompts/ ./prompts/

EXPOSE 8000

CMD ["sh", "-c", "mkdir -p /app/resources/db /app/resources/checkpoint /app/resources/data /app/resources/es && exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]