import unicodedata


def normalizar_nome(nome: str) -> str:
    """Normaliza para chave de casamento do import: sem acento, caixa baixa, sem espaços nas pontas. `Água` -> `agua`."""
    return (
        unicodedata.normalize("NFKD", nome or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )
