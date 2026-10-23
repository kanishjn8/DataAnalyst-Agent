FROM python:3.12-slim
WORKDIR /api
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
RUN useradd --create-home api && mkdir -p /data && chown api:api /data
ENV CACHE_DIRECTORY=/tmp/analysis-tables
ENV PYTHONUNBUFFERED=1
USER api
EXPOSE 4000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4000"]
