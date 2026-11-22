#!/bin/sh
set -eu

python manage.py migrate --noinput

# Tuning de pico para a reunião mensal de acompanhamento (~50 usuários simultâneos):
# o worker sync dava só 3 slots de concorrência e uma requisição lenta (ex.: export
# XLSX) monopolizava 1 deles, formando fila; gthread com 3 workers x 4 threads dá
# 12 slots na mesma RAM (~172MB medidos com 3 workers sync). --workers fica em 3:
# o host tem 2 CPUs — escala-se por threads, não por processos. --max-requests +
# jitter recicla os workers escalonadamente contra vazamento de memória; o jitter
# evita que os 3 reciclem ao mesmo tempo. Defaults via ${VAR:-} preservam o
# invariante de portabilidade: nada obrigatório novo no .env, mas tudo ajustável
# sem rebuild de código — este entrypoint é assado na imagem, então mudar as
# variáveis exige só `docker compose up -d`; mudar os defaults exige rebuild.
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --max-requests 1000 \
    --max-requests-jitter 100
