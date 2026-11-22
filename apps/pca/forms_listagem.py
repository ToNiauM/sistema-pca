"""Contratos de formulário da tela Processos.

Nenhum destes forms decide o filtro real: servem só para
RENDERIZAR os campos com o `DSGovFormRenderer`. A leitura validada do GET
continua inteiramente em `apps/pca/filtros.py` (`filtros_ativos`/
`queryset_filtrado`) — `tabela_view` nunca chama `.is_valid()` destes forms
como fonte de filtragem.
"""

from django import forms
from django.db.models import F
from django.db.models.functions import Collate

from apps.catalogo.models import Modalidade
from apps.pca.colunas import COLUNAS, COLUNAS_PADRAO, _filtrar_restritas
from apps.pca.filtros import (
    SENTINEL_NAO_CLASSIFICADO,
    SENTINEL_SEM_MES,
    opcoes_filtros,
    opcoes_unidade_sei,
)
from apps.pca.models import Estado, Reuniao, Situacao

# Fase 28 — `apps.pca.colunas` é a fonte única de
# colunas (registro + padrão), eliminando a dependência circular que este
# módulo tinha com `views.py` (import local dentro de `tabela_view`, pré-
# existente por causa desse ciclo).


class FiltrosProcessoForm(forms.Form):
    """Um campo por chave "de catálogo" de `PARAMETROS_FILTRO` — as 9 flags
    de drill-down do dashboard (`atrasado`, `reprometidos`, `contratado`,
    `publicacao_pendente`, `criticos`, `proximo_prazo`, `sem_atualizacao`,
    `vencimento_proximo`, `sobrestado`) continuam só leitura via link, sem
    campo visível. `exercicio` também fica fora deste form: é o
    único parâmetro propagado pelo menu/links entre telas, carregado por um
    `<input type="hidden">` simples no template, nunca reescrito por este
    formulário de filtros compostos."""

    # Fase 28 — grade de filtros em 3 blocos: faixa 1
    # (q/uo, 6/6 >= 992), faixa 2 (situacao/mes, 6/6), "Mais filtros" (3/2/1
    # controles por linha em desktop amplo/intermediário/pequeno). `col`
    # troca de `col-md-N` (Bootstrap-like da Fase 25) para as classes DS
    # `col-12 col-md-6[ col-lg-4]` — nenhum `name=` de campo muda.
    #
    # `estado` (Ativo/Cancelado) não constava na enumeração EJAMENTO.md (só cita 11 dos 12 campos de "Mais filtros"),
    # lacuna corrigida aqui (campo real do form, removê-lo seria
    # regressão funcional): entra em "Mais filtros" com a mesma classe dos
    # demais campos secundários.
    q = forms.CharField(
        required=False,
        label="Busca",
        widget=forms.TextInput(attrs={"col": "col-12 col-md-6"}),
    )
    uo = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label="Unidade",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6"}),
    )
    categoria = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label="Categoria",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    tipo = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label="Tipo",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    prioridade = forms.MultipleChoiceField(
        choices=(), required=False, label="Prioridade",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    classificacao = forms.MultipleChoiceField(
        choices=(), required=False, label="Classificação",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    modalidade = forms.ModelChoiceField(
        queryset=None, required=False, label="Modalidade",
        widget=forms.Select(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    unidade_sei = forms.ChoiceField(
        choices=(), required=False, label="Unidade no SEI",
        widget=forms.Select(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    estado = forms.MultipleChoiceField(
        choices=Estado.choices, required=False, label="Estado",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    situacao = forms.MultipleChoiceField(
        choices=Situacao.choices, required=False, label="Situação",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6"}),
    )
    mes = forms.MultipleChoiceField(
        choices=(), required=False, label="Mês previsto",
        widget=forms.SelectMultiple(attrs={"col": "col-12 col-md-6"}),
    )
    desde_reuniao = forms.ModelChoiceField(
        queryset=Reuniao.objects.order_by("-data"),
        required=False,
        label="Alterações na reunião",
        widget=forms.Select(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    legados = forms.BooleanField(
        required=False, label="Apenas itens legados",
        widget=forms.CheckboxInput(attrs={"col": "col-12 col-md-6 col-lg-4"}),
    )
    recebido_de = forms.DateField(
        required=False,
        label="Recebido no Gelic de",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "col": "col-12 col-md-6 col-lg-4"},
        ),
    )
    recebido_ate = forms.DateField(
        required=False,
        label="Recebido no Gelic até",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "col": "col-12 col-md-6 col-lg-4"},
        ),
    )
    vigencia_fim_de = forms.DateField(
        required=False,
        label="Vigência fim de",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "col": "col-12 col-md-6 col-lg-4"},
        ),
    )
    vigencia_fim_ate = forms.DateField(
        required=False,
        label="Vigência fim até",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "col": "col-12 col-md-6 col-lg-4"},
        ),
    )

    def __init__(self, *args, exercicio=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Consultas resolvidas na instanciação (nunca no corpo da classe,
        # para não bater no banco na importação do módulo) — mesma fonte
        # de opções que `_filtros.html` legado usava.
        opcoes = opcoes_filtros()
        self.fields["uo"].queryset = opcoes["uo"]
        self.fields["categoria"].queryset = opcoes["categoria"]
        self.fields["tipo"].queryset = opcoes["tipo"]
        self.fields["modalidade"].queryset = Modalidade.objects.order_by(
            Collate(F("nome"), "ptbr")
        )
        self.fields["prioridade"].choices = [
            (str(item.pk), item.nome) for item in opcoes["prioridade"]
        ] + [(SENTINEL_NAO_CLASSIFICADO, "Não classificado")]
        self.fields["classificacao"].choices = [
            (str(item.pk), item.nome) for item in opcoes["classificacao"]
        ] + [(SENTINEL_NAO_CLASSIFICADO, "Não classificado")]
        self.fields["mes"].choices = list(opcoes["mes"]) + [
            (SENTINEL_SEM_MES, "Sem mês previsto")
        ]
        # Opções restritas ao exercício corrente, mesma
        # lógica de `opcoes_unidade_sei`.
        self.fields["unidade_sei"].choices = [
            ("", "Todas as unidades")
        ] + [(sigla, sigla) for sigla in opcoes_unidade_sei(exercicio)]


class ExportarForm(forms.Form):
    """Colunas escolhíveis da página `pca:exportar`. Sem
    `clean()` de negócio — a filtragem de colunas inválidas continua em
    `apps/pca/exportacao.py::_colunas_resolvidas`.

    Fase 28 — a interface de Processos oferece
    SOMENTE XLSX: `formato` deixa de ser um `RadioSelect` visível e vira
    um campo oculto travado em `"xlsx"` (CSV desaparece da UI, mas
    `pca:exportar_csv`/o ramo CSV desta view continuam respondendo por
    compatibilidade — só fecha a INTERFACE, não a rota)."""

    formato = forms.CharField(widget=forms.HiddenInput, initial="xlsx")
    colunas = forms.MultipleChoiceField(
        choices=[(coluna.chave, coluna.rotulo) for coluna in COLUNAS],
        required=False,
        label="Colunas",
        initial=[coluna.chave for coluna in COLUNAS if coluna.chave in COLUNAS_PADRAO],
    )

    def __init__(self, *args, request=None, **kwargs):
        """QA de segurança 30/09/2026 (achado M2) — sem
        `pca.view_acompanhamento` (`request`), as colunas de
        `CHAVES_RESTRITAS_ACOMPANHAMENTO` somem das `choices` do campo: o
        próprio form já não oferece a opção, mesmo que o cliente a envie
        diretamente no POST (`is_valid()` recusa escolha fora de
        `choices`)."""
        super().__init__(*args, **kwargs)
        chaves_permitidas = _filtrar_restritas(
            [coluna.chave for coluna in COLUNAS], request
        )
        permitidas = set(chaves_permitidas)
        self.fields["colunas"].choices = [
            (coluna.chave, coluna.rotulo)
            for coluna in COLUNAS
            if coluna.chave in permitidas
        ]
