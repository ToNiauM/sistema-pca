"""Harvesting de hiperlinks SEI a partir de um envelope de coleta (quick). Módulo PURO — sem Playwright, sem ORM (só `django.utils.timezone`
para o carimbo, mesma tolerância de `apps.pca.sei.coletor`) — importável no
container `web`, que nunca tem Playwright instalado.
"""

from __future__ import annotations

from django.utils import timezone


def atualizar_de_coleta(links: dict, dados_coleta: dict) -> dict:
    """Muta `links` (formato de `execucoes.ler_links()`) por referência a
    partir de `dados_coleta` (envelope de `coletor.coletar()`/
    `coletor.resolver_links()`) e devolve o mesmo dict — quem grava em disco
    é sempre o chamador, mesmo padrão de `coletor.coletar()`.

    Para cada item de `dados_coleta["processos"]`: sem `numero`, pula (nunca
    quebra o laço). `resultado == "nao_encontrado"` grava `nao_encontrado:
    True` sem `id_procedimento`. Com `abertura.id_procedimento`, grava o link
    resolvido. Documentos contratuais com `protocolo` e `id_documento`
    grafam `links["documentos"][protocolo]`.
    """
    agora = timezone.localtime().isoformat()
    processos = links.setdefault("processos", {})
    documentos = links.setdefault("documentos", {})

    for processo in dados_coleta.get("processos", []) or []:
        numero = processo.get("numero")
        if not numero:
            continue

        if processo.get("resultado") == "nao_encontrado":
            processos[numero] = {"nao_encontrado": True, "resolvido_em": agora}
        else:
            id_procedimento = (processo.get("abertura") or {}).get("id_procedimento")
            if id_procedimento:
                processos[numero] = {
                    "id_procedimento": id_procedimento,
                    "nao_encontrado": False,
                    "resolvido_em": agora,
                }

        for doc in processo.get("documentos_contratuais") or []:
            protocolo = doc.get("protocolo")
            id_documento = doc.get("id_documento")
            if protocolo and id_documento:
                documentos[protocolo] = {"id_documento": id_documento, "numero_sei": numero}

    return links
