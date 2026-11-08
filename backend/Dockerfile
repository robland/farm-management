# Production image of the API (ARCHITECTURE.md §13). Build from the repository root:
#   docker build -f backend/Dockerfile -t fms-api backend
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DJANGO_SETTINGS_MODULE=config.settings.prod

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app
# Dependencies first (cached layer), from the locked versions only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra ai --no-install-project

COPY . .
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://build@localhost/build \
    /app/.venv/bin/python manage.py collectstatic --noinput

RUN useradd --system --uid 1000 fms && mkdir -p /data/files && chown -R fms /data /app
USER fms
ENV FMS_FILE_STORAGE_ROOT=/data/files PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--timeout", "120", "--access-logfile", "-"]
