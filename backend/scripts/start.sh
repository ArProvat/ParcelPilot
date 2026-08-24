#!/bin/sh
set -eu

alembic upgrade head

if [ "${BOOTSTRAP_DATA:-false}" = "true" ] || [ "${BOOTSTRAP_DATA:-false}" = "1" ]; then
  python -m app.ingestion.bootstrap
fi

PORT="${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

