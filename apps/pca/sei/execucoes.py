"""I/O de arquivo do robô SEI (Fase 32).

Grava e lê `data/sei/{coletas,execucoes}/<carimbo>.json`, `data/sei/
estado.json` (pendências já avisadas), o lock `data/sei/em_execucao`, a
fila de pedidos sob demanda `data/sei/pedidos/` (base, §3.7) e
`data/sei/ultima_consulta.json`. Sem migração — nenhum destes
arquivos é schema de banco.

O lock `em_execucao` vira também o canal de progresso ao
vivo da varredura (`atualizar_progresso`/`ler_progresso`) — o `docker
compose exec` do cron é o único lugar onde `sei_sincronizar` imprime linha
a linha, então o card "Sincronização com o SEI" do Início lê
direto do lock em vez de `docker compose logs -f robo`. Cada execução
também grava um log próprio (`abrir_log_execucao`), pareado por carimbo com
o `.json` de `execucoes/` na mesma retenção de 60.

Não é módulo puro: importa `django.conf.settings` para ler `SEI_DATA_DIR`/
`BASE_DIR`, mas não faz nenhuma query ORM. `diretorio_base()` NUNCA assume
que `settings.SEI_DATA_DIR` já foi declarado — o plano (que declara
essa setting) roda na mesma wave/paralelo a este módulo.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

logger = logging.getLogger(__name__)

_RE_LINHA_PROGRESSO = re.compile(
    r"^item (?P<item>\d+) \((?P<k>\d+)/(?P<total>\d+)\): (?P<resto>.*)$"
)

# Lote 6 do QA 30/09/2026 (achado dados A3) — chave composta ano-item de
# `estado.json`/`ultima_consulta.json`/`resumo["series"]`: com dois
# `Exercicio` ABERTOS ao mesmo tempo ("Gerar itens de N+1"), a chave antiga
# (só o nº do item) podia misturar os dois ciclos. `RE_CHAVE_ITEM` casa o
# formato novo ("<exercicio>-<item>"); `EXERCICIO_CHAVES_ANTIGAS` é o único
# exercício aberto quando os arquivos de produção foram gerados, antes desta
# correção — usada só para retrocompatibilidade de LEITURA, nunca de escrita.
RE_CHAVE_ITEM = re.compile(r"^(?P<exercicio>\d{4})-(?P<item>\d+)$")
EXERCICIO_CHAVES_ANTIGAS = 2026


def chave_item(item_pca: int, exercicio: int) -> str:
    return f"{exercicio}-{item_pca}"


def decompor_chave_item(chave: str) -> tuple[int, int]:
    m = RE_CHAVE_ITEM.match(chave)
    if not m:
        raise ValueError(f"chave fora do formato '<exercicio>-<item>': {chave!r}")
    return int(m.group("item")), int(m.group("exercicio"))


def _migrar_chaves_antigas(dados: dict) -> dict:
    """Retrocompatibilidade de leitura (achado dados A3): um `estado.json`/
    `ultima_consulta.json` gravado em produção ANTES desta correção tem
    chaves só com o nº do item ("3"); reinterpreta cada uma dessas como
    `EXERCICIO_CHAVES_ANTIGAS` (2026, único exercício aberto na época).
    Chave já no formato novo passa direto; qualquer outra coisa (nunca deve
    acontecer, mas não lança) também passa direto."""
    migrado = {}
    for chave, valor in dados.items():
        if RE_CHAVE_ITEM.match(chave):
            migrado[chave] = valor
        elif chave.isdigit():
            migrado[chave_item(int(chave), EXERCICIO_CHAVES_ANTIGAS)] = valor
        else:
            migrado[chave] = valor
    return migrado


def diretorio_base() -> Path:
    base = getattr(settings, "SEI_DATA_DIR", None)
    if base:
        return Path(base)
    return Path(settings.BASE_DIR) / "data" / "sei"


def novo_carimbo() -> str:
    return timezone.localtime().strftime("%Y-%m-%d-%H%M")


def _gravar_json(caminho: Path, dados: dict) -> Path:
    """Escrita atômica (achado dados M7, QA 30/09/2026): serializa para um
    arquivo TEMPORÁRIO no MESMO diretório (`os.replace` só é atômico dentro
    do mesmo filesystem) e renomeia por cima do arquivo final — nunca deixa
    um JSON pela metade visível para outro processo (robô + web lendo ao
    mesmo tempo)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(dados, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder)
    temporario = caminho.with_name(caminho.name + f".tmp-{os.getpid()}")
    temporario.write_text(texto, encoding="utf-8")
    os.replace(temporario, caminho)
    return caminho


def _ler_json(caminho: Path, padrao):
    """Leitura tolerante (achado dados M7): um JSON corrompido (gravação
    interrompida de uma versão anterior, disco cheio, edição manual
    malformada) nunca propaga exceção — vira `padrao`, com um aviso no log.
    Início/detalhe/ficha do Assistente/fila do robô dependem de `_ler_json`
    nunca lançar."""
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        logger.warning("sei: %s corrompido, tratado como ausente", caminho)
        return padrao


def gravar_coleta(carimbo: str, dados: dict) -> Path:
    return _gravar_json(diretorio_base() / "coletas" / f"{carimbo}.json", dados)


def gravar_execucao(carimbo: str, dados: dict) -> Path:
    return _gravar_json(diretorio_base() / "execucoes" / f"{carimbo}.json", dados)


def ultima() -> dict | None:
    pasta = diretorio_base() / "execucoes"
    if not pasta.exists():
        return None
    arquivos = sorted(pasta.glob("*.json"), key=lambda caminho: caminho.name)
    if not arquivos:
        return None
    with open(arquivos[-1], encoding="utf-8") as arquivo:
        return json.load(arquivo)


def carregar_estado_pendencias() -> dict:
    return _migrar_chaves_antigas(_ler_json(diretorio_base() / "estado.json", {}))


def gravar_estado_pendencias(estado: dict) -> None:
    _gravar_json(diretorio_base() / "estado.json", estado)


def ler_cache() -> dict:
    """Cache incremental da varredura (Fase 34):
    `{"processos": {<numero_sei>: {...}}, "documentos": {<id_documento>: {...}}}`.
    Sem arquivo, devolve as duas chaves vazias — `sei_sincronizar`/`sei_atender`/
    `sei_coletar` sempre esperam as duas presentes. NUNCA passa por
    `aplicar_retencao` (retenção não toca o cache)."""
    return _ler_json(diretorio_base() / "cache.json", {"processos": {}, "documentos": {}})


def gravar_cache(cache: dict) -> None:
    _gravar_json(diretorio_base() / "cache.json", cache)


def ler_links() -> dict:
    """Mapa de hiperlinks SEI: `{"processos": {<numero_sei>:
    {"id_procedimento"|"nao_encontrado", "resolvido_em"}}, "documentos":
    {<protocolo>: {"id_documento", "numero_sei"}}}`. Sem arquivo, devolve as
    duas chaves vazias — mesmo contrato de `ler_cache()`. Arquivo PRÓPRIO
    (`links.json`), nunca apagado pelo reset do `cache.json` nem pela
    restauração do banco, e NUNCA passa por `aplicar_retencao`."""
    return _ler_json(diretorio_base() / "links.json", {"processos": {}, "documentos": {}})


def gravar_links(links: dict) -> None:
    _gravar_json(diretorio_base() / "links.json", links)


def ler_extensao() -> dict:
    """Coleta recebida das extensões SEI Pro (Fase 42):
    `{"processos": {<numero_sei>: {"coleta": {"registros", "primeiro"},
    "recebido_em": iso, "usuario_id": n}}}`. Sem arquivo, devolve a chave
    vazia — mesmo contrato de `ler_cache()`. Arquivo PRÓPRIO
    (`extensao.json`), NUNCA o `cache.json` do robô: o robô só regrava o
    cache no FIM de uma varredura que pode levar horas — gravar nele pela
    API perderia as coletas da extensão feitas nesse meio-tempo. Fora da
    retenção (`aplicar_retencao` só varre subpastas por carimbo; este é um
    arquivo único na raiz, como `cache.json`/`links.json`)."""
    return _ler_json(diretorio_base() / "extensao.json", {"processos": {}})


def gravar_extensao(dados: dict) -> None:
    """Grava `extensao.json` sob `fcntl.flock` BLOQUEANTE (sem `LOCK_NB`):
    diferente do robô (processo único, sequencial), a API web pode receber
    2 POSTs concorrentes de números SEI diferentes do MESMO processo — a
    escrita é curta, então esperar alguns milissegundos pelo lock é melhor
    que perder a coleta de um deles por contenção (interfaces — mesmo padrão de `fcntl.flock` de
    `apps.assistente.indice`, aqui sem `LOCK_NB`/exceção). Substitui o
    arquivo INTEIRO — usada hoje só por testes (seed de `extensao.json`
    para os testes de `GET /api/sei/processo`); o POST real
    usa `atualizar_extensao()` abaixo, que lê+atualiza+escreve dentro da
    MESMA seção crítica (nunca duas aquisições separadas do lock, que
    reabriria a janela de corrida entre dois POSTs concorrentes)."""
    caminho_lock = diretorio_base() / "extensao.lock"
    caminho_lock.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_lock, "a+") as arquivo_lock:
        fcntl.flock(arquivo_lock, fcntl.LOCK_EX)
        try:
            _gravar_json(diretorio_base() / "extensao.json", dados)
        finally:
            fcntl.flock(arquivo_lock, fcntl.LOCK_UN)


def atualizar_extensao(numero_sei: str, coleta: dict, usuario_id: int) -> None:
    """Atualiza em `extensao.json` SÓ a entrada do `numero_sei` recebido
    (`POST /api/sei/coleta`): `{"coleta": coleta,
    "recebido_em": agora, "usuario_id": usuario_id}` — as demais entradas
    (de outros números/POSTs anteriores) ficam intocadas. A leitura do
    arquivo atual + a atualização da chave + a escrita de volta acontecem
    TODAS dentro da MESMA seção crítica de `fcntl.flock` bloqueante (mesmo
    arquivo de lock de `gravar_extensao`, `extensao.lock`) — nunca lê fora
    e escreve depois, o que reabriria a janela de corrida entre dois POSTs
    concorrentes de números diferentes do MESMO processo (um apagaria a
    entrada que o outro acabou de gravar). Não chama `gravar_extensao()`
    por dentro — abrir uma segunda seção crítica no mesmo processo
    bloquearia esperando a si mesmo (`fcntl.flock` não é reentrante entre
    descritores diferentes do mesmo arquivo)."""
    caminho_lock = diretorio_base() / "extensao.lock"
    caminho_lock.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_lock, "a+") as arquivo_lock:
        fcntl.flock(arquivo_lock, fcntl.LOCK_EX)
        try:
            dados = _ler_json(diretorio_base() / "extensao.json", {"processos": {}})
            dados.setdefault("processos", {})[numero_sei] = {
                "coleta": coleta,
                "recebido_em": timezone.localtime().isoformat(),
                "usuario_id": usuario_id,
            }
            _gravar_json(diretorio_base() / "extensao.json", dados)
        finally:
            fcntl.flock(arquivo_lock, fcntl.LOCK_UN)


def adquirir_lock() -> bool:
    caminho = diretorio_base() / "em_execucao"
    if caminho.exists():
        mtime = datetime.fromtimestamp(caminho.stat().st_mtime, tz=dt_timezone.utc)
        if timezone.now() - mtime < timedelta(hours=3):
            return False
    _gravar_json(caminho, {
        "pid": os.getpid(),
        "carimbo": novo_carimbo(),
        "iniciado_em": timezone.localtime().isoformat(),
    })
    return True


def liberar_lock() -> None:
    (diretorio_base() / "em_execucao").unlink(missing_ok=True)


def ler_progresso() -> dict | None:
    """Lê o lock `em_execucao` para o card "Sincronização com o SEI" (quick). Sem arquivo -> `None`. Lock obsoleto (mtime a 3h ou mais no
    passado, mesmo limite/comparação de `adquirir_lock`, varredura anterior
    que travou sem liberar) -> `None`. Caso contrário devolve o dict
    completo, tolerando tanto o formato antigo (`pid`/`carimbo`
    [`/iniciado_em`], sem `total` — varredura que ainda não emitiu a 1ª
    linha, ou lock do `sei_atender` para um único pedido) quanto o formato
    completo pós-progresso — quem decide se há progresso pronto para exibir
    é o chamador, testando a presença da chave `total`."""
    caminho = diretorio_base() / "em_execucao"
    if not caminho.exists():
        return None
    mtime = datetime.fromtimestamp(caminho.stat().st_mtime, tz=dt_timezone.utc)
    if timezone.now() - mtime >= timedelta(hours=3):
        return None
    return _ler_json(caminho, None)


def atualizar_progresso(
    carimbo, *, item, k, total, coletados, pulados, erros, ultima_linha
) -> None:
    """Atualiza o lock `em_execucao` com o progresso item-a-item da
    varredura (chamada pela closure `progresso()` de
    `sei_sincronizar`). Sem o arquivo presente (corrida rara entre
    `liberar_lock` e uma última chamada tardia), não recria nada — retorna
    sem gravar. Com o arquivo presente, preserva `pid`/`carimbo`/
    `iniciado_em` já gravados por `adquirir_lock()` e sobrescreve/acrescenta
    `item`/`k`/`total`/`coletados`/`pulados`/`erros`/`ultima_linha`/
    `atualizado_em`."""
    caminho = diretorio_base() / "em_execucao"
    if not caminho.exists():
        return
    dados = _ler_json(caminho, {})
    dados.update({
        "item": item,
        "k": k,
        "total": total,
        "coletados": coletados,
        "pulados": pulados,
        "erros": erros,
        "ultima_linha": ultima_linha,
        "atualizado_em": timezone.localtime().isoformat(),
    })
    _gravar_json(caminho, dados)


def abrir_log_execucao(carimbo: str):
    """Devolve um `callable(linha: str)` que acrescenta `linha + "\\n"` em
    `execucoes/<carimbo>.log`, abrindo em modo append a cada chamada (sem
    arquivo aberto persistente — a varredura é sequencial, uma linha de
    cada vez, nunca em paralelo)."""
    caminho = diretorio_base() / "execucoes" / f"{carimbo}.log"

    def _escrever(linha: str) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")

    return _escrever


def interpretar_linha_progresso(linha: str) -> dict | None:
    """Função PURA: interpreta uma linha de progresso no formato exato de
    ("item <item> (<k>/<total>): <resto>"). Sem casar (inclusive a
    linha final "coleta concluída: …", que não começa com "item "),
    devolve `None`. Casando mas com `resto` num formato inesperado, também
    devolve `None`. Caso contrário devolve `{"item", "k", "total",
    "resultado"}`, com `resultado` em `{"coletado", "pulado", "erro"}`.

    Fase 42: `resto` começando com "pulado" (em vez
    da igualdade exata de antes) casa como "pulado" — cobre tanto o texto
    antigo ("pulado (sem mudança no histórico)") quanto o novo pulo por
    coleta recente da extensão ("pulado (coleta recente da extensão)"),
    backward compatible com qualquer linha já gravada em log antes desta
    fase."""
    m = _RE_LINHA_PROGRESSO.match(linha)
    if not m:
        return None
    resto = m.group("resto")
    if resto.startswith("erro — "):
        resultado = "erro"
    elif resto.startswith("pulado"):
        resultado = "pulado"
    elif resto.startswith("coletado em "):
        resultado = "coletado"
    else:
        return None
    return {
        "item": int(m.group("item")),
        "k": int(m.group("k")),
        "total": int(m.group("total")),
        "resultado": resultado,
    }


def aplicar_retencao(subpasta: str, manter: int = 60) -> int:
    """Mantém só os `manter` carimbos mais recentes de `subpasta`. Desde a,
    pareia `.json`+`.log` do MESMO carimbo como uma
    unidade só — nem toda subpasta tem `.log` (`coletas/`/`pedidos/
    atendidos/` seguem só com `.json`), mas quando `execucoes/` tem os
    dois, ambos do mesmo carimbo excedente são apagados juntos. Devolve a
    contagem de CARIMBOS excedentes, não de arquivos."""
    pasta = diretorio_base() / subpasta
    if not pasta.exists():
        return 0
    carimbos = {caminho.stem for caminho in pasta.glob("*.json")}
    carimbos |= {caminho.stem for caminho in pasta.glob("*.log")}
    ordenados = sorted(carimbos, reverse=True)
    excedentes = ordenados[manter:]
    for carimbo in excedentes:
        (pasta / f"{carimbo}.json").unlink(missing_ok=True)
        (pasta / f"{carimbo}.log").unlink(missing_ok=True)
    return len(excedentes)


# --- Fila de pedidos sob demanda (§3.7, base) --------------------


def gravar_pedido(*, item_pca: int, exercicio: int, solicitado_por: int) -> Path:
    dados = {
        "item_pca": item_pca,
        "exercicio": exercicio,
        "solicitado_por": solicitado_por,
        "solicitado_em": timezone.localtime().isoformat(),
    }
    return _gravar_json(diretorio_base() / "pedidos" / f"{exercicio}-{item_pca}.json", dados)


def listar_pedidos() -> list[dict]:
    pasta = diretorio_base() / "pedidos"
    if not pasta.exists():
        return []
    pedidos = []
    for arquivo in pasta.glob("*.json"):
        with open(arquivo, encoding="utf-8") as leitor:
            dados = json.load(leitor)
        dados["_arquivo"] = arquivo
        pedidos.append(dados)
    pedidos.sort(key=lambda pedido: pedido["solicitado_em"])
    return pedidos


def mover_pedido_para_atendidos(pedido: dict, resultado: dict) -> Path:
    dados = {chave: valor for chave, valor in pedido.items() if chave != "_arquivo"}
    dados["resultado"] = resultado
    caminho = _gravar_json(
        diretorio_base() / "pedidos" / "atendidos" / f"{novo_carimbo()}-{pedido['item_pca']}.json",
        dados,
    )
    arquivo_original = pedido.get("_arquivo")
    if arquivo_original is not None:
        Path(arquivo_original).unlink(missing_ok=True)
    return caminho


def descartar_pedidos_vencidos(limite_horas: float = 2) -> list[dict]:
    limite = timedelta(hours=limite_horas)
    agora = timezone.localtime()
    descartados = []
    for pedido in listar_pedidos():
        solicitado_em = datetime.fromisoformat(pedido["solicitado_em"])
        # Achado dados M7 — `gravar_pedido` sempre grava com offset, mas um
        # pedido editado manualmente (ou de uma versão anterior) pode vir
        # sem fuso; sem isto, a subtração abaixo lança
        # `TypeError: can't subtract offset-naive and offset-aware datetimes`
        # e derruba o laço do robô inteiro.
        if timezone.is_naive(solicitado_em):
            solicitado_em = timezone.make_aware(solicitado_em)
        if agora - solicitado_em > limite:
            resultado = {
                "status": "descartado_por_prazo",
                "campos": [],
                "pendencias": [],
                "mensagem": None,
                "atendido_em": timezone.localtime().isoformat(),
            }
            mover_pedido_para_atendidos(pedido, resultado)
            descartados.append(pedido)
    return descartados


def ultimo_pedido_atendido() -> dict | None:
    """Último pedido atendido + contagem de atendidos hoje (Fase 34),
    lidos de `pedidos/atendidos/`. Pasta ausente ou vazia -> `None`. Ordena
    pelo carimbo do nome do arquivo (mesmo padrão de `ultima()`); "hoje" é o
    dia local (`America/Sao_Paulo`) de `resultado["atendido_em"]`. Tolerante
    a arquivo corrompido/campo ausente — pula da contagem e da escolha do
    mais recente, mesma tolerância aplicada a `ultima_execucao`
    em `core/views.py`."""
    pasta = diretorio_base() / "pedidos" / "atendidos"
    if not pasta.exists():
        return None
    arquivos = sorted(pasta.glob("*.json"), key=lambda caminho: caminho.name)

    hoje = timezone.localdate()
    atendidos_hoje = 0
    mais_recente = None
    for arquivo in arquivos:
        try:
            with open(arquivo, encoding="utf-8") as leitor:
                dados = json.load(leitor)
            resultado = dados["resultado"]
            atendido_em = timezone.localtime(
                datetime.fromisoformat(resultado["atendido_em"])
            )
            item_pca = dados["item_pca"]
            status = resultado["status"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if atendido_em.date() == hoje:
            atendidos_hoje += 1
        mais_recente = {
            "item_pca": item_pca,
            "atendido_em": atendido_em,
            "status": "ok" if status == "ok" else "erro",
        }

    if mais_recente is None:
        return None
    mais_recente["atendidos_hoje"] = atendidos_hoje
    return mais_recente


def carregar_ultima_consulta() -> dict:
    return _migrar_chaves_antigas(_ler_json(diretorio_base() / "ultima_consulta.json", {}))


def registrar_ultima_consulta(item_pca: int, exercicio: int, dados: dict) -> None:
    registrar_ultimas_consultas({(item_pca, exercicio): dados})


def registrar_ultimas_consultas(mapa: dict) -> None:
    """Grava em lote (uma leitura + uma escrita do JSON)
    a última consulta de vários itens; entradas de outros itens ficam.

    Lote 6 do QA 30/09/2026 (achado dados A3) — `mapa` é chaveado por
    `(item_pca, exercicio)`; a chave gravada no JSON é a composta
    `chave_item(item_pca, exercicio)`, nunca só o item."""
    if not mapa:
        return
    estado = carregar_ultima_consulta()
    for (item_pca, exercicio), dados in mapa.items():
        estado[chave_item(item_pca, exercicio)] = dados
    _gravar_json(diretorio_base() / "ultima_consulta.json", estado)


def resumir_consultas_da_coleta(processos_coletados: list, data_hora: str) -> dict:
    """`{(item_pca, exercicio): {"data_hora",
    "resultado"}}` a partir dos processos de uma coleta. `ok` só quando
    TODOS os processos do item vieram `resultado == "ok"` — "pulado (sem
    mudança no histórico)" conta como ok, o histórico foi conferido;
    qualquer outro resultado vira `erro`. Entradas sem `item_pca` OU sem
    `exercicio` são ignoradas (Lote 6 do QA 30/09/2026, achado dados A3 — a
    chave de retorno precisa dos dois para não misturar exercícios abertos
    simultaneamente). Função pura."""
    mapa: dict = {}
    for processo in processos_coletados:
        item_pca = processo.get("item_pca")
        exercicio = processo.get("exercicio")
        if item_pca is None or exercicio is None:
            continue
        ok = processo.get("resultado") == "ok"
        chave = (item_pca, exercicio)
        anterior = mapa.get(chave)
        resultado = "ok" if ok and (anterior is None or anterior["resultado"] == "ok") else "erro"
        mapa[chave] = {"data_hora": data_hora, "resultado": resultado}
    return mapa
