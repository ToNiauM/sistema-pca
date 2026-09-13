# Nota sobre o vendor ausente nesta cópia da skill

Esta cópia de `.claude/skills/dsgov/` **não inclui `assets/vendor/`** (~4 MB —
`@govbr-ds/core@3.7.0`, Font Awesome Free 5.15.4, fontes Rawline/Raleway,
htmx 2.0.10, Apache ECharts 5.5.0). Não é uma cópia incompleta por engano: o
mesmo conteúdo já está vendorizado e congelado em `core/static/dsgov/vendor/`
deste repositório — trazê-lo de novo aqui duplicaria os mesmos 4 MB sem
necessidade.

## Consequência prática

`scripts/verificar.py` e `scripts/novo_projeto.py` **desta cópia** resolvem
os caminhos de `CORE_CSS`/`FA_CSS`/`VENDOR` a partir do próprio diretório da
skill (`SKILL / "assets/vendor/..."`). Sem o vendor:

- `scripts/verificar.py` tem um **fallback**: se `assets/vendor/...` não
  existir, ele procura o mesmo asset em `core/static/dsgov/vendor/...` a
  partir da raiz do projeto informado na linha de comando. Funciona sem
  ajuste — mas é específico desta cópia, não do script original da skill.
- `scripts/novo_projeto.py` **não tem** esse fallback — ele copia
  `assets/vendor/` para o projeto novo, e vai falhar com `FileNotFoundError`
  se rodado diretamente a partir desta cópia.

## Como verificar conformidade neste repositório

Use sempre `ops/dsgov/verificar.py` (a cópia portátil na raiz do projeto,
já repontada para `core/static/dsgov/**` — funciona sem depender de nenhum
vendor externo, é a mesma que a suíte de testes e o CI rodam):

```sh
python3 ops/dsgov/verificar.py . --avisos-como-erros
```

## Como gerar um projeto NOVO com esta skill

`novo_projeto.py`/`aplicar.py` precisam da skill original **completa** (com
`assets/vendor/`) instalada em outro lugar — a cópia aqui dentro não serve
para isso. A fonte de verdade da skill vem de fora deste repositório (quem
mantém a skill decide onde publicá-la); reobtenha o vendor da mesma versão
documentada no `CLAUDE.md` deste projeto (DSGov 3.7.0 core puro) antes de
rodar esses dois scripts.
