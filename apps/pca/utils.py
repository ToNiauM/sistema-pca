import hashlib
from datetime import date


def calcular_origem_hash(
    exercicio_ano: int,
    processo_numero: int,
    data_reuniao: date,
    situacao_informada: str,
) -> str:
    """Chave natural do Acompanhamento para idempotência do re-import.
    Deriva do exercício + processo + data da reunião + texto literal
    declarado, para que o mesmo item possa reaparecer em exercícios
    diferentes sem colidir no histórico."""
    bruto = (
        f"{exercicio_ano}|{processo_numero}|{data_reuniao.isoformat()}|"
        f"{(situacao_informada or '').strip()}"
    )
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
