#!/bin/sh
set -eu

python manage.py migrate --noinput

# gthread com workers x threads dá mais concorrência sem monopolizar workers em requisições lentas
# ajustável via env, sem rebuild
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --max-requests 1000 \
    --max-requests-jitter 100
