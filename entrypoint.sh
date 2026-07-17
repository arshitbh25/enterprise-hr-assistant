#!/bin/sh
# Railway release step (SDD Section 3.7: "DB migrations run as a release
# step") - runs on every container start, before the app is reachable,
# so a schema-missing DB never serves a request (app/main.py's lifespan
# already fails fast on this instead of guessing).
set -e

alembic upgrade head

exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
