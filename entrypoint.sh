#!/usr/bin/env sh
set -e

if [ "$RUN_MIGRATIONS" = "true" ] || [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "Running database migrations..."
    alembic upgrade head
    echo "Migrations applied successfully."
fi

exec "$@"
