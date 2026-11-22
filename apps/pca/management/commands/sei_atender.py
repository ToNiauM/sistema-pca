"""Laço permanente do serviço `robo` (Fase 32, spec
§3.7): atende a fila de pedidos sob demanda `data/sei/pedidos/` (gravada
pela ação "Atualizar com o SEI" do Django Admin), um pedido por vez.

`atender_um_passo()` é uma função de MÓDULO (não método de `Command`), para
ser importável e testável direto, sem `call_command`, com um `coletor` falso
injetado — nenhum teste deste comando chama Playwright/o SEI real.

`from apps.pca.sei import execucoes` no topo é seguro (não importa
playwright); `_coletor_real()` só importa `apps.pca.sei.coletor` quando de
fato chamada, para que este módulo inteiro seja importável no container
`web` (sem Playwright instalado) — mesma regra dos outros 3 comandos deste
plano que tocam `apps.pca.sei.coletor`.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assistente import estado as assistente_estado
from apps.assistente import fila as assistente_fila
from apps.pca.models import Estado, Processo
from apps.pca.sei import aplicador, execucoes, links
from apps.pca.sei.regras import propor
from apps.pca.servicos import eventos_financeiros

INTERVALO_LACO_S = 5
LIMITE_HORAS_PEDIDO = 2
FALHAS_LOGIN_PARA_ESPERAR = 3
ESPERA_APOS_FALHAS_LOGIN_S = 600


def _coletor_real(alvos, forcar=True):
    """Import preguiçoso — só dispara `import playwright` quando de fato
    chamada; produção sempre usa esta função (testes sempre injetam
    `coletor=<fake>` em `atender_um_passo`).

    Fase 34: a ação "Atualizar com o SEI" do Admin sempre relê
    tudo do item (`forcar=True`, default aqui) — serve de "forçar
    releitura" quando alguém desconfiar do cache; mesmo assim o cache é
    lido/atualizado/gravado, para os demais processos continuarem
    se beneficiando do atalho na próxima varredura.

    Fase 42: carrega `extensao.json` (só leitura,
    nunca grava) e repassa `extensao`/`pular_se_extensao_h` a
    `coletor.coletar` — mesmo contrato uniforme de `sei_sincronizar`,
    mesmo que `forcar=True` (o default de produção aqui) sempre bypasse o
    pulo na prática (comportamento documentado, não um bug a esconder)."""
    from apps.pca.sei.coletor import coletar

    cache = execucoes.ler_cache()
    mapa_extensao = execucoes.ler_extensao()
    resultado = coletar(
        alvos,
        cache=cache,
        forcar=forcar,
        extensao=mapa_extensao,
        pular_se_extensao_h=getattr(settings, "SEI_PULAR_SE_EXTENSAO_H", 24),
    )
    execucoes.gravar_cache(cache)

    # Mantém data/sei/links.json em dia a cada pedido
    # atendido — sem o passo extra de resolver pendentes (só sei_sincronizar
    # faz isso, é a varredura completa diária).
    mapa_links = execucoes.ler_links()
    links.atualizar_de_coleta(mapa_links, resultado)
    execucoes.gravar_links(mapa_links)

    return resultado


def _campos_atuais(processo: Processo) -> dict:
    return {
        "data_assinatura_contrato": processo.data_assinatura_contrato,
        "numero_instrumento_contratual": processo.numero_instrumento_contratual,
        "instrumento_contratual_nome_normalizado": (
            processo.instrumento_contratual.nome_normalizado
            if processo.instrumento_contratual_id
            else None
        ),
        "valor_contratado": processo.valor_contratado,
        "data_recebimento_gelic": processo.data_recebimento_gelic,
        "fornecedor_razao_social": processo.fornecedor_razao_social,
        "fornecedor_cnpj": processo.fornecedor_cnpj,
        "modalidade_nome_normalizado": (
            processo.modalidade.nome_normalizado if processo.modalidade_id else None
        ),
        "numero_contratacao": processo.numero_contratacao,
        "vigencia_inicio": processo.vigencia_inicio,
        "vigencia_fim": processo.vigencia_fim,
        # Ver comentário em `sei_aplicar.py::campos_atuais_de`.
        "unidade_sei_atual": processo.unidade_sei_atual,
        "unidade_sei_atual_desde": processo.unidade_sei_atual_desde,
    }


def _mensagem_erro_processos(processos: list[dict]) -> str:
    """Resume o erro de CADA numero SEI coletado (nenhum resultado == "ok"), mesmo padrao de
    truncamento de `_coletor_real`/excecao de `coletor_fn` (`[:500]`)."""
    return "; ".join(
        f"{p.get('numero') or '?'}: {p.get('erro') or p.get('resultado') or 'erro'}"
        for p in processos
    )[:500]


def _logar(stdout, mensagem: str) -> None:
    """Escreve uma linha de observabilidade e força o flush — sem isso, o
    `docker compose logs robo` fica sem novidade até o buffer do processo
    enchworking (UAT 18/09/2026). Sem `stdout` (chamada direta de teste, sem
    injetar o writer do Command), não loga nada — comportamento inócuo."""
    if stdout is None:
        return
    stdout.write(mensagem)
    stdout.flush()


def atender_um_passo(*, coletor=None, stdout=None) -> dict | None:
    """Atende UM pedido de `data/sei/pedidos/`, o mais antigo primeiro.

    Simplificação deliberada (documentada aqui, spec §3.7 ponto 3): a spec
    pede "espera, verifica a cada 15s" enquanto o lock da varredura noturna
    estiver em uso; em vez de um laço de espera interno, devolvemos
    `{"status": "aguardando_lock"}` sem consumir o pedido — ele permanece na
    fila — e deixamos a cadência de 5s do laço externo (`Command.handle`)
    tentar de novo na próxima iteração. Cobre a mesma espera sem duplicar
    lógica de laço.

    Devolve `None` quando não há pedido SEI nem pedido de reindexação
    (nada a fazer). `coletor` (assinatura `alvos -> dict`) é injetado pelos
    testes; em produção, `Command.handle()` nunca o passa, e `_coletor_real`
    é usada. `stdout` (um `OutputWrapper` do Command, ou qualquer objeto com
    `.write()`/`.flush()`) é opcional — só existe observabilidade por etapa
    (UAT 18/09/2026) quando `Command.handle()` o passa; sem nomes de
    pessoas nem credenciais em nenhuma linha.

    Fase 39 — PRIMEIRA ação de cada passagem: verifica (sem exigir
    `IA_API_KEY`) se a limpeza periódica de conversas/metadados do
    assistente é devida; nunca derruba o laço. Em seguida, se não há
    nenhum pedido SEI pendente, delega para o consumidor independente da
    fila de reindexação do assistente (`data/ia/pedidos/`) — prioridade
    SEI garantida por construção: o consumidor só é chamado quando esta
    fila está vazia, e no máximo um pedido de qualquer fila é atendido por
    passagem."""
    assistente_estado.limpar_se_necessario(timezone.now())

    for descartado in execucoes.descartar_pedidos_vencidos(limite_horas=LIMITE_HORAS_PEDIDO):
        _logar(stdout, f"pedido item {descartado['item_pca']} descartado por prazo")

    pedidos = execucoes.listar_pedidos()
    if not pedidos:
        return assistente_fila.consumir_um_pedido(agora=timezone.now(), stdout=stdout)

    pedido = pedidos[0]
    _logar(
        stdout,
        f"pedido item {pedido['item_pca']} recebido "
        f"(solicitado_em {pedido['solicitado_em']})",
    )

    if not execucoes.adquirir_lock():
        # A varredura noturna está em curso — o pedido PERMANECE na fila,
        # não foi consumido, e o lock não é nosso para liberar.
        return {"status": "aguardando_lock"}

    try:
        processo = (
            Processo.objects.filter(
                exercicio__ano=pedido["exercicio"], item_pca=pedido["item_pca"]
            )
            .select_related("exercicio", "instrumento_contratual")
            .first()
        )
        numeros_sei = list(processo.numeros_sei.all()) if processo is not None else []

        if processo is None or processo.estado == Estado.CANCELADO or not numeros_sei:
            resultado = {
                "status": "erro",
                "campos": [],
                "pendencias": [],
                "mensagem": "processo não encontrado, cancelado ou sem número SEI",
                "atendido_em": timezone.localtime().isoformat(),
            }
            _logar(
                stdout,
                f"item {pedido['item_pca']}: erro — {resultado['mensagem']}",
            )
        else:
            alvos = [
                {
                    "item_pca": processo.item_pca,
                    "exercicio": processo.exercicio.ano,
                    "numero_sei": numero_sei.numero_sei,
                }
                for numero_sei in numeros_sei
            ]
            coletor_fn = coletor or _coletor_real
            inicio = time.perf_counter()
            try:
                dados = coletor_fn(alvos)
            except Exception as exc:  # noqa: BLE001 — nunca derruba o laço
                mensagem = str(exc)[:500]
                classificacao = "erro_login" if (
                    "login" in mensagem.casefold() or "credencia" in mensagem.casefold()
                ) else "erro"
                resultado = {
                    "status": classificacao,
                    "campos": [],
                    "pendencias": [],
                    "mensagem": mensagem,
                    "atendido_em": timezone.localtime().isoformat(),
                }
                _logar(stdout, f"item {pedido['item_pca']}: erro — {mensagem}")
            else:
                login_info = dados.get("login") or {}
                processos_coletados = dados.get("processos") or []
                if not login_info.get("autenticado"):
                    mensagem = (login_info.get("erro") or "login nao autenticado")[:500]
                    resultado = {
                        "status": "erro_login",
                        "campos": [],
                        "pendencias": [],
                        "mensagem": mensagem,
                        "atendido_em": timezone.localtime().isoformat(),
                    }
                    _logar(stdout, f"item {pedido['item_pca']}: erro — {mensagem}")
                elif processos_coletados and all(
                    p.get("resultado") != "ok" for p in processos_coletados
                ):
                    mensagem = _mensagem_erro_processos(processos_coletados)
                    resultado = {
                        "status": "erro",
                        "campos": [],
                        "pendencias": [],
                        "mensagem": mensagem,
                        "atendido_em": timezone.localtime().isoformat(),
                    }
                    _logar(stdout, f"item {pedido['item_pca']}: erro — {mensagem}")
                else:
                    duracao_s = time.perf_counter() - inicio
                    _logar(
                        stdout,
                        f"item {pedido['item_pca']}: login ok / coleta de "
                        f"{len(alvos)} número(s) concluída em {duracao_s:.1f} s",
                    )
                    proposta = propor(
                        item_pca=processo.item_pca,
                        exercicio=processo.exercicio.ano,
                        campos_atuais=_campos_atuais(processo),
                        processos_coletados=dados.get("processos", []),
                    )
                    resumo = aplicador.aplicar([proposta], simular=False)
                    # Fase 36 — `sei_atender` nunca simula
                    # (já fora de qualquer `if simular`); `processo` já está em
                    # escopo, o caso mais simples dos três comandos. Chave
                    # composta ano-item (Lote 6 do QA 30/09/2026, achado dados
                    # A3) — nunca só `str(processo.item_pca)`.
                    chave_serie = execucoes.chave_item(processo.item_pca, processo.exercicio.ano)
                    serie = resumo["series"].get(chave_serie)
                    if serie:
                        eventos_financeiros.sincronizar(processo, serie)
                    campos = [
                        campo
                        for alterado in resumo["alterados"]
                        for campo in alterado["campos"]
                    ]
                    pendencias = [p["texto"] for p in resumo["pendencias"]]
                    resultado = {
                        "status": "ok",
                        "campos": campos,
                        "pendencias": pendencias,
                        "series": resumo["series"].get(chave_serie, []),
                        "mensagem": None,
                        "atendido_em": timezone.localtime().isoformat(),
                    }
                    _logar(
                        stdout,
                        f"item {pedido['item_pca']}: aplicado — campos: "
                        f"{', '.join(campos) or 'nenhum'} | pendências: "
                        f"{len(pendencias)} | eventos: {resumo['eventos_gravados']}",
                    )
    finally:
        execucoes.liberar_lock()

    execucoes.mover_pedido_para_atendidos(pedido, resultado)
    execucoes.registrar_ultima_consulta(
        pedido["item_pca"],
        pedido["exercicio"],
        {"data_hora": resultado["atendido_em"], "resultado": resultado["status"]},
    )
    return resultado


class Command(BaseCommand):
    help = (
        "Laço permanente do serviço robo — atende a fila de pedidos sob "
        "demanda gravada pela ação 'Atualizar com o SEI' do Admin."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--uma-vez",
            action="store_true",
            help="Roda atender_um_passo() uma única vez e sai (uso manual/depuração).",
        )

    def handle(self, *args, **options):
        # Cria data/sei/pedidos/ na subida (os demais
        # subdiretórios de execucoes.py continuam preguiçosos) — o
        # laço é o único consumidor permanente dessa fila, então ela precisa
        # existir para inspeção/monitoramento mesmo antes do 1º pedido do
        # Admin, em vez de só nascer com a primeira gravação.
        (execucoes.diretorio_base() / "pedidos").mkdir(parents=True, exist_ok=True)

        # Observabilidade do serviço robo: única linha impressa na subida,
        # para `docker compose logs robo` confirmar o laço vivo sem precisar
        # abrir shell no container nem esperar o 1º pedido.
        self.stdout.write(
            self.style.SUCCESS(
                "sei_atender: laço iniciado, aguardando pedidos em "
                "data/sei/pedidos/"
            )
        )

        if options["uma_vez"]:
            resultado = atender_um_passo(stdout=self.stdout)
            self.stdout.write(str(resultado))
            return

        falhas_login_seguidas = 0
        while True:
            resultado = atender_um_passo(stdout=self.stdout)
            if resultado and resultado.get("status") == "erro_login":
                falhas_login_seguidas += 1
                if falhas_login_seguidas >= FALHAS_LOGIN_PARA_ESPERAR:
                    # §3.7 ponto 6 — 3 erros de login seguidos: espera 10min
                    # antes de tentar de novo, para não martelar o SEI.
                    time.sleep(ESPERA_APOS_FALHAS_LOGIN_S)
                    falhas_login_seguidas = 0
            else:
                falhas_login_seguidas = 0
            time.sleep(INTERVALO_LACO_S)
