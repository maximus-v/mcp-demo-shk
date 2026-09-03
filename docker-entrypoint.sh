#!/bin/sh
set -e

python manage.py migrate --noinput

if [ "$DJANGO_SEED_DEMO" = "true" ]; then
    python manage.py loaddata demo_seed
fi

exec gunicorn mcp_demo.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}"
