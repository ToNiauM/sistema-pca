# Migração para uma VM limpa

Este runbook restaura uma cópia funcional do Sistema de Acompanhamento do Plano de
Contratações Anual em uma VM que nunca executou este projeto. Execute os sete passos na ordem indicada; os comandos pressupõem um
usuário com `sudo`. O runbook é **agnóstico de distro**: o Passo 1 detecta a
família da VM e oferece três caminhos de instalação (A: Debian/Ubuntu via apt;
B: família RHEL — Rocky, AlmaLinux, CentOS Stream, RHEL — via dnf; C: fallback
para qualquer outra distro via script oficial do Docker). A topologia final é
Internet → Cloudflare → Nginx do host → Gunicorn no loopback, como descrito em
[`ops/nginx/pca.conf`](./nginx/pca.conf).

## 1. Preparar a VM e instalar Docker

Crie uma VM limpa, aponte o DNS do novo domínio para ela e conecte por SSH.
Detecte a família da distribuição pela própria VM e siga **um** dos três
caminhos abaixo (registre no arquivo de evidência qual caminho foi usado):

```sh
. /etc/os-release
FAMILY=""
case "$ID" in
  ubuntu|debian) FAMILY=apt ;;
  rocky|almalinux|centos|rhel|ol) FAMILY=dnf ;;
  *) case " ${ID_LIKE:-} " in
       *debian*|*ubuntu*) FAMILY=apt ;;
       *rhel*|*fedora*|*centos*) FAMILY=dnf ;;
     esac ;;
esac
printf 'Familia detectada: %s\n' "${FAMILY:-desconhecida (use o Caminho C)}"
```

### Caminho A — família Debian (`FAMILY=apt`)

Instala pelo repositório oficial assinado do Docker para a distribuição:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
DOCKER_DIST="$ID"
sudo curl -fsSL "https://download.docker.com/linux/${DOCKER_DIST}/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
  "$(dpkg --print-architecture)" "$DOCKER_DIST" "$VERSION_CODENAME" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nginx certbot python3-certbot-nginx rclone
sudo systemctl enable --now docker nginx
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

### Caminho B — família RHEL (`FAMILY=dnf`: Rocky, AlmaLinux, CentOS Stream, RHEL)

Instala pelo repositório oficial assinado do Docker (Rocky/Alma/CentOS usam o
repo `centos`; RHEL e Oracle Linux usam o repo `rhel`). `certbot` e `rclone`
vêm do EPEL:

```sh
sudo dnf -y install dnf-plugins-core
case "$ID" in
  rhel|ol) DOCKER_REPO="https://download.docker.com/linux/rhel/docker-ce.repo" ;;
  *)       DOCKER_REPO="https://download.docker.com/linux/centos/docker-ce.repo" ;;
esac
sudo dnf config-manager --add-repo "$DOCKER_REPO"
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo dnf -y install epel-release || \
  sudo dnf -y install "https://dl.fedoraproject.org/pub/epel/epel-release-latest-$(rpm -E %rhel).noarch.rpm"
sudo dnf -y install nginx certbot python3-certbot-nginx rclone
sudo systemctl enable --now docker nginx
# firewalld vem ativo por padrão na família RHEL: libere HTTP/HTTPS antes do Passo 6
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
# SELinux enforcing (padrão): o Nginx precisa de permissão para falar com o
# Gunicorn no loopback, senão o proxy do Passo 6 falha com 502 mesmo com nginx -t OK
sudo setsebool -P httpd_can_network_connect 1
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

### Caminho C — qualquer outra distro (fallback agnóstico)

Usa o script de instalação oficial do Docker (que configura o repositório
assinado correto para a distro detectada); `nginx`, `certbot` (com o plugin
nginx) e `rclone` vêm do gerenciador de pacotes da própria distro:

```sh
curl -fsSL https://get.docker.com | sudo sh
# instale nginx, certbot + plugin nginx e rclone pelo gerenciador da sua distro
sudo systemctl enable --now docker nginx
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

Se a distro tiver firewall ativo por padrão (firewalld, ufw, nftables), libere
HTTP/HTTPS; se tiver SELinux/AppArmor em modo enforcing, garanta que o Nginx
pode conectar ao loopback (equivalente ao `setsebool` do Caminho B).

`newgrp docker` abre uma subshell com o grupo atualizado; continue nela. Se a sessão
SSH for encerrada, conecte novamente antes de continuar. Não exponha a porta do
container: `WEB_BIND_ADDRESS` deve continuar em `127.0.0.1`, pois somente o Nginx
do host deve alcançá-la.

## 2. Obter o repositório e configurar `.env`

Clone o repositório que contém este runbook, entre nele e parta do arquivo de
variáveis versionado:

```sh
git clone https://github.com/ToNiauM/sistema-pca.git sistema-pca
cd sistema-pca
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
```

Edite `.env` e use a saída do último comando como um `SECRET_KEY` **novo**. Nunca
reutilize o segredo de produção. Preencha também um `POSTGRES_PASSWORD`
novo e faça `DATABASE_URL` usar exatamente o mesmo usuário, senha, banco e host
`db` definidos por `POSTGRES_USER` e `POSTGRES_DB`; o formato existente é
`postgres://pca:<senha-nova>@db:5432/pca`. Para o novo domínio, defina
`DJANGO_SETTINGS_MODULE=config.settings.prod`, `DEBUG=false`,
`ALLOWED_HOSTS=<novo-dominio>` e
`CSRF_TRUSTED_ORIGINS=https://<novo-dominio>`. Mantenha
`WEB_BIND_ADDRESS=127.0.0.1`, escolha `WEB_PORT` (por exemplo, `8000`) e deixe
`PGDATA_VOLUME=pca_pgdata`, salvo se houver uma razão explícita para usar outro
nome.

As quatro variáveis de backup `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`R2_ENDPOINT` e `R2_BUCKET` são opcionais somente para não iniciar o serviço
`backup`. Elas ainda são necessárias no Passo 4 se o dump for copiado diretamente
do Cloudflare R2 por `rclone`; use credenciais com acesso somente de leitura ao
bucket de origem. Todos os nomes acima existem em [`.env.example`](../.env.example).

## 3. Criar o volume externo antes de qualquer Compose

Carregue o nome configurado e crie o volume **antes de iniciar qualquer serviço do
Compose**:

```sh
set -a
. ./.env
set +a
docker volume create "$PGDATA_VOLUME"
docker volume inspect "$PGDATA_VOLUME"
```

Com o valor padrão, o comando efetivo é `docker volume create pca_pgdata`. Este
passo não é opcional: foi exatamente a ausência de um volume externo que custou a
base de produção em 29/07 e 30/07/2026. Em [`compose.yml`](../compose.yml), `pgdata`
é externo e recebe o nome `${PGDATA_VOLUME:-pca_pgdata}`, portanto o Compose não o
cria implicitamente; o volume externo também não é apagado por `docker compose down -v`.

## 4. Subir o banco e restaurar o dump customizado

Suba somente o banco, aguarde o healthcheck e confirme o status antes de restaurar:

```sh
docker compose up -d db
until [ "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q db)")" = "healthy" ]; do
  docker compose ps db
  sleep 5
done
docker compose ps db
```

O script [`ops/backup/backup.sh`](./backup/backup.sh) gera arquivos com
`pg_dump --format=custom`, enviados para `r2:${R2_BUCKET}/daily/` (e, aos domingos,
para `weekly/`). Configure o mesmo remoto `r2` usado pelo serviço de backup, copie
o arquivo mais recente ou um ponto semanal mais antigo e restaure-o com `pg_restore`
(nunca com `psql < arquivo.sql`):

```sh
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
DUMP_FILE=<arquivo>.dump
rclone copy "r2:${R2_BUCKET}/daily/${DUMP_FILE}" .
# Para um ponto semanal, troque somente daily por weekly no comando anterior.
docker compose exec -T db pg_restore --clean --if-exists --no-owner \
  --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" - < "$DUMP_FILE"
```

O `POSTGRES_INITDB_ARGS` de [`compose.yml`](../compose.yml) já inicializa um volume
novo com ICU `pt-BR` e UTF-8. Não execute uma etapa separada para corrigir collation:
ela só seria necessária se o volume do Passo 3 não fosse realmente novo.

## 5. Subir a aplicação e verificar o healthcheck

Suba os serviços restantes, aguardando até os 120 segundos de `start_period` do
healthcheck do serviço `web`:

```sh
docker compose up -d
until [ "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q web)")" = "healthy" ]; do
  docker compose ps web
  sleep 5
done
docker compose ps
curl -fsS "http://127.0.0.1:${WEB_PORT}/healthz"
```

O último comando deve retornar `{"status": "ok"}`. O
[`entrypoint.sh`](../entrypoint.sh) executa `python manage.py migrate --noinput`
antes de iniciar o Gunicorn, então não rode `migrate` manualmente. Os estáticos da
PWA, incluindo ícones do manifest e `offline.html`, já são coletados durante o build
do `Dockerfile`; não há uma etapa separada de `collectstatic`.

## Migrações estruturais anuais

Reaplicações anuais de migração estrutural (ex.: virada de exercício com mudança de schema) merecem seu próprio ensaio de pré-produção, sobre uma cópia restaurada e isolada do banco, com registro de aprovação (`APPROVED`/`BLOCKED`) antes de qualquer `migrate` em produção — adapte o roteiro de gates (checkout/volume, dry-run, apply, smoke test funcional, decisão e rollback) ao seu próprio projeto de hospedagem.

## 6. Publicar com Nginx, certificado e Cloudflare

Defina o domínio real, instale o template do repositório no Nginx e troque os dois
placeholders (domínio e porta de loopback) antes de validar a configuração:

```sh
DOMAIN=<novo-dominio>
set -a
. ./.env
set +a
# Família Debian usa sites-available/sites-enabled; família RHEL e a maioria
# das outras distros usam /etc/nginx/conf.d — o teste de diretório decide:
if [ -d /etc/nginx/sites-available ]; then
  NGINX_CONF=/etc/nginx/sites-available/pca.conf
  sudo cp ops/nginx/pca.conf "$NGINX_CONF"
  sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/pca.conf
else
  NGINX_CONF=/etc/nginx/conf.d/pca.conf
  sudo cp ops/nginx/pca.conf "$NGINX_CONF"
fi
sudo sed -i "s|<dominio-da-vps>|${DOMAIN}|g; s|127.0.0.1:8000|127.0.0.1:${WEB_PORT}|g" "$NGINX_CONF"
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d "$DOMAIN"
```

Na família RHEL, se `nginx -t` passar mas `https://<novo-dominio>` responder
`502`, confira os dois pré-requisitos do Caminho B do Passo 1: o boolean
SELinux `httpd_can_network_connect` ativo e o firewalld com `http`/`https`
liberados.

No painel Cloudflare do domínio, selecione **SSL/TLS → Overview → Full (strict)**.
Não use **Flexible**: conforme o comentário em
[`ops/nginx/pca.conf`](./nginx/pca.conf), ele faz o Cloudflare falar HTTP com a
origem, enquanto Django redireciona para HTTPS, produzindo um loop infinito de 301.
Esta topologia tem Cloudflare e Nginx como os dois proxies confiáveis assumidos por
`AXES_IPWARE_PROXY_COUNT = 2` em [`config/settings/prod.py`](../config/settings/prod.py);
revise esse valor se a topologia da nova VM tiver outro número de proxies.

## 7. Executar o teste de aceite externo

De um navegador fora da rede local da VM, abra `https://<novo-dominio>` e entre com
uma conta real que veio no dump. Confirme que o dashboard apresenta a mesma contagem
de processos conhecida no ambiente de origem. Como usuário com permissão de edição,
altere inline um campo permitido — por exemplo, `grau_prioridade` na tabela — e salve.
Por fim, abra Django Admin → **PCA — processos e acompanhamentos** → o modelo
histórico de Processo (`HistoricalProcesso`) e confirme uma nova linha histórica para
o processo, identificando o usuário que fez a edição. Isso prova login, dados
restaurados e auditoria `django-simple-history`, não apenas que o banco aceitou o dump.

## Não objetivos

Este runbook não recria contas de usuário: elas já devem chegar dentro do dump
restaurado. Isto é diferente de uma instalação vazia seguida de `importar_pca`, que
importa os dados do PCA mas não cria usuários. Não confunda o caminho de restauração
deste documento com esse caminho de importação inicial.
