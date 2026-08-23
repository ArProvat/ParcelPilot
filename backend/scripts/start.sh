#!/bin/sh
set -eu

alembic upgrade head

if [ "${BOOTSTRAP_DATA:-true}" = "true" ] || [ "${BOOTSTRAP_DATA:-true}" = "1" ]; then
  python -m app.ingestion.bootstrap
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
