"""Fila própria de reindexação do Assistente do PCA (A14) —
`data/ia/pedidos/`, consumida pelo laço permanente do robô
(`apps.pca.management.commands.sei_atender.atender_um_passo`) SÓ quando
NÃO há pedido SEI pendente (prioridade SEI garantida por construção, não
por prioridade explícita entre filas). Espelha o padrão de
`apps.pca.sei.execucoes` (fila SEI/`gravar_pedido`/`listar_pedidos`/
`mover_pedido_para_atendidos`), mas em outro diretório e SEM reutilizar
suas funções (A14) — a fila SEI exige `item_pca`/`exercicio`; um pedido de
reindexação não tem (nem deve ter) nenhum dos dois.

Estados: `pendente` -> `executando` -> `concluido` | `erro`. O `flock`
exclusivo não bloqueante de `apps.assistente.indice.indexar` já É o lock
de indexação — separado do lock SEI (`data/sei/em_execucao`); esta fila
não precisa (e não deve) implementar um lock próprio.

`consumir_um_pedido` NUNCA propaga exceção — o laço do robô não pode cair
por causa de uma indexação com problema (03). Nenhum nome/e-mail
do solicitante é gravado, só o `pk` (04); nenhuma mensagem de
mensagem crua da exceção chega ao JSON do pedido nem ao log — só o
nome da classe da exceção."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.assistente import cliente as cliente_mod
from apps.assistente import indice


def diretorio_pedidos() -> Path:
    """`<diretório do estado>/pedidos/` — nasce preguiçosamente com
    permissões restritas, mesmo padrão dos demais diretórios auxiliares do
    assistente."""
    caminho = Path(settings.IA_ESTADO_PATH).parent / "pedidos"
    caminho.mkdir(parents=True, exist_ok=True, mode=0o700)
    return caminho


def _logar(stdout, mensagem: str) -> None:
    """Mesmo padrão de `apps.pca.management.commands.sei_atender._logar`
    — sem `stdout` (chamada direta de teste), não loga nada."""
    if stdout is None:
        return
    stdout.write(mensagem)
    stdout.flush()


def gravar_pedido_reindexacao(*, solicitado_por: int, completo: bool = False, agora) -> Path:
    """Grava um pedido `pendente`. `solicitado_por` é só o `pk` do
    usuário — nunca nome/e-mail (04)."""
    dados = {
        "tipo": "reindexar",
        "completo": bool(completo),
        "solicitado_por": solicitado_por,
        "solicitado_em": agora.isoformat(),
        "estado": "pendente",
    }
    carimbo = agora.strftime("%Y-%m-%d-%H%M%S")
    token = secrets.token_hex(4)
    caminho = diretorio_pedidos() / f"{carimbo}-{token}.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def listar_pedidos() -> list[dict]:
    """Só pedidos `estado == "pendente"`, ordenados por `solicitado_em`.
    Arquivo ilegível/corrompido é silenciosamente ignorado — nunca derruba
    o laço por causa de um JSON malformado."""
    pasta = diretorio_pedidos()
    pedidos = []
    for arquivo in pasta.glob("*.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if dados.get("estado") != "pendente":
            continue
        dados["_arquivo"] = arquivo
        pedidos.append(dados)
    pedidos.sort(key=lambda pedido: pedido["solicitado_em"])
    return pedidos


def _marcar(pedido: dict, novo_estado: str, **extras) -> None:
    """Reescreve o JSON do pedido a partir dos campos originais (exceto o
    marcador interno `_arquivo`) + o novo estado + os `extras` da
    transição (ver docstring do módulo para o que cada estado grava)."""
    arquivo = Path(pedido["_arquivo"])
    dados = {chave: valor for chave, valor in pedido.items() if chave != "_arquivo"}
    dados["estado"] = novo_estado
    dados.update(extras)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def descartar_vencidos(limite_horas: float = 6) -> list[dict]:
    """Marca como `erro`/`vencido` pedidos `pendente` mais antigos que
    `limite_horas` (proteção contra um pedido preso monopolizar a
    prioridade de reindexação indefinidamente)."""
    limite = timedelta(hours=limite_horas)
    agora = timezone.now()
    descartados = []
    for pedido in listar_pedidos():
        solicitado_em = datetime.fromisoformat(pedido["solicitado_em"])
        if agora - solicitado_em > limite:
            _marcar(pedido, "erro", erro_codigo="vencido", concluido_em=agora.isoformat())
            descartados.append(pedido)
    return descartados


def aplicar_retencao(manter: int = 30) -> int:
    """Mantém só os `manter` pedidos `concluido`/`erro` mais recentes
    (pelo nome do arquivo, que começa pelo carimbo) — mesmo espírito de
    `apps.pca.sei.execucoes.aplicar_retencao`, sem reutilizar a função
    (diretório/formato diferentes)."""
    pasta = diretorio_pedidos()
    terminais = []
    for arquivo in pasta.glob("*.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if dados.get("estado") in ("concluido", "erro"):
            terminais.append(arquivo)
    terminais.sort(key=lambda arquivo: arquivo.name, reverse=True)
    excedentes = terminais[manter:]
    for arquivo in excedentes:
        arquivo.unlink(missing_ok=True)
    return len(excedentes)


def consumir_um_pedido(*, agora, cliente_fabrica=None, indexar=None, stdout=None) -> dict | None:
    """Atende no máximo UM pedido `pendente`, o mais antigo primeiro.
    Chamada por `sei_atender.atender_um_passo` só quando não há pedido SEI
    (prioridade SEI por construção). `cliente_fabrica`/`indexar` são
    `None` por padrão e resolvidos aqui dentro (não como valor-padrão do
    parâmetro) para que `unittest.mock.patch("apps.assistente.fila.
    indice.indexar")`/`patch("apps.assistente.cliente.criar_cliente")`
    continuem funcionando quando o chamador não passa nada (padrão de
    produção) — um valor-padrão fixado na assinatura seria resolvido na
    importação do módulo, antes de qualquer `patch` de teste.

    NUNCA propaga exceção (03): `IndiceOcupado` devolve o pedido a
    `pendente` (outra indexação em curso — o `flock` de `indice.indexar`
    já é o lock separado do lock SEI); qualquer outra exceção marca `erro`
    com o nome da classe da exceção, nunca a mensagem crua (04)."""
    if cliente_fabrica is None:
        cliente_fabrica = cliente_mod.criar_cliente
    if indexar is None:
        indexar = indice.indexar

    descartar_vencidos()
    pedidos = listar_pedidos()
    if not pedidos:
        return None
    pedido = pedidos[0]

    cliente = cliente_fabrica()
    if cliente is None:
        _marcar(pedido, "erro", erro_codigo="sem_chave", concluido_em=agora.isoformat())
        _logar(stdout, "reindexação: IA_API_KEY ausente, pedido marcado erro")
        return {"status": "erro", "motivo": "sem_chave"}

    _marcar(pedido, "executando", iniciado_em=agora.isoformat())

    try:
        resumo = indexar(cliente, completo=bool(pedido.get("completo")), agora=agora, stdout=stdout)
    except indice.IndiceOcupado:
        _marcar(pedido, "pendente")
        _logar(stdout, "reindexação: índice ocupado, pedido permanece pendente")
        return {"status": "aguardando_lock_indice"}
    except Exception as exc:  # noqa: BLE001 — nunca derruba o laço do robô
        _marcar(
            pedido,
            "erro",
            erro_codigo=type(exc).__name__,
            concluido_em=timezone.now().isoformat(),
        )
        _logar(stdout, f"reindexação: erro ({type(exc).__name__})")
        return {"status": "erro"}

    _marcar(
        pedido,
        "concluido",
        concluido_em=timezone.now().isoformat(),
        geracao=resumo.geracao,
        novos=resumo.novos,
        reaproveitados=resumo.reaproveitados,
        removidos=resumo.removidos,
        tokens=resumo.tokens,
    )
    _logar(
        stdout,
        f"reindexação: concluída (geração {resumo.geracao}, novos {resumo.novos}, "
        f"reaproveitados {resumo.reaproveitados}, removidos {resumo.removidos})",
    )
    return {"status": "ok", "geracao": resumo.geracao}
