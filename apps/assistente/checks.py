"""Checks de configuração do Assistente do PCA (A20, spec §2).

Nunca abrem arquivo, nunca acessam rede, nunca exigem `IA_API_KEY` — rodam
limpos em `manage.py check`, na suíte e no `collectstatic` mesmo sem
chave. `Path(...).resolve(strict=False)` compara caminhos sem tocar o
disco (arquivo pode não existir ainda — nasce preguiçosamente em
`estado.py`). `IA_PROVEDOR` agora admite `openai`/
`anthropic` (E003 ampliado); E005/E006 são novos e validam
`IA_PROVEDOR_EMBED`/`IA_API_KEY_EMBED` (embeddings continuam exclusivos da
OpenAI)."""

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, register


@register("assistente")
def verificar_configuracao(app_configs, **kwargs):
    erros = []

    limites = {
        "IA_MAX_PERGUNTAS_DIA": settings.IA_MAX_PERGUNTAS_DIA,
        "IA_CONVERSA_TTL_S": settings.IA_CONVERSA_TTL_S,
        "IA_MAX_TOKENS_RESPOSTA": settings.IA_MAX_TOKENS_RESPOSTA,
        "IA_TIMEOUT_S": settings.IA_TIMEOUT_S,
        "IA_PRAZO_PERGUNTA_S": settings.IA_PRAZO_PERGUNTA_S,
    }
    invalidos = [nome for nome, valor in limites.items() if valor <= 0]
    if invalidos:
        erros.append(
            Error(
                "Limites do assistente devem ser positivos: "
                + ", ".join(sorted(invalidos)),
                id="assistente.E001",
            )
        )

    caminhos = {
        "IA_INDICE_PATH": settings.IA_INDICE_PATH,
        "IA_ESTADO_PATH": settings.IA_ESTADO_PATH,
        "IA_CONVERSAS_PATH": settings.IA_CONVERSAS_PATH,
    }
    resolvidos = {
        nome: Path(str(valor)).resolve(strict=False)
        for nome, valor in caminhos.items()
    }
    banco = Path(str(settings.DATABASES["default"]["NAME"])).resolve(strict=False)
    valores_resolvidos = list(resolvidos.values())
    colisao = len(set(valores_resolvidos)) != len(valores_resolvidos) or any(
        caminho == banco for caminho in valores_resolvidos
    )
    if colisao:
        erros.append(
            Error(
                "IA_INDICE_PATH, IA_ESTADO_PATH e IA_CONVERSAS_PATH precisam "
                "ser distintos entre si e do banco de dados principal.",
                id="assistente.E002",
            )
        )

    if settings.IA_PROVEDOR not in ("openai", "anthropic"):
        erros.append(
            Error(
                "IA_PROVEDOR só admite 'openai' ou 'anthropic'.",
                id="assistente.E003",
            )
        )

    if settings.IA_API_KEY and (
        not settings.IA_MODELO_ASSISTENTE or not settings.IA_MODELO_EMBED
    ):
        erros.append(
            Error(
                "Com IA_API_KEY preenchida, IA_MODELO_ASSISTENTE e "
                "IA_MODELO_EMBED não podem ficar vazios.",
                id="assistente.E004",
            )
        )

    if settings.IA_PROVEDOR_EMBED != "openai":
        erros.append(
            Error(
                "IA_PROVEDOR_EMBED só admite 'openai' — a Anthropic não tem "
                "API de embeddings.",
                id="assistente.E005",
            )
        )

    if (
        settings.IA_API_KEY
        and settings.IA_PROVEDOR != settings.IA_PROVEDOR_EMBED
        and not settings.IA_API_KEY_EMBED
    ):
        erros.append(
            Error(
                "Com IA_PROVEDOR diferente de IA_PROVEDOR_EMBED, "
                "IA_API_KEY_EMBED não pode ficar vazio — a chave de chat "
                "seria usada no provedor de embeddings errado.",
                id="assistente.E006",
            )
        )

    return erros
