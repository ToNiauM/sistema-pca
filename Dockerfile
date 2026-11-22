FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=build \
    DATABASE_URL=sqlite:///tmp/build.db \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    SEI_USUARIO=build \
    SEI_SENHA=build \
    python manage.py collectstatic --noinput

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]

# Fase 32 — alvo do serviço robo (compose.yml), Chromium autenticado
# no SEI. A imagem web (alvo runtime acima) NUNCA ganha Playwright; só este
# alvo, construído à parte (build.target: robo). Herda ENTRYPOINT/EXPOSE do
# runtime por FROM, mas o serviço robo do compose sobrescreve com
# entrypoint: [] + command: sei_atender — este alvo nunca roda migrate nem
# gunicorn (sem migração/sem servidor web no robô).
FROM runtime AS robo
COPY requirements-robo.txt ./
RUN pip install --no-cache-dir -r requirements-robo.txt
RUN playwright install --with-deps chromium
