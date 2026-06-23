FROM python:3.13-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY main.py ./
COPY app/ ./app/
COPY config/ ./config/
COPY prompts/ ./prompts/

EXPOSE 8000

CMD ["sh", "-c", "mkdir -p /app/resources/db /app/resources/checkpoint /app/resources/chroma /app/resources/data && exec uv run --no-sync uvicorn main:app --host 0.0.0.0 --port 8000"]