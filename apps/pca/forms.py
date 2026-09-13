"""Contratos de formulário: `ProcessoForm` (criar/editar, página própria),
`AcompanhamentoForm` (único modal do sistema) e `TransicaoForm` (alterar
situação como página).

`CAMPOS_EDITAVEIS_PROCESSO` e `_normalizar_valor_monetario` continuam
definidos em `apps/pca/views.py` e são só importados de volta aqui, para
não duplicar a allowlist nem os formatos de valor monetário aceitos."""

from decimal import Decimal, InvalidOperation

from django import forms
from django.forms import inlineformset_factory

from apps.pca.filtros import MESES, NOMES_MES
from apps.pca.models import Estado, Processo, ProcessoSEI, Situacao
from apps.pca.rotulos import ROTULOS


def _campos_processo_form():
    """Import tardio: evita ciclo entre forms.py e views.py."""
    from apps.pca.views import CAMPOS_EDITAVEIS_PROCESSO

    return CAMPOS_EDITAVEIS_PROCESSO


def _normalizar_valor_monetario(bruto):
    from apps.pca.views import _normalizar_valor_monetario as normalizar

    return normalizar(bruto)


# campos que ganham col-md-6 no renderer; col-12 é o padrão
_CAMPOS_COL_MD6 = {
    "mes_previsto",
    "data_inclusao_pca",
    "data_envio_gelic",
    "prazo_entrega",
    "data_recebimento_gelic",
    "data_prevista_conclusao",
    "vigencia_inicio",
    "vigencia_fim",
    "data_assinatura_contrato",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
    "valor_estimado",
    "valor_contratado",
}

# aceitam forma crua (35000.00) e mascarada pt-BR (35.000,00); nascem
# CharField porque um DecimalField rejeitaria a vírgula antes de clean_<campo>
# rodar; a conversão para Decimal acontece em _limpar_monetario
_CAMPOS_MONETARIOS = ("valor_estimado", "valor_contratado")

# campos mínimos de criação — os únicos que ProcessoForm(criando=True) mantém
CAMPOS_CRIACAO_PROCESSO = (
    "descricao_objeto",
    "tipo",
    "categoria",
    "unidade_organizacional",
)


class ProcessoForm(forms.ModelForm):
    """Criar e editar um processo. `Meta.fields` é CAMPOS_EDITAVEIS_PROCESSO,
    a fronteira de confiança: campos como estado/situacao não são postáveis
    por este form. Na criação, só CAMPOS_CRIACAO_PROCESSO sobrevive."""

    class Meta:
        model = Processo
        fields = _campos_processo_form()
        widgets = {
            "justificativa": forms.Textarea(attrs={"rows": 3}),
        }
        # "Prazo inicial" vem de ROTULOS; verbose_name do model fica intocado
        labels = {"prazo_entrega": ROTULOS["prazo_entrega"]}
        help_texts = {
            "prazo_entrega": (
                "Prazo original do PCA. Adiamentos entram em Registrar "
                "acompanhamento."
            )
        }

    def __init__(self, *args, criando=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.criando = criando
        if criando:
            for nome in list(self.fields):
                if nome not in CAMPOS_CRIACAO_PROCESSO:
                    del self.fields[nome]

        for nome in _CAMPOS_MONETARIOS:
            if nome in self.fields:
                rotulo = self.fields[nome].label
                obrigatorio = self.fields[nome].required
                self.fields[nome] = forms.CharField(
                    label=rotulo, required=obrigatorio
                )

        for nome, campo in self.fields.items():
            if isinstance(campo, forms.DateField):
                campo.widget = forms.DateInput(
                    format="%Y-%m-%d", attrs={"type": "date"}
                )
            if nome in _CAMPOS_COL_MD6:
                campo.widget.attrs["col"] = "col-md-6"

        if "mes_previsto" in self.fields:
            self.fields["mes_previsto"] = forms.ChoiceField(
                label=self.fields["mes_previsto"].label,
                required=False,
                choices=[("", "---------")]
                + [(numero, NOMES_MES[numero]) for numero in MESES],
                widget=forms.Select(attrs={"col": "col-md-6"}),
            )

    def clean_valor_estimado(self):
        return self._limpar_monetario("valor_estimado")

    def clean_valor_contratado(self):
        return self._limpar_monetario("valor_contratado")

    def _limpar_monetario(self, campo):
        bruto = self.cleaned_data.get(campo, "")
        if not bruto:
            return None
        try:
            return Decimal(_normalizar_valor_monetario(str(bruto)))
        except InvalidOperation:
            raise forms.ValidationError("Informe um valor monetário válido.")

    def clean_mes_previsto(self):
        bruto = self.cleaned_data.get("mes_previsto")
        return int(bruto) if bruto else None

    def clean(self):
        cleaned = super().clean()
        # vigência final não pode ficar antes da inicial; os dois lados
        # chegam juntos num form inteiro
        inicio = cleaned.get("vigencia_inicio")
        fim = cleaned.get("vigencia_fim")
        if inicio and fim and fim < inicio:
            self.add_error(
                "vigencia_fim",
                "A vigência final não pode ser anterior à inicial.",
            )
        return cleaned


# texto de ajuda de "Novo prazo", decidido no servidor: três variantes
# escolhidas pela situação efetiva e sobreposição manual ativa do processo
AJUDA_NOVO_PRAZO_RESET = (
    "Passa a ser o Prazo atual. Se o processo estava Atrasado, volta a No prazo."
)
AJUDA_NOVO_PRAZO_ESTAVEL = "Passa a ser o Prazo atual; a situação não muda."
AJUDA_NOVO_PRAZO_MANUAL = (
    "Passa a ser o Prazo atual; a situação definida manualmente não muda."
)


def ajuda_novo_prazo(*, sobreposicao_manual_ativa, situacao_efetiva):
    """Com sobreposição manual ativa, avisa que a situação não muda. Sem
    ela, No prazo/Atrasado usa o texto de reset; Em tramitação/Concluído
    usa o texto estável."""
    if sobreposicao_manual_ativa:
        return AJUDA_NOVO_PRAZO_MANUAL
    if situacao_efetiva in (Situacao.NO_PRAZO, Situacao.ATRASADO):
        return AJUDA_NOVO_PRAZO_RESET
    return AJUDA_NOVO_PRAZO_ESTAVEL


class AcompanhamentoForm(forms.Form):
    """Único modal do sistema. Nunca muda situacao/estado: só grava um
    Acompanhamento novo."""

    prazo_prometido = forms.DateField(
        label=ROTULOS["prazo_prometido"],
        required=False,
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date", "col": "col-md-6"}
        ),
    )
    observacao = forms.CharField(
        label="Observação",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    justificativa = forms.CharField(
        label="Justificativa",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, ajuda_prazo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if ajuda_prazo:
            self.fields["prazo_prometido"].help_text = ajuda_prazo

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("prazo_prometido") and not cleaned.get("observacao"):
            raise forms.ValidationError(
                "Informe ao menos o prazo prometido ou uma observação."
            )
        return cleaned


class TransicaoForm(forms.Form):
    """Alterar situação como página própria."""

    destino = forms.ChoiceField(label="Nova situação", choices=Situacao.choices)
    justificativa = forms.CharField(
        label="Justificativa",
        required=True,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


# números SEI só mudam dentro do fieldset Processo, na mesma submissão do
# ProcessoForm. Duas linhas vazias para incluir, can_delete para excluir
ProcessoSEIFormSet = inlineformset_factory(
    Processo,
    ProcessoSEI,
    fields=("numero_sei",),
    extra=2,
    can_delete=True,
    labels={"numero_sei": "Nº do processo SEI"},
)
