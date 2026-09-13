#!/bin/sh
# ensaio local de restauração: prova que o volume externo sobrevive a down -v
# e que o dump mais recente restaura corretamente, sem tocar produção
# reexecutável: roda tudo com recursos pca_rehearsal_*, destruídos ao final
set -eu

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

# imagem construída por `docker compose build web` (sobrescreva via IMAGEM_WEB=...)
IMAGEM_WEB="${IMAGEM_WEB:-sistema-pca-web:latest}"
REDE="pca_rehearsal_net"
VOLUME_PGDATA="pca_rehearsal_pgdata"
DB_CONTAINER="pca_rehearsal_db"
VOLUME_TESTE_GATE1="pca_rehearsal_volume_test"
PROJETO_GATE1="pca_rehearsal_vol_test"

# --- Parte 1: volume isolado + restore + migration + contagens ---

echo "=== [1/7] Linha de base viva de produção (só leitura, via web já em execução) ==="
docker compose exec -T web python manage.py shell -c "
from apps.pca.models import Processo, Acompanhamento, HistoricalProcesso, Reuniao
print('BASELINE Processo', Processo.objects.count())
print('BASELINE Acompanhamento', Acompanhamento.objects.count())
print('BASELINE Reuniao', Reuniao.objects.count())
print('BASELINE HistoricalProcesso', HistoricalProcesso.objects.count())
print('BASELINE Exercicios', sorted(set(Processo.objects.values_list('exercicio__ano', flat=True))))
"

echo "=== [2/7] Gate 1 — volume externo sobrevive a 'down -v' num projeto Compose isolado ==="
TMP_COMPOSE_DIR=$(mktemp -d)
cat > "${TMP_COMPOSE_DIR}/docker-compose.yml" <<EOF
services:
  probe:
    image: postgres:17
    command: ["true"]
    volumes:
      - ${VOLUME_TESTE_GATE1}:/data
volumes:
  ${VOLUME_TESTE_GATE1}:
    external: true
EOF
docker volume create "${VOLUME_TESTE_GATE1}"
docker compose -p "${PROJETO_GATE1}" -f "${TMP_COMPOSE_DIR}/docker-compose.yml" up --no-start
docker compose -p "${PROJETO_GATE1}" -f "${TMP_COMPOSE_DIR}/docker-compose.yml" down -v
docker volume inspect "${VOLUME_TESTE_GATE1}"
rm -rf "${TMP_COMPOSE_DIR}"
echo "Gate 1 provado: pca_rehearsal_volume_test sobreviveu ao down -v do projeto isolado."

echo "=== [3/7] Identifica o dump mais recente em r2:\${R2_BUCKET}/daily/ (via serviço backup) ==="
DUMP_FILE=$(docker compose exec -T backup sh -c 'rclone lsf "r2:${R2_BUCKET}/daily/" --format tp --separator ";"' \
  | sort -t';' -k1 -r | head -1 | cut -d';' -f2 | tr -d '\r')
echo "Dump mais recente: ${DUMP_FILE}"

echo "=== [4/7] Infra efêmera pca_rehearsal_* (nunca colide com pca-db-1/pca_pgdata) ==="
docker volume create "${VOLUME_PGDATA}"
docker network create "${REDE}"
REHEARSAL_PGPASSWORD=$(openssl rand -hex 16)
docker run -d --name "${DB_CONTAINER}" \
  --network "${REDE}" \
  -v "${VOLUME_PGDATA}:/var/lib/postgresql/data" \
  -e POSTGRES_DB=pca -e POSTGRES_USER=pca -e POSTGRES_PASSWORD="${REHEARSAL_PGPASSWORD}" \
  -e POSTGRES_INITDB_ARGS="--locale-provider=icu --icu-locale=pt-BR --encoding=UTF8" \
  postgres:17
echo "Aguardando pca_rehearsal_db ficar saudável..."
until docker exec "${DB_CONTAINER}" pg_isready -U pca -d pca >/dev/null 2>&1; do
  sleep 2
done
docker exec "${DB_CONTAINER}" pg_isready -U pca -d pca

echo "=== [5/7] Restaura o dump via pipe (rclone cat -> pg_restore stdin, nada gravado em disco do host) ==="
docker compose exec -T backup sh -c "rclone cat \"r2:\${R2_BUCKET}/daily/${DUMP_FILE}\"" | \
  docker exec -i "${DB_CONTAINER}" pg_restore --clean --if-exists --no-owner --username=pca --dbname=pca

REHEARSAL_SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL_EFEMERA="postgres://pca:${REHEARSAL_PGPASSWORD}@${DB_CONTAINER}:5432/pca"

echo "=== [6/7] migrate --plan e migrate --noinput (imagem pinada, entrypoint bypassado) ==="
docker run --rm --network "${REDE}" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py migrate --plan

docker run --rm --network "${REDE}" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py migrate --noinput

echo "=== [7/7] Contagens pós-restore no ambiente efêmero ==="
docker run --rm --network "${REDE}" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py shell -c "
from apps.pca.models import Processo, Acompanhamento, HistoricalProcesso, Reuniao
print('RESTORED Processo', Processo.objects.count())
print('RESTORED Acompanhamento', Acompanhamento.objects.count())
print('RESTORED Reuniao', Reuniao.objects.count())
print('RESTORED HistoricalProcesso', HistoricalProcesso.objects.count())
print('RESTORED Exercicios', sorted(set(Processo.objects.values_list('exercicio__ano', flat=True))))
print('RESTORED Processo NULL exercicio', Processo.objects.filter(exercicio__isnull=True).count())
print('RESTORED HistoricalProcesso NULL exercicio', HistoricalProcesso.objects.filter(exercicio__isnull=True).count())
"

echo "=== Parte 1 (Task 1) concluída. pca_rehearsal_db/pca_rehearsal_net/pca_rehearsal_pgdata seguem de pé para a Parte 2. ==="

# --- Parte 2: autenticação, edição, auditoria e encerramento do ensaio ---
# reaproveita o mesmo pca_rehearsal_db/pca_rehearsal_net de pé da Parte 1

echo "=== [Task 2 · 1/2] Smoke test: login, GET raiz, edição inline, auditoria ==="
docker run --rm --network "${REDE}" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  -e SECURE_SSL_REDIRECT=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py shell -c "
from django.test import Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.pca.models import Processo
from apps.catalogo.models import GrauPrioridade

User = get_user_model()
usuario = User.objects.filter(is_superuser=True).order_by('pk').first()
print('SMOKE usuario_login', usuario.pk, usuario.email)

client = Client(SERVER_NAME='testserver')
client.force_login(usuario)

resp = client.get(reverse('raiz'))
print('SMOKE GET raiz status', resp.status_code)

processo = Processo.objects.select_related('exercicio').filter(grau_prioridade__isnull=False).order_by('item_pca').first()
print('SMOKE processo escolhido', processo.exercicio.ano, processo.item_pca, 'grau_prioridade atual', processo.grau_prioridade_id)

novo_grau = GrauPrioridade.objects.exclude(pk=processo.grau_prioridade_id).order_by('pk').first()
print('SMOKE novo_grau', novo_grau.pk, novo_grau.nome)

historico_antes = processo.history.count()
url = reverse('pca:editar_campo', args=[processo.exercicio.ano, processo.item_pca, 'grau_prioridade'])
resp2 = client.post(url, {'valor': str(novo_grau.pk), 'versao': processo.atualizado_em.isoformat()})
print('SMOKE POST editar_campo status', resp2.status_code)

processo.refresh_from_db()
historico_depois = processo.history.count()
ultimo = processo.history.first()
print('SMOKE historico_antes', historico_antes, 'historico_depois', historico_depois)
print('SMOKE history_user_id_ultimo', ultimo.history_user_id, 'esperado', usuario.pk)
print('SMOKE grau_prioridade_novo_no_banco', processo.grau_prioridade_id, 'esperado', novo_grau.pk)
"

echo "=== [Task 2 · 2/2] Encerramento — destruindo TODOS os recursos pca_rehearsal_* ==="
docker rm -f "${DB_CONTAINER}"
docker network rm "${REDE}"
docker volume rm "${VOLUME_PGDATA}" "${VOLUME_TESTE_GATE1}"
echo "Verificação pós-limpeza:"
docker ps -a --filter name="${DB_CONTAINER}" --format '{{.Names}}'
docker volume ls --format '{{.Name}}' | grep pca_rehearsal || echo "(nenhum volume pca_rehearsal_* remanescente)"
echo "Produção (deve continuar Up, sem reinício):"
docker compose ps

echo "=== Ensaio completo (Task 1 + Task 2). Todos os recursos pca_rehearsal_* foram destruídos. ==="
