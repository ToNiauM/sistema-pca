"""Contratos de formulário: `ViradaItemForm` (etapa "Ajustar" do wizard de
virada, mesmo tratamento de campo monetário de forms.py::ProcessoForm) e
`ReuniaoForm` (criação de reunião; exercicio fica de fora dos campos, sempre
resolvido para o exercício aberto em foco)."""

from decimal import Decimal, InvalidOperation

from django import forms

from apps.pca.filtros import MESES, NOMES_MES
from apps.pca.models import RascunhoItemVirada, Reuniao, SituacaoReuniao


def _normalizar_valor_monetario(bruto):
    # import tardio: evita views.py precisar importar forms_exercicio.py de volta
    from apps.pca.views import _normalizar_valor_monetario as normalizar

    return normalizar(bruto)


class ViradaItemForm(forms.ModelForm):
    """Etapa "Ajustar" do wizard de virada. Meta.fields restrito aos 2
    campos editáveis do rascunho; nunca aceita selecionado/processo_origem."""

    class Meta:
        model = RascunhoItemVirada
        fields = ["mes_previsto_editado", "valor_estimado_editado"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["valor_estimado_editado"] = forms.CharField(
            label=self.fields["valor_estimado_editado"].label,
            required=False,
        )
        self.fields["mes_previsto_editado"] = forms.ChoiceField(
            label=self.fields["mes_previsto_editado"].label,
            required=False,
            choices=[("", "---------")]
            + [(numero, NOMES_MES[numero]) for numero in MESES],
            widget=forms.Select(attrs={"col": "col-md-6"}),
        )
        self.fields["valor_estimado_editado"].widget.attrs["col"] = "col-md-6"

    def clean_valor_estimado_editado(self):
        bruto = self.cleaned_data.get("valor_estimado_editado", "")
        if not bruto:
            return None
        try:
            return Decimal(_normalizar_valor_monetario(str(bruto)))
        except (InvalidOperation, ValueError):
            raise forms.ValidationError("Informe um valor monetário válido.")

    def clean_mes_previsto_editado(self):
        valor = self.cleaned_data.get("mes_previsto_editado")
        return int(valor) if valor else None


class ReuniaoForm(forms.ModelForm):
    """Criar uma reunião. exercicio não é campo do form (sempre resolvido
    para o exercício aberto em foco); situacao nasce ABERTA mas continua
    editável."""

    class Meta:
        model = Reuniao
        fields = ["data", "situacao"]
        widgets = {
            "data": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data"].widget.attrs["col"] = "col-md-6"
        self.fields["situacao"].widget.attrs["col"] = "col-md-6"
        # o modelo já tem default=SituacaoReuniao.ABERTA; o form só precisa
        # deixar de exigir o campo, não reimplementar o valor padrão
        self.fields["situacao"].required = False
        if not self.initial.get("situacao"):
            self.fields["situacao"].initial = SituacaoReuniao.ABERTA

    def clean_situacao(self):
        return self.cleaned_data.get("situacao") or SituacaoReuniao.ABERTA
