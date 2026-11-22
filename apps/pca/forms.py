"""Contratos de formulário da Fase 26.

Substituíram a edição inline por campo (`editar_campo_view`, apagada no Plano
26-06) e os 3 modais de webcomponents do processo por páginas
próprias no padrão `telas/detalhe.md`/`telas/formulario.md` do padrão DSGov:
`ProcessoForm` (criar/editar, `processo_formulario.html`), `AcompanhamentoForm`
(único modal do sistema) e `TransicaoForm` (alterar situação como
página).

`CAMPOS_EDITAVEIS_PROCESSO` (a fronteira de confiança, única tupla
desde que `editar_campo_view`/`CAMPOS_EDITAVEIS_TABELA` saíram) e
`_normalizar_valor_monetario` continuam definidos em `apps/pca/views.py` e são
só IMPORTADOS de volta aqui, para não duplicar a allowlist nem os dois
formatos de valor monetário aceitos (decisão do executor, do Plano
26-02: promover a tupla para cá exigiria `views.py` importar de `forms.py`,
que por sua vez precisaria importar `views.py` para as demais funções de
apoio — import circular. Importar só nesta direção evita o ciclo).
"""

from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from apps.pca.filtros import MESES, NOMES_MES
from apps.pca.models import Estado, Processo, ProcessoSEI, Situacao
from apps.pca.rotulos import ROTULOS


def _campos_processo_form():
    """Import tardio (evita ciclo: `views.py` importa `forms.py` para os 3
    contratos abaixo; `forms.py` importa de volta só estas duas constantes)."""
    from apps.pca.views import CAMPOS_EDITAVEIS_PROCESSO

    return CAMPOS_EDITAVEIS_PROCESSO


def _normalizar_valor_monetario(bruto):
    from apps.pca.views import _normalizar_valor_monetario as normalizar

    return normalizar(bruto)


def _valor_monetario_formato_valido(normalizado):
    from apps.pca.views import _valor_monetario_formato_valido as valido

    return valido(normalizado)


# Campos que ganham `col-md-6` no renderer (contrato de `django.md`: "col-12"
# é o padrão, "col-md-6" para números, datas e booleanos).
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
    # Fase 36 — número e booleano ganham col-md-6,
    # mesma convenção de vigencia_inicio/vigencia_fim acima;
    # `regime_execucao` fica FORA (select de poucas opções, col-12 padrão,
    # mesmo tratamento de modalidade/instrumento_contratual).
    "valor_mensal",
    "renovacao_prevista",
}

# Os dois campos monetários aceitam tanto a forma crua (`35000.00`) quanto a
# mascarada pt-BR (`35.000,00`, Decisão 3/`_normalizar_valor_monetario`). Um
# `DecimalField` nativo rejeitaria a vírgula ANTES de `clean_<campo>` rodar
# (Django só chama `clean_<nome>` depois de `field.clean()` ter aceitado o
# valor) — por isso os dois nascem `CharField` aqui, e a conversão para
# `Decimal` acontece inteiramente em `_limpar_monetario`.
_CAMPOS_MONETARIOS = ("valor_estimado", "valor_contratado", "valor_mensal")

# 4 campos mínimos de criação (mesma allowlist de `criar_processo_view` antes
# deste plano) — os únicos que `ProcessoForm(criando=True)` mantém.
CAMPOS_CRIACAO_PROCESSO = (
    "descricao_objeto",
    "tipo",
    "categoria",
    "unidade_organizacional",
)


class ProcessoForm(forms.ModelForm):
    """Criar e editar um processo — `processo_formulario.html`.

    `Meta.fields` é `CAMPOS_EDITAVEIS_PROCESSO`, a MESMA fronteira de confiança
    usada pela edição inline: nenhum campo fora dela (`estado`,
    `situacao`) fica postável por este form. Na criação (`criando=True`), só os
    4 campos de `CAMPOS_CRIACAO_PROCESSO` sobrevivem em `self.fields`.
    """

    class Meta:
        model = Processo
        fields = _campos_processo_form()
        widgets = {
            "justificativa": forms.Textarea(attrs={"rows": 3}),
        }
        # "Prazo inicial" (`ROTULOS`, fonte
        # única); `verbose_name` do model ("Data prevista para entrega")
        # permanece intocado, zero migração.
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

    def clean_valor_mensal(self):
        return self._limpar_monetario("valor_mensal")

    def _limpar_monetario(self, campo):
        # QA 30/09/2026 (fuzz M4/domínio nº8) — formato estrito ANTES de
        # `Decimal()`: negativo/notação científica/`_`/dígito não ASCII são
        # recusados aqui, nunca gravados. `valor_estimado` exige > 0
        # quando informado; `valor_contratado`/`valor_mensal` aceitam 0.
        bruto = self.cleaned_data.get(campo, "")
        if not bruto:
            return None
        normalizado = _normalizar_valor_monetario(str(bruto))
        if not _valor_monetario_formato_valido(normalizado):
            raise forms.ValidationError("Informe um valor monetário válido.")
        valor = Decimal(normalizado)
        minimo = Decimal("0.01") if campo == "valor_estimado" else Decimal("0")
        if valor < minimo:
            raise forms.ValidationError("Informe um valor monetário válido.")
        return valor

    def clean_mes_previsto(self):
        bruto = self.cleaned_data.get("mes_previsto")
        return int(bruto) if bruto else None

    def clean(self):
        cleaned = super().clean()
        # QA 30/09/2026 (dados M9) — texto colado com caractere de
        # controle (\x0b, \x0c etc.) é removido ANTES de gravar; nunca
        # impede salvar o processo.
        for nome, valor in list(cleaned.items()):
            if isinstance(valor, str) and valor:
                limpo = ILLEGAL_CHARACTERS_RE.sub("", valor)
                if limpo != valor:
                    cleaned[nome] = limpo
        # (preservado de `editar_processo_view`/`editar_campo_view`) — a
        # vigência final não pode ficar antes da inicial; os dois lados
        # chegam JUNTOS num form inteiro, então a checagem usa os valores
        # finais da mesma submissão.
        inicio = cleaned.get("vigencia_inicio")
        fim = cleaned.get("vigencia_fim")
        if inicio and fim and fim < inicio:
            self.add_error(
                "vigencia_fim",
                "A vigência final não pode ser anterior à inicial.",
            )
        return cleaned


# Texto de ajuda de "Novo prazo", decidido no servidor
# (nunca por JS): três variantes fechadas, escolhidas por `ajuda_novo_prazo`
# a partir da situação efetiva e da sobreposição manual ativa do processo
# (as mesmas anotações de `ProcessoQuerySet.para_listagem()`).
AJUDA_NOVO_PRAZO_RESET = (
    "Passa a ser o Prazo atual. Se o processo estava Atrasado, volta a No prazo."
)
AJUDA_NOVO_PRAZO_ESTAVEL = "Passa a ser o Prazo atual; a situação não muda."
AJUDA_NOVO_PRAZO_MANUAL = (
    "Passa a ser o Prazo atual; a situação definida manualmente não muda."
)


def ajuda_novo_prazo(*, sobreposicao_manual_ativa, situacao_efetiva):
    """prevalece sobre quando há sobreposição manual ativa:
    o texto avisa que a situação definida manualmente não muda, mesmo em
    No prazo/Atrasado. Sem sobreposição manual, No prazo/Atrasado usa o
    texto de reset; Em tramitação/Concluído usa o texto estável
    (prazo novo nunca tira o processo desses dois estados)."""
    if sobreposicao_manual_ativa:
        return AJUDA_NOVO_PRAZO_MANUAL
    if situacao_efetiva in (Situacao.NO_PRAZO, Situacao.ATRASADO):
        return AJUDA_NOVO_PRAZO_RESET
    return AJUDA_NOVO_PRAZO_ESTAVEL


class AcompanhamentoForm(forms.Form):
    """Único modal do sistema — `_acompanhamento_modal.html`.

    Nunca muda `situacao`/`estado` (fronteira intocada): só grava um
    `Acompanhamento` novo via `services.registrar_acompanhamento(situacao_novo=
    None, ...)`.
    """

    prazo_prometido = forms.DateField(
        label=ROTULOS["prazo_prometido"],
        required=False,
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date", "col": "col-md-4"}
        ),
    )
    observacao = forms.CharField(
        label="Observação",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "col": "col-md-4"}),
        # Padrão de escrita, fixo: um fato por
        # frase, com a fonte, sem repetir a situação do item (já visível
        # noutra coluna da tabela).
        help_text=(
            "Um fato por frase, com a fonte: “Valor estimado alterado de "
            "R$ 120.000,00 para R$ 148.500,00, conforme pesquisa de preços "
            "(doc. 1493632).” Não repita a situação do item."
        ),
    )
    justificativa = forms.CharField(
        label="Justificativa",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "col": "col-md-4"}),
        # Só o porquê, em minúscula e sem ponto
        # final, porque entra na frase institucional "Justificativa: ___."
        # (`apps.pca.relatorio_movimentacao.frase_compromisso`).
        help_text=(
            "Só o porquê do prazo, em minúscula e sem ponto final — ela entra "
            "na frase “Justificativa: ___.” Ex.: aguardando "
            "manifestação da Projur sobre a minuta."
        ),
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
    """Alterar situação como página — `processo_transicao.html`."""

    destino = forms.ChoiceField(label="Nova situação", choices=Situacao.choices)
    justificativa = forms.CharField(
        label="Justificativa",
        required=True,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


# `NumeroSeiForm` (a linha do formulário
# "Adicionar" avulso da antiga seção Números SEI do detalhe) saiu junto com
# `pca:adicionar_sei`/`pca:remover_sei`: números SEI só mudam dentro do
# fieldset Processo de `processo_formulario.html`, na mesma submissão e
# transação do `ProcessoForm` (`telas/formulario.md` § "Registros filhos
# 1:N"). Duas linhas vazias para incluir, `can_delete=True` para excluir; a
# unicidade `ProcessoSEI.unique_together` é validada pelo próprio formset.
ProcessoSEIFormSet = inlineformset_factory(
    Processo,
    ProcessoSEI,
    fields=("numero_sei",),
    extra=2,
    can_delete=True,
    labels={"numero_sei": "Nº do processo SEI"},
)
