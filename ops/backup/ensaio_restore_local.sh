#!/bin/sh
# Ensaio local de restauração — (Gate 1),
# adaptado para SQLite na Fase 31.
#
# Prova, contra o R2 real e recursos Docker efêmeros, que o volume externo
# pca_data sobrevive a `docker compose down -v` (Gate 1) e que o
# `.sqlite3.gz` mais recente restaura corretamente (Gates 2-3): mesma
# contagem de processos da produção, zero exercício nulo, migration aplicada
# sem pendência.
#
# NUNCA toca produção: nenhum comando aqui referencia o volume pca_data, o
# projeto Compose "pca-cfc" deste diretório, ou os containers
# pca-cfc-web-1/pca-cfc-backup-1 além de `docker compose exec` (leitura)
# contra web/backup, que já rodam. Toda infraestrutura criada usa o prefixo
# pca_rehearsal_ e é destruída ao final da Parte 2. Nenhum `docker compose
# down` aparece neste arquivo sem `-p pca_rehearsal_*` na mesma linha.
#
# Reexecutável: rode o arquivo inteiro para repetir o ensaio do zero. As duas
# partes abaixo (do plano) podem também ser copiadas e
# rodadas em shells separados no mesmo host, na mesma ordem, reaproveitando
# os recursos pca_rehearsal_* que a Parte 1 deixa de pé.
set -eu

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

IMAGEM_WEB="${WEB_IMAGE:-toniaum/pca-cfc:dev}"
REDE="pca_rehearsal_net"
VOLUME_DATA="pca_rehearsal_data"
VOLUME_TESTE_GATE1="pca_rehearsal_volume_test"
PROJETO_GATE1="pca_rehearsal_vol_test"

# ---------------------------------------------------------------------------
# PARTE 1 — volume isolado (Gate 1) + restore + migration + contagens
# ---------------------------------------------------------------------------

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
    image: alpine
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

echo "=== [3/7] Identifica o .sqlite3.gz mais recente em r2:\${R2_BUCKET}/daily/ (via serviço backup) ==="
DUMP_FILE=$(docker compose exec -T backup sh -c 'rclone lsf "r2:${R2_BUCKET}/daily/" --format tp --separator ";"' \
  | sort -t';' -k1 -r | head -1 | cut -d';' -f2 | tr -d '\r')
echo "Backup mais recente: ${DUMP_FILE}"

echo "=== [4/7] Volume efêmero pca_rehearsal_data (nunca colide com pca-cfc-web-1/pca_data) ==="
docker volume create "${VOLUME_DATA}"
docker network create "${REDE}"

echo "=== [5/7] Baixa e restaura o .sqlite3.gz no volume efêmero (container busybox de uso único) ==="
docker compose exec -T backup sh -c "rclone cat \"r2:\${R2_BUCKET}/daily/${DUMP_FILE}\"" > /tmp/pca_rehearsal_restore.sqlite3.gz
docker run --rm \
  -v "${VOLUME_DATA}:/data" \
  -v /tmp/pca_rehearsal_restore.sqlite3.gz:/tmp/restore.sqlite3.gz:ro \
  busybox sh -c "gunzip -c /tmp/restore.sqlite3.gz > /data/db.sqlite3"
rm -f /tmp/pca_rehearsal_restore.sqlite3.gz

REHEARSAL_SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL_EFEMERA="sqlite:////data/db.sqlite3"

echo "=== [6/7] migrate --plan e migrate --noinput (imagem pinada, entrypoint bypassado) ==="
docker run --rm --network "${REDE}" \
  -v "${VOLUME_DATA}:/data" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py migrate --plan

docker run --rm --network "${REDE}" \
  -v "${VOLUME_DATA}:/data" \
  -e DATABASE_URL="${DATABASE_URL_EFEMERA}" \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY="${REHEARSAL_SECRET_KEY}" \
  -e ALLOWED_HOSTS=testserver,127.0.0.1 \
  -e DEBUG=false \
  --entrypoint python "${IMAGEM_WEB}" manage.py migrate --noinput

echo "=== [7/7] Contagens pós-restore no ambiente efêmero ==="
docker run --rm --network "${REDE}" \
  -v "${VOLUME_DATA}:/data" \
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

echo "=== Parte 1 concluída. pca_rehearsal_data/pca_rehearsal_net seguem de pé para a Parte 2. ==="

# ---------------------------------------------------------------------------
# PARTE 2 — autenticação, edição, auditoria e encerramento do ensaio
# ---------------------------------------------------------------------------
#
# Reaproveita o mesmo pca_rehearsal_data/pca_rehearsal_net ainda de pé da
# Parte 1 (mesmas REHEARSAL_SECRET_KEY/DATABASE_URL_EFEMERA definidas acima).
# force_login() é um proxy documentado de autenticação — não
# substitui o teste de aceite humano com senha real do runbook
# (ops/MIGRACAO.md seção 7).

echo "=== [· 1/2] Smoke test: login, GET raiz, edição inline, auditoria ==="
docker run --rm --network "${REDE}" \
  -v "${VOLUME_DATA}:/data" \
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
from apps.pca.models import Processo, Acompanhamento

User = get_user_model()
usuario = User.objects.filter(is_superuser=True).order_by('pk').first()
print('SMOKE usuario_login', usuario.pk, usuario.email)

client = Client(SERVER_NAME='testserver')
client.force_login(usuario)

resp = client.get(reverse('raiz'))
print('SMOKE GET raiz status', resp.status_code)

processo = Processo.objects.select_related('exercicio').order_by('item_pca').first()
print('SMOKE processo escolhido', processo.exercicio.ano, processo.item_pca)

# pca:editar_campo foi removida na Fase 26 — pca:acompanhamento_modal é a rota
# atual de edição real: sempre grava Processo com _history_user
# setado, gerando uma linha nova em HistoricalProcesso mesmo só com
# 'observacao', sem tocar situacao/estado (mesmo caminho provado no
# smoke test do plano).
historico_antes = processo.history.count()
acompanhamentos_antes = Acompanhamento.objects.filter(processo=processo).count()
url = reverse('pca:acompanhamento_modal', args=[processo.exercicio.ano, processo.item_pca])
resp2 = client.post(url, {'observacao': 'Ensaio de restore local — smoke test'})
print('SMOKE POST acompanhamento_modal status', resp2.status_code)

processo.refresh_from_db()
historico_depois = processo.history.count()
acompanhamentos_depois = Acompanhamento.objects.filter(processo=processo).count()
ultimo = processo.history.first()
print('SMOKE historico_antes', historico_antes, 'historico_depois', historico_depois)
print('SMOKE acompanhamentos_antes', acompanhamentos_antes, 'acompanhamentos_depois', acompanhamentos_depois)
print('SMOKE history_user_id_ultimo', ultimo.history_user_id, 'esperado', usuario.pk)
"

echo "=== [· 2/2] Encerramento — destruindo TODOS os recursos pca_rehearsal_* ==="
docker network rm "${REDE}"
docker volume rm "${VOLUME_DATA}" "${VOLUME_TESTE_GATE1}"
echo "Verificação pós-limpeza:"
docker volume ls --format '{{.Name}}' | grep pca_rehearsal || echo "(nenhum volume pca_rehearsal_* remanescente)"
echo "Produção (deve continuar Up, sem reinício):"
docker compose ps

echo "=== Ensaio completo. Todos os recursos pca_rehearsal_* foram destruídos. ==="
