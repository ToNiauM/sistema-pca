import unicodedata


def normalizar_nome(nome: str) -> str:
    """Chave de casamento do upsert de re-import: sem acento, caixa
    baixa, sem espaços nas pontas. `Água` -> `agua`, `Ação` -> `acao`.

    Usada pelo `save()` de `DominioBase` e reaproveitada pelo import (01-04)
    para casar o rótulo da planilha com o registro já existente sem nunca
    apagar o que nasceu no Admin. Extraída para cá (em vez de ficar dentro de
    `models.py`) para que o comando de import possa reaproveitá-la sem
    importar `apps.catalogo.models`.
    """
    return (
        unicodedata.normalize("NFKD", nome or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )
