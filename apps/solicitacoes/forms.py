"""Formulários das telas de Solicitações (Fase 43).

Só leem e conferem a entrada; quem decide e grava é `services.py` (sempre por ele). Os campos são
renderizados pelo renderer da casca ativa (`core/forms/renderer.py`): DSGov ou Tabler, mesmo form.
Valores monetários aceitam a forma crua (`35000.00`) e a mascarada pt-BR (`35.000,00`), como o
`ProcessoForm`.
"""

from decimal import Decimal

from django import forms

from apps.catalogo.models import Categoria, Tipo
from apps.pca.filtros import MESES, NOMES_MES

from . import regras
from .regras import Campo

OPCOES_MES = [("", "Selecione")] + [(str(numero), NOMES_MES[numero]) for numero in MESES]


def _monetario(bruto: str) -> Decimal:
    """Decimal do texto digitado, com o mesmo rigor do `ProcessoForm` (sem sinal, sem notação
    científica, no máximo 2 casas) e maior que zero."""
    from apps.pca.views import _normalizar_valor_monetario, _valor_monetario_formato_valido

    normalizado = _normalizar_valor_monetario(str(bruto).strip())
    if not _valor_monetario_formato_valido(normalizado):
        raise forms.ValidationError("Informe um valor monetário válido, como 35.000,00.")
    valor = Decimal(normalizado)
    if valor <= 0:
        raise forms.ValidationError("Informe um valor maior que zero.")
    return valor


def _data(col=""):
    """Campo de data nativo; `col` é a largura no renderer de formulário inteiro (`{{ form }}`) — as
    telas que montam as linhas à mão (pedido de alteração, decisão) não passam `col`."""
    atributos = {"type": "date", **({"col": col} if col else {})}
    return forms.DateInput(format="%Y-%m-%d", attrs=atributos)


class SelecionarItemForm(forms.Form):
    """Passo 1 de "alterar ou cancelar": escolher o item (só os itens das unidades do usuário)."""

    processo = forms.ChoiceField(label="Item do PCA", choices=[])

    def __init__(self, *args, itens, **kwargs):
        super().__init__(*args, **kwargs)
        opcoes = [("", "Selecione")]
        for item in itens:
            objeto = " ".join(item.descricao_objeto.split())
            if len(objeto) > 90:
                objeto = objeto[:89] + "…"
            opcoes.append((f"{item.exercicio.ano}/{item.item_pca}", f"Item {item.item_pca} — {objeto}"))
        self.fields["processo"].choices = opcoes


class AlteracaoForm(forms.Form):
    """Passo 2 de "alterar ou cancelar": só os campos que o item aceita. Campo
    preenchido = campo pedido; cancelamento é um pedido separado e exclusivo."""

    justificativa = forms.CharField(
        label="Justificativa",
        widget=forms.Textarea(attrs={"rows": 4}),
        max_length=regras.LIMITE_TEXTO,
        error_messages={"required": "Informe a justificativa do pedido."},
    )
    numero_sei = forms.CharField(
        label="Nº do processo SEI",
        required=False,
        max_length=50,
        help_text="Opcional: o processo SEI em que o pedido foi tratado.",
    )

    def __init__(self, *args, campos_aceitos, **kwargs):
        super().__init__(*args, **kwargs)
        self.campos_aceitos = tuple(campos_aceitos)
        self.pedidos: dict = {}
        novos = {}
        if Campo.PRAZO_ENTREGA in self.campos_aceitos:
            novos["prazo_entrega"] = forms.DateField(
                label="Novo prazo de entrega", required=False, widget=_data(),
                error_messages={"invalid": "Informe uma data válida."},
            )
        if Campo.MES_PREVISTO in self.campos_aceitos:
            novos["mes_previsto"] = forms.ChoiceField(
                label="Novo mês previsto", required=False, choices=OPCOES_MES
            )
        if Campo.VALOR_ESTIMADO in self.campos_aceitos:
            novos["valor_estimado"] = forms.CharField(
                label="Novo valor estimado (R$)", required=False, help_text="Ex.: 35.000,00",
                widget=forms.TextInput(attrs={"inputmode": "decimal"}),
            )
        if Campo.DESCRICAO_OBJETO in self.campos_aceitos:
            novos["descricao_objeto"] = forms.CharField(
                label="Novo objeto", required=False, max_length=regras.LIMITE_TEXTO,
                widget=forms.Textarea(attrs={"rows": 3}),
            )
        if Campo.CANCELAMENTO in self.campos_aceitos:
            novos["cancelamento"] = forms.BooleanField(
                label="Pedir o cancelamento do item", required=False
            )
        # Campos do pedido antes da justificativa, na ordem de tela.
        ordem = [*novos, "justificativa", "numero_sei"]
        self.fields = {nome: {**novos, **self.fields}[nome] for nome in ordem}

    def clean_valor_estimado(self):
        bruto = self.cleaned_data.get("valor_estimado")
        return _monetario(bruto) if bruto and bruto.strip() else None

    def clean_descricao_objeto(self):
        return " ".join((self.cleaned_data.get("descricao_objeto") or "").split())

    def clean(self):
        cleaned = super().clean()
        pedidos = {}
        for campo in (Campo.PRAZO_ENTREGA, Campo.MES_PREVISTO, Campo.VALOR_ESTIMADO, Campo.DESCRICAO_OBJETO):
            valor = cleaned.get(campo.value)
            if valor not in (None, ""):
                pedidos[campo] = valor
        cancelar = bool(cleaned.get("cancelamento"))
        if cancelar and pedidos:
            self.add_error(
                "cancelamento",
                "O cancelamento é pedido sozinho: deixe os outros campos em branco.",
            )
        elif cancelar:
            pedidos[Campo.CANCELAMENTO] = None
        if not pedidos and not self.errors:
            raise forms.ValidationError(
                "Preencha ao menos um campo com o valor pedido ou peça o cancelamento do item."
            )
        self.pedidos = pedidos
        return cleaned


class InclusaoForm(forms.Form):
    """Pedido de inclusão de item novo."""

    unidade = forms.ChoiceField(label="Unidade organizacional", widget=forms.Select(attrs={"col": "col-md-6"}))
    descricao_objeto = forms.CharField(
        label="Objeto", max_length=regras.LIMITE_TEXTO, widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Informe o objeto."},
    )
    tipo = forms.ChoiceField(label="Tipo", widget=forms.Select(attrs={"col": "col-md-6"}))
    categoria = forms.ChoiceField(label="Categoria", widget=forms.Select(attrs={"col": "col-md-6"}))
    valor_estimado = forms.CharField(
        label="Valor estimado (R$)", help_text="Ex.: 35.000,00",
        widget=forms.TextInput(attrs={"inputmode": "decimal", "col": "col-md-6"}),
        error_messages={"required": "Informe o valor estimado."},
    )
    mes_previsto = forms.ChoiceField(
        label="Mês previsto", choices=OPCOES_MES, widget=forms.Select(attrs={"col": "col-md-6"}),
        error_messages={"required": "Informe o mês previsto."},
    )
    prazo_entrega = forms.DateField(
        label="Prazo de entrega", required=False, widget=_data("col-md-6"),
        help_text="Opcional.", error_messages={"invalid": "Informe uma data válida."},
    )
    justificativa = forms.CharField(
        label="Justificativa", max_length=regras.LIMITE_TEXTO, widget=forms.Textarea(attrs={"rows": 4}),
        error_messages={"required": "Informe a justificativa do pedido."},
    )
    numero_sei = forms.CharField(
        label="Nº do processo SEI", required=False, max_length=50,
        help_text="Opcional: o processo SEI em que o pedido foi tratado.",
        widget=forms.TextInput(attrs={"col": "col-md-6"}),
    )

    def __init__(self, *args, unidades, **kwargs):
        super().__init__(*args, **kwargs)
        unidades = list(unidades)
        self.fields["unidade"].choices = [("", "Selecione")] + [(str(u.pk), u.nome) for u in unidades]
        if len(unidades) == 1:
            self.fields["unidade"].initial = str(unidades[0].pk)
        self.fields["tipo"].choices = [("", "Selecione")] + [
            (str(t.pk), t.nome) for t in Tipo.objects.filter(nome_normalizado__in=regras.TIPOS_DE_INCLUSAO)
        ]
        self.fields["categoria"].choices = [("", "Selecione")] + [
            (str(c.pk), c.nome) for c in Categoria.objects.all()
        ]

    def clean_valor_estimado(self):
        return _monetario(self.cleaned_data["valor_estimado"])

    def clean_descricao_objeto(self):
        return " ".join(self.cleaned_data["descricao_objeto"].split())


class DecisaoForm(forms.Form):
    """Decisão de UMA parte. Um formulário por parte, com prefixo próprio; o valor do
    ajuste muda de tipo conforme o campo. Ajuste e recusa exigem motivo (conferido por `regras`)."""

    decisao = forms.ChoiceField(
        label="Decisão",
        widget=forms.RadioSelect,
        choices=[],
        error_messages={"required": "Escolha aprovar, aprovar com ajuste ou recusar."},
    )
    valor_ajuste = forms.CharField(label="Valor do ajuste", required=False)
    motivo = forms.CharField(
        label="Motivo", required=False, max_length=regras.LIMITE_TEXTO,
        help_text="Obrigatório no ajuste e na recusa.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, campo, **kwargs):
        super().__init__(*args, **kwargs)
        self.campo = Campo(campo)
        self.fields["decisao"].choices = [(d.value, d.label) for d in regras.decisoes_admitidas(self.campo)]
        if regras.Decisao.AJUSTE not in regras.decisoes_admitidas(self.campo):
            del self.fields["valor_ajuste"]
            return
        ajuste = self.fields["valor_ajuste"]
        if self.campo == Campo.PRAZO_ENTREGA:
            self.fields["valor_ajuste"] = forms.DateField(
                label="Data do ajuste", required=False, widget=_data(),
                error_messages={"invalid": "Informe uma data válida."},
            )
        elif self.campo == Campo.MES_PREVISTO:
            self.fields["valor_ajuste"] = forms.ChoiceField(
                label="Mês do ajuste", required=False, choices=OPCOES_MES
            )
        elif self.campo == Campo.VALOR_ESTIMADO:
            ajuste.label = "Valor do ajuste (R$)"
            ajuste.widget = forms.TextInput(attrs={"inputmode": "decimal"})
            ajuste.help_text = "Ex.: 35.000,00. Só se aprovar com ajuste."
        else:
            ajuste.label = "Objeto do ajuste"
            ajuste.widget = forms.Textarea(attrs={"rows": 3})
        if not self.fields["valor_ajuste"].help_text:
            self.fields["valor_ajuste"].help_text = "Só se aprovar com ajuste."

    def clean_valor_ajuste(self):
        valor = self.cleaned_data.get("valor_ajuste")
        if self.campo == Campo.VALOR_ESTIMADO and valor and str(valor).strip():
            return _monetario(valor)
        return valor
