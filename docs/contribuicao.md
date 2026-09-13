# Contribuição

## Preparar o ambiente

Veja [Desenvolvimento local](desenvolvimento-local.md) para o passo a passo completo (Docker
Compose, volume externo, superusuário, fixture de exemplo).

## Convenções de código

`CLAUDE.md`, na raiz do repositório, é a fonte da verdade para convenções de código: padrão de
componentes DSGov (zero `<br-*>` Custom Element, zero Shadow DOM, zero Alpine.js), regras de
escrita (classe `br-*` do DS, cor só via `var(--token)`, `{% comment %}` para comentário
multilinha, CSRF por `htmx:configRequest`, POST-redirect-GET), e os testes-guarda que toda
contribuição precisa continuar satisfazendo. Não duplicado aqui — leia `CLAUDE.md` antes de
escrever a primeira linha de template ou view.

## Migrations

- `python manage.py makemigrations` gera a migration; `python manage.py migrate` aplica.
- **Nunca edite uma migration já aplicada em algum ambiente** (dev, produção ou de outro
  contribuidor) — crie uma nova migration corretiva.
- **Nunca use `RunSQL` direto sem revisão** — prefira as operações declarativas do Django
  (`AddField`, `AlterField`, etc.); `RunSQL`/`RunPython` só quando não houver equivalente
  declarativo, e sempre revisado por outra pessoa antes de mesclar.
- Confira `python manage.py makemigrations --check --dry-run` antes de abrir um PR — nenhuma
  mudança de model deve ficar sem migration correspondente.

## Testes

```sh
docker compose exec web python manage.py test
```

A suíte roda **contra PostgreSQL, nunca SQLite** — `apps/pca/migrations/0002_unaccent.py` habilita
a extensão `unaccent` do Postgres (usada pelo lookup de busca sem acento), que não existe em
SQLite. Não é possível rodar a suíte completa com `DATABASES` apontando para SQLite.

Rode também o verificador de conformidade visual antes de abrir um PR:

```sh
docker compose exec web python3 ops/dsgov/verificar.py . --avisos-como-erros
```

## Branches, commits e PRs

Fluxo simples: crie uma branch a partir de `main`, escreva commits descritivos (o que mudou e
por quê, não só "fix"), abra um PR preenchendo o checklist do template
(`.github/PULL_REQUEST_TEMPLATE.md`) — testes rodando, `ops/dsgov/verificar.py` sem erro,
documentação atualizada quando o comportamento muda.

## Como atualizar a documentação

Edite os arquivos em `docs/*.md` (este site) e rode o build estrito localmente antes de
commitar:

```sh
mkdocs build --strict
```

Um build que falha em `--strict` (link quebrado, página fora da `nav`) não deve ser mesclado.

**Fontes verificadas:** `CLAUDE.md` (seções Conventions e "Testes-guarda e como rodar"),
`apps/pca/migrations/0002_unaccent.py`, `compose.yml`.
