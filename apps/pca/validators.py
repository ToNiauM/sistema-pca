"""Validadores do bloco de execução contratual. CNPJ é aritmética de
domínio público (checksum módulo-11 da Receita Federal), sem dependência
externa."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

validar_formato_cnpj = RegexValidator(
    regex=r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$",
    message="Informe um valor válido.",
)


def validar_digitos_cnpj(valor):
    """Checksum módulo-11 padrão da Receita Federal — sem dependência externa."""
    digitos = re.sub(r"\D", "", valor or "")
    if len(digitos) != 14:
        raise ValidationError("Informe um valor válido.")
    if len(set(digitos)) == 1:
        raise ValidationError("Informe um valor válido.")

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def dv(nums, pesos):
        soma = sum(int(n) * p for n, p in zip(nums, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    dv1 = dv(digitos[:12], pesos1)
    dv2 = dv(digitos[:12] + dv1, pesos2)
    if digitos[12] != dv1 or digitos[13] != dv2:
        raise ValidationError("Informe um valor válido.")
