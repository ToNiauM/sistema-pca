# Verificador (`scripts/verificar.py`)

Bloqueante. Rode antes de dizer que qualquer tela está pronta; saída 1 significa trabalho não concluído.

```
python3 <skill>/scripts/verificar.py <raiz-do-projeto>            # relatório legível
python3 <skill>/scripts/verificar.py <raiz-do-projeto> --json     # para CI
```

| Regra | O que pega | Como corrigir |
|---|---|---|
| CLASSE | classe que não existe no `core.min.css` 3.7.0, no Font Awesome 5 nem no `dsgov.css` | use a classe do DS equivalente (`references/utilitarios.md`); se precisa de algo novo, a tela está fora do padrão |
| ESTILO | `style=""` ou `<style>` em template | classes utilitárias do DS (`mb-3`, `text-center`, `d-flex`...) |
| COR | hex de cor em template | `bg-*`/`text-*` do DS ou tokens em `core/graficos.py` |
| CDN | `<link>`/`<script>` externo ou fora da lista fixa | tudo é servido de `core/static/dsgov` |
| CSS | `.css` do projeto fora da skill, ou `dsgov.css`/`fontes.css` alterados | apague; ajuste com classes |
| FONTE | `font-family` em template | remova; Rawline vem do DS |
| ESTRUTURA | `base.html` sem os partials na ordem; página sem `extends`; mais de um `h1`; página autônoma sem header/footer | siga `layout.md` |
| ELEMENTO | `<button>` sem `br-button`; `<select>` nativo; `<table>` fora de `br-table`; `<input>` fora de wrapper | use `{{ form }}`, `br-button`, `br-table` |
| ICONE (aviso) | `<i class="fa…">` sem `aria-hidden` | adicione o atributo |
| PRIMARIO (aviso) | mais de um `br-button primary` no template | só a ação principal é primária |

Exceções embutidas (não configure nada): classes de hook do JS do DS presentes nos exemplos oficiais
(`per-page`, `menu-close`, `header-avatar`...), classes de estado que o JS aplica (`active`, `expanded`),
`htmx-*`, e `theme-color` no `<head>`.

O verificador lê os templates como texto (não renderiza). Por isso, classes montadas dinamicamente
(`class="{{ classe }}"`) escapam dele: não faça isso. Use `{% if %}` com classes literais.
