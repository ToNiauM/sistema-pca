---
name: dsgov
description: Constrói sistemas web (Django + HTML/CSS/JS) com a identidade visual do Design System do governo federal (gov.br/ds, DSGov 3.7.0) de forma determinística — scaffold de projeto, geração de módulos CRUD a partir de um sistema.yaml, dashboard com ECharts, formulários e tabelas já no padrão, e um verificador bloqueante que impede qualquer desvio do DS. Use SEMPRE que o usuário pedir para criar, gerar, montar ou prototipar um sistema, aplicativo, painel, dashboard, CRUD, cadastro, listagem, formulário, tela ou módulo — mesmo que ele não mencione "design system", "DSGov", "gov.br", "Django" ou "padrão". Use também para "aplicar o padrão gov.br", "deixar com a cara do governo", "colocar no DSGov", reformar telas de um Django existente, ou quando o usuário chamar /dsgov. Não use para sistemas que explicitamente devem ter outra identidade visual, para apps nativos mobile ou para sites de conteúdo (portais/blogs).
---

# dsgov — sistemas com a cara do gov.br, sem decisões de design

Esta skill existe para tirar de você toda decisão visual. Cor, fonte, espaçamento, componente, layout de
tela e comportamento de tabela já estão decididos pelo Design System gov.br 3.7.0 e congelados aqui.
Seu trabalho é o **negócio**: entender o que o usuário precisa controlar, traduzir isso num `sistema.yaml`,
gerar, e então escrever regras, cálculos, permissões e fluxos em Python. Se em algum momento você se pegar
escolhendo uma cor, um tamanho ou "um jeito melhor de mostrar", pare: a resposta está nas referências ou
o pedido está fora do padrão.

`<skill>` abaixo é a pasta desta skill (o harness informa o caminho). Rode os scripts com o **Python do
projeto** (uma venv com `requirements-dev.txt` instalado, que inclui PyYAML e Django): eles chamam
`manage.py makemigrations` e precisam do Django importável. Crie a venv antes do scaffold se não existir.

## Fluxo (siga na ordem; cada passo é um comando, não uma decisão)

### 1. Entender e especificar (a única parte que exige julgamento)

Extraia do pedido: nome do sistema, órgão e sigla, e os módulos com seus campos. Pergunte só o que for
indispensável e não puder ser suposto com bom senso (ex.: quais situações um processo pode ter). Escreva
o `sistema.yaml` conforme `references/especificacao.md` e mostre ao usuário um resumo de uma linha por
módulo antes de gerar. Nomes em português, como no resto do código.

### 2. Criar o projeto (ou aplicar num existente)

```bash
python3 <skill>/scripts/novo_projeto.py <pasta> --sistema "Nome do Sistema" --orgao "Nome do Órgão" \
    --sigla SIGLA [--subtitulo "..."] --yaml sistema.yaml
```

Isso cria Django 5.2 + HTMX + DSGov congelado (CSS, JS, fontes Rawline/Raleway, Font Awesome 5, ECharts)
com login, layout (skiplink, header, menu lateral, breadcrumb, footer), renderer de formulários,
listagem genérica, dashboard vazio, Docker Compose com PostgreSQL, e já gera os módulos do YAML.
Projeto Django que já existe: `python3 <skill>/scripts/aplicar.py <raiz>` e siga o que ele imprime.

Módulos depois do scaffold: `python3 <skill>/scripts/gerar_app.py <raiz> sistema.yaml` (idempotente;
`--forcar` sobrescreve). Depois: `python manage.py migrate` e `createsuperuser`.

### 3. Regras de negócio (aqui você programa)

- `apps/<app>/forms.py` → `clean()` para regras entre campos; `models.py` → métodos, propriedades,
  `save()`; views de ação (aprovar, cancelar) como POST com `messages` e redirect para o detalhe.
- Dashboard: preencha `kpis`, `graficos` e `pendencias` em `core/views.py::inicio` usando
  `core/graficos.py` (`references/telas/dashboard.md`). Agregue com o ORM.
- Permissões via grupos; o menu e as views já respeitam `app.view_modelo` etc.
- Testes de regra ao lado dos gerados (`pytest`).
Leia `references/django.md` antes de escrever a primeira view à mão.

### 4. Verificar (bloqueante) e entregar

```bash
python3 <skill>/scripts/verificar.py <raiz>
python -m pytest -q
```

Saída 1 do verificador = não está pronto. Corrija o que ele apontar (`references/verificador.md` explica
cada regra) e rode de novo. Só então diga ao usuário que a tela está pronta, com o comando para subir
(`runserver` ou `docker compose up`) e o usuário/senha criados.

## O que é fixo (não reabra)

| Assunto | Decisão | Onde está |
|---|---|---|
| Paleta, tipografia, espaçamento | tokens do DS 3.7.0; só variáveis/classes, nunca hex | `references/tokens.md`, `utilitarios.md` |
| Estrutura de página | skiplink → header → menu lateral → breadcrumb → mensagens → conteúdo → footer | `references/layout.md` |
| Telas | dashboard, listagem, formulário, detalhe, exclusão, login, wizard, relatório, **matriz de indicadores**, **calendário** | `references/telas/*.md` |
| Componentes | HTML canônico de cada `br-*` com modificadores e `data-*` | `references/componentes/<nome>.md` |
| Gráficos | ECharts 5.5.0, tema `dsgov`, 5 tipos permitidos | `references/graficos.md` |
| Formulários | `{{ form }}` via renderer; `<select>` nativo proibido | `references/django.md` |
| Tabelas | server-side, 10/20/50 por página, ordenação por cabeçalho, ações à direita | `references/telas/listagem.md` |
| Ícones | Font Awesome 5 `fas`, vocabulário fixo por ação | `references/tokens.md` § Ícones |
| Tema | só claro | — |
| CSS do projeto | apenas `dsgov.css` da skill, intocável | `references/verificador.md` |
| Acessibilidade | WCAG 2.1 AA / e-MAG; `h1` único, `aria-label` em ícones | `references/acessibilidade.md` |

## Quando escrever HTML à mão

Telas que o gerador não cobre (uma tela de aprovação com resumo e botões, um relatório) são compostas
com os mesmos blocos: `{% extends "base.html" %}`, cabeçalho `h1` + ações, `br-card`, `dl.dsgov-detalhe`,
`br-table`, `{{ form }}`. Antes de escrever, abra o `references/componentes/<nome>.md` do componente e
copie o HTML canônico; adapte só textos e dados. Classes utilitárias permitidas estão em
`references/utilitarios.md`. Se precisa de algo que não existe lá, a tela está errada, não a skill.

## Sinais de que você está saindo do padrão

- Escreveu `style=`, um hex, `<style>`, um `<select>`, um `<button>` sem `br-button`, ou criou um `.css`.
- Mudou `dsgov.css`, `base.html` ou um partial de `dsgov/` para "ajustar" algo de uma tela.
- Colocou um segundo botão `primary` na mesma tela, ou dois `h1`.
- Escolheu cores para um gráfico por conta própria.
- Fez edição inline em tabela, modal de confirmação, tema escuro, menu horizontal.
Cada um desses é reprovado pelo verificador ou contraria `references/`. Volte ao bloco equivalente.
