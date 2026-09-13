# Contribuindo

Contribuições são bem-vindas. Para convenções de código, testes e o guia completo de
desenvolvimento local, veja [`docs/contribuicao.md`](docs/contribuicao.md) e o `CLAUDE.md` na raiz
do repositório (fonte da verdade para padrões de escrita e componentes).

Antes de abrir um PR, confirme:

- `python manage.py test` passa (suíte completa, contra PostgreSQL — nunca SQLite).
- `python3 ops/dsgov/verificar.py . --avisos-como-erros` não aponta erro.
- Documentação atualizada quando o comportamento muda.

Veja o checklist completo em [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
