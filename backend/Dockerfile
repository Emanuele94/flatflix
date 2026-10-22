FROM python:3.12.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies come only from the reviewed lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ ./app/

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin flatflix
USER flatflix

EXPOSE 8000

# uvicorn's own proxy handling is off: app.proxy.TrustedProxyHeaders believes X-Forwarded-For
# only from the reverse proxy container, never from other containers on the `qbit` network.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
