"""Contratos de formulário da tela Processos: servem só para renderizar os
campos com o DSGovFormRenderer. A leitura validada do GET continua
inteiramente em apps/pca/filtros.py."""

from django import forms

from apps.catalogo.models import Modalidade
from apps.pca.colunas import COLUNAS, COLUNAS_PADRAO
from apps.pca.filtros import (
    SENTINEL_NAO_CLASSIFICADO,
    SENTINEL_SEM_MES,
    opcoes_filtros,
)
from apps.pca.models import Estado, Reuniao, Situacao

# apps.pca.colunas é a fonte única de colunas (registro + padrão)


class FiltrosProcessoForm(forms.Form):
    """Um campo por chave "de catálogo" de PARAMETROS_FILTRO — as flags de
    drill-down do dashboard continuam só leitura via link, sem campo
    visível. exercicio também fica fora, propagado por um hidden input."""

    # grade de filtros em 3 blocos: faixa 1 (q/uo), faixa 2 (situacao/mes),
    # "Mais filtros" (demais campos secundários); col usa as classes DS
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # consultas resolvidas na instanciação, nunca no corpo da classe
        opcoes = opcoes_filtros()
        self.fields["uo"].queryset = opcoes["uo"]
        self.fields["categoria"].queryset = opcoes["categoria"]
        self.fields["tipo"].queryset = opcoes["tipo"]
        self.fields["modalidade"].queryset = Modalidade.objects.order_by("nome")
        self.fields["prioridade"].choices = [
            (str(item.pk), item.nome) for item in opcoes["prioridade"]
        ] + [(SENTINEL_NAO_CLASSIFICADO, "Não classificado")]
        self.fields["classificacao"].choices = [
            (str(item.pk), item.nome) for item in opcoes["classificacao"]
        ] + [(SENTINEL_NAO_CLASSIFICADO, "Não classificado")]
        self.fields["mes"].choices = list(opcoes["mes"]) + [
            (SENTINEL_SEM_MES, "Sem mês previsto")
        ]


class ExportarForm(forms.Form):
    """Colunas escolhíveis da página de exportação. A interface oferece
    somente XLSX: formato é um campo oculto travado em "xlsx" (a rota CSV
    continua respondendo por compatibilidade, só a interface fecha)."""

    formato = forms.CharField(widget=forms.HiddenInput, initial="xlsx")
    colunas = forms.MultipleChoiceField(
        choices=[(coluna.chave, coluna.rotulo) for coluna in COLUNAS],
        required=False,
        label="Colunas",
        initial=[coluna.chave for coluna in COLUNAS if coluna.chave in COLUNAS_PADRAO],
    )
