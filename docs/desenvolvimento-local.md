# Desenvolvimento local

## Pré-requisitos

- Docker e Docker Compose (plugin `docker compose`).
- Nada mais no host: todo o resto (Python 3.12, Postgres 17, dependências) vive dentro dos
  containers do próprio `compose.yml`.

## Passo a passo

1. **Clonar o repositório e entrar nele.**
2. **Copiar o arquivo de variáveis de ambiente:**
   ```sh
   cp .env.example .env
   ```
3. **Gerar um `SECRET_KEY` novo** (nunca reaproveite um de outro ambiente) e colar em `.env`:
   ```sh
   python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
   ```
   Ajuste também `POSTGRES_PASSWORD`/`DATABASE_URL` em `.env` se quiser uma senha própria (os
   valores padrão do `.env.example` já funcionam para desenvolvimento local).
4. **Criar o volume externo do Postgres** — obrigatório antes do primeiro `up`, porque
   `compose.yml` declara `pgdata` como volume externo (nunca apagado por `docker compose down -v`):
   ```sh
   docker volume create pca_pgdata
   ```
5. **Subir os serviços:**
   ```sh
   docker compose up -d
   ```
   O `entrypoint.sh` do serviço `web` já roda `python manage.py migrate --noinput`
   automaticamente antes de iniciar o Gunicorn — rodar `migrate` manualmente só é necessário se
   você quiser aplicar uma migration nova sem reiniciar o container:
   ```sh
   docker compose exec web python manage.py migrate
   ```
6. **Criar um superusuário:**
   ```sh
   docker compose exec web python manage.py createsuperuser
   ```
7. **Popular dados de exemplo.** `importar_pca` exige um `Exercicio` já existente — crie um pelo
   Django Admin (`/admin/catalogo/exercicio/add/`, ano + rótulo, situação "Aberto") e então:
   ```sh
   docker compose exec web python manage.py importar_pca --exercicio <ano>
   ```
   O argumento `caminho` (posicional, opcional) tem como default
   `apps/pca/fixtures/modelo-controle-exemplo.xlsx` — a fixture de exemplo com 30 processos e
   75 acompanhamentos inteiramente fictícios; não é necessário informar um caminho.
8. **Acessar o sistema:** `http://localhost:${WEB_PORT}` (o valor de `WEB_PORT` está em `.env`;
   `8000` no `.env.example`).
9. **Rodar a suíte de testes:**
   ```sh
   docker compose exec web python manage.py test
   ```
10. **Rodar o verificador de conformidade DSGov** (guarda único de padrão visual):
    ```sh
    docker compose exec web python3 ops/dsgov/verificar.py . --avisos-como-erros
    ```

## Rebuild de imagem

`docker compose build web && docker compose up -d web` só é necessário quando você muda
`Dockerfile`, `requirements.txt`, `entrypoint.sh` ou `core/static/dsgov/**` — não há estágio Node
no build (o vendor DSGov é `COPY . .` normal). Para qualquer outra mudança de código Python ou
template, `docker compose restart web` (ou nada, se o servidor de desenvolvimento recarregar
sozinho) basta.

**Fontes verificadas:** `compose.yml`, `entrypoint.sh`, `.env.example`,
`apps/pca/management/commands/importar_pca.py`, `apps/catalogo/admin.py` (`ExercicioAdmin`),
`CLAUDE.md` (seção "Testes-guarda e como rodar").
