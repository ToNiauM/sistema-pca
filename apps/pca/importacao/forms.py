"""Formulários da importação administrativa da planilha."""

from pathlib import Path
import re

from django import forms

from apps.catalogo.models import Exercicio


EXTENSAO_PERMITIDA = ".xlsx"
TAMANHO_MAXIMO_MB = 10
TAMANHO_MAXIMO_BYTES = TAMANHO_MAXIMO_MB * 1024 * 1024


def _nome_arquivo_seguro(nome_arquivo):
    """Remove diretórios enviados pelo cliente antes de reutilizar o nome."""
    return Path(nome_arquivo).name


def _validar_nome_e_tamanho(nome_arquivo, tamanho):
    nome_seguro = _nome_arquivo_seguro(nome_arquivo)
    if not nome_seguro.lower().endswith(EXTENSAO_PERMITIDA):
        raise forms.ValidationError("Envie um arquivo .xlsx.")
    if tamanho > TAMANHO_MAXIMO_BYTES:
        raise forms.ValidationError(
            f"O arquivo deve ter no máximo {TAMANHO_MAXIMO_MB} MB."
        )
    return nome_seguro


class UploadPlanilhaForm(forms.Form):
    # accept é só dica de navegador; a validação real é _validar_nome_e_tamanho
    arquivo = forms.FileField(
        label="Planilha .xlsx", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"})
    )
    exercicio = forms.ModelChoiceField(
        label="Exercício de destino", queryset=Exercicio.objects.all()
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        _validar_nome_e_tamanho(arquivo.name, arquivo.size)
        return arquivo


class ConfirmarImportacaoForm(forms.Form):
    """Confirma somente uma referência opaca; os metadados ficam no servidor."""

    referencia = forms.RegexField(
        regex=re.compile(r"^[A-Za-z0-9_-]{43}$"),
        max_length=43,
        min_length=43,
        widget=forms.HiddenInput,
    )
