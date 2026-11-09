# Một Dockerfile, ba image theo container Level 2. Mỗi target chỉ cài package của nó.
#   docker build --target api     -t ingest-api .
#   docker build --target convert -t ingest-convert .
#   docker build --target index   -t ingest-index .

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Chép pyproject trước để lớp cài thư viện được cache khi chỉ đổi code
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY packages/api/pyproject.toml packages/api/
COPY packages/convert/pyproject.toml packages/convert/
COPY packages/index/pyproject.toml packages/index/
COPY packages/cli/pyproject.toml packages/cli/

FROM base AS api
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev --no-install-workspace --package ingest-api
COPY packages/core/src packages/core/src
COPY packages/api/src packages/api/src
RUN uv sync --frozen --no-dev --package ingest-api
EXPOSE 8000
ENTRYPOINT ["uv", "run", "--no-sync", "--package", "ingest-api", "ingest-api"]

FROM base AS convert
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev --no-install-workspace --package ingest-convert
COPY packages/core/src packages/core/src
COPY packages/convert/src packages/convert/src
RUN uv sync --frozen --no-dev --package ingest-convert
ENTRYPOINT ["uv", "run", "--no-sync", "--package", "ingest-convert", "ingest-convert-worker"]

FROM base AS index
RUN uv sync --frozen --no-dev --no-install-workspace --package ingest-index
COPY packages/core/src packages/core/src
COPY packages/index/src packages/index/src
RUN uv sync --frozen --no-dev --package ingest-index
ENTRYPOINT ["uv", "run", "--no-sync", "--package", "ingest-index", "ingest-index-worker"]
