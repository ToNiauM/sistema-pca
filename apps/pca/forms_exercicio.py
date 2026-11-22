"""Contratos de formulário da Fase 26.

`ViradaItemForm` substitui a edição POR CAMPO (`virada_campo_view`, edição
inline) pela etapa "Ajustar" do wizard de virada — mesmo tratamento de
campo monetário de `apps/pca/forms.py::ProcessoForm` (`CharField` +
`clean_*` chamando `_normalizar_valor_monetario`, nunca um `DecimalField`
nativo, que rejeitaria a vírgula pt-BR antes de `clean_<campo>` rodar).

`ReuniaoForm` dá à criação de reunião o lugar canônico que faltava
— a rota existia, mas o template `_form_criar_reuniao.html` nunca existiu no
repositório (achado registrado). `exercicio` fica de fora
dos campos do form: `services.criar_reuniao` sempre resolve o exercício
ABERTO em foco, nunca o ano cru de um `<select>` do formulário (mesma
disciplina de `criar_reuniao_view`, que já ignorava esse retorno antes deste
plano).
"""

from decimal import Decimal

from django import forms

from apps.pca.filtros import MESES, NOMES_MES
from apps.pca.models import RascunhoItemVirada, Reuniao, SituacaoReuniao


def _normalizar_valor_monetario(bruto):
    # Import tardio — mesmo padrão de `apps/pca/forms.py::_normalizar_valor_monetario`:
    # evita `views.py` precisar importar `forms_exercicio.py` de volta.
    from apps.pca.views import _normalizar_valor_monetario as normalizar

    return normalizar(bruto)


def _valor_monetario_formato_valido(normalizado):
    from apps.pca.views import _valor_monetario_formato_valido as valido

    return valido(normalizado)


class ViradaItemForm(forms.ModelForm):
    """Etapa "Ajustar" do wizard de virada — `virada_item_formulario.html`.

    `Meta.fields` restrito aos 2 campos editáveis do rascunho:
    nunca aceita `selecionado` nem `processo_origem`.
    """

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
        # QA 30/09/2026 (fuzz M4/domínio nº8) — mesmo formato estrito do
        # cadastro (`ProcessoForm._limpar_monetario`): negativo/notação
        # científica/`_`/dígito não ASCII nunca gravam; estimado exige > 0
        # quando informado.
        bruto = self.cleaned_data.get("valor_estimado_editado", "")
        if not bruto:
            return None
        normalizado = _normalizar_valor_monetario(str(bruto))
        if not _valor_monetario_formato_valido(normalizado):
            raise forms.ValidationError("Informe um valor monetário válido.")
        valor = Decimal(normalizado)
        if valor < Decimal("0.01"):
            raise forms.ValidationError("Informe um valor monetário válido.")
        return valor

    def clean_mes_previsto_editado(self):
        valor = self.cleaned_data.get("mes_previsto_editado")
        return int(valor) if valor else None


class ReuniaoForm(forms.ModelForm):
    """Criar uma reunião — `reuniao_formulario.html`.

    `exercicio` não é campo do form (resolvido por `services.criar_reuniao`,
    sempre o exercício ABERTO em foco); `situacao` nasce ABERTA por padrão,
    mas continua editável (ex.: registrar uma reunião já fechada).
    """

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
        # O modelo já tem `default=SituacaoReuniao.ABERTA` — o form só
        # precisa deixar de EXIGIR o campo (om undo omitido no POST cai no
        # default do model), não reimplementar o valor padrão.
        self.fields["situacao"].required = False
        if not self.initial.get("situacao"):
            self.fields["situacao"].initial = SituacaoReuniao.ABERTA

    def clean_situacao(self):
        return self.cleaned_data.get("situacao") or SituacaoReuniao.ABERTA
