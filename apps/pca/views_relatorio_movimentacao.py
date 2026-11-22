"""View da tela "Relatório da reunião" (antes "Relatório de movimentação", Fase 27).

Só wiring e apresentação — o documento inteiro (reunião, período, indicadores, gráficos, tabelas e anexos)
sai de `apps.pca.congelamento`: os FATOS do relatório (`apurar_relatorio`, ao vivo, guardados ou reconstituídos)
são apresentados com o código e o template ATUAIS (`apresentar_relatorio`). A URL
(`pca:relatorio_movimentacao`) e a permissão continuam as mesmas: o relatório É acompanhamento (revisto) e exige `pca.view_acompanhamento`; o grupo `visualizador` não o vê.

De onde vem o documento:
  (a) reunião FECHADA, sem datas no GET: os fatos congelados (a versão mais recente ou `?versao=n`),
      sem recalcular nada; sem nenhuma versão, reconstitui do histórico e guarda a versão 1;
  (b) reunião ABERTA, sem datas: ao vivo, com o aviso de prévia (e as versões anteriores, se foi reaberta);
  (c) período livre com "até" no passado: calculado sobre a cópia do banco no fim do dia "até" (subprocesso
      de `checkout`), sem gravar nada, com "Dados até";
  (d) demais casos: ao vivo.
Com datas no GET o relatório é de PERÍODO, não de reunião: os fatos são apurados com `reuniao=None` (título
"Relatório de acompanhamento do PCA {ano}", sem ordinal, condutor nem registros da reunião).
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.catalogo.models import Exercicio
from apps.pca import checkout, congelamento
from apps.pca.filtros import resolver_exercicio
from apps.pca.models import Reuniao, SituacaoReuniao
from apps.pca.relatorio_reuniao import resolver_periodo, resolver_reuniao
from core.templatetags.dsgov import data_br

ROTULO = "Relatório da reunião"


def _versao_pedida(get):
    valor = (get.get("versao") or "").strip()
    return int(valor) if valor.isdigit() else None


def _lista_de_versoes(versoes, exercicio, reuniao, escolhida):
    base = reverse("pca:relatorio_movimentacao")
    return [
        {
            "versao": v.versao,
            "hash_curto": v.hash_curto,
            "criado_em": timezone.localtime(v.criado_em),
            "rotulo": v.get_origem_display(),
            "url": f"{base}?exercicio={exercicio.ano}&reuniao={reuniao.pk}&versao={v.versao}",
            "atual": escolhida is not None and v.pk == escolhida.pk,
        }
        for v in reversed(versoes)
    ]


@permission_required("pca.view_acompanhamento", raise_exception=True)
def relatorio_movimentacao_view(request):
    """Exercício + reunião (a aberta por padrão; período desde a reunião anterior, até hoje se ainda
    aberta) + datas livres (prevalecem). O título da página vira o nome sugerido do PDF."""
    get = request.GET
    exercicio = resolver_exercicio(get)

    documento = None
    congelado = None
    versoes = []
    total_versoes = 0
    previa = False
    dados_ate = None
    integridade_ok = True
    erro = None
    reunioes = []
    titulo_arquivo = "Relatorio-reuniao-PCA"
    trilha = [(ROTULO, None)]

    if exercicio is not None:
        hoje = timezone.localdate()
        reuniao = resolver_reuniao(get, exercicio)
        de, ate, aviso = resolver_periodo(get, exercicio, reuniao)
        if aviso:
            messages.warning(request, aviso)
        livre_pedido = bool(get.get("de") and get.get("ate"))
        livre_valido = livre_pedido and not aviso
        casca_tabler = congelamento.casca_tabler_ativa()
        # Datas livres = relatório de período: sem reunião nos fatos (o seletor continua mostrando uma).
        reuniao_dos_fatos = None if livre_pedido else reuniao
        pedida = _versao_pedida(get)
        try:
            todas = list(reuniao.relatorios_congelados.select_related("criado_por").order_by("versao")) if reuniao else []
            por_numero = {v.versao: v for v in todas}
            serve_congelado = (
                reuniao is not None
                and not livre_pedido
                and (reuniao.situacao == SituacaoReuniao.FECHADA or pedida in por_numero)
            )
            if serve_congelado:
                if not todas:
                    todas = [congelamento.reconstituir(reuniao, usuario=request.user)]
                    por_numero = {v.versao: v for v in todas}
                escolhida = todas[-1]
                if pedida is not None or get.get("versao"):
                    if pedida in por_numero:
                        escolhida = por_numero[pedida]
                    else:
                        messages.warning(request, "Versão pedida não encontrada; mostrando a mais recente.")
                congelado = escolhida
                total_versoes = len(todas)
                versoes = _lista_de_versoes(todas, exercicio, reuniao, escolhida)
                integridade_ok = escolhida.integro
                if integridade_ok:
                    documento = congelamento.renderizar_fatos(escolhida.dados, casca_tabler=casca_tabler)
            elif livre_valido and ate < hoje:
                fatos = checkout.apurar_no_corte(
                    corte=congelamento.fim_do_dia(ate), exercicio=exercicio, reuniao=reuniao_dos_fatos,
                    de=de, ate=ate, usuario=request.user,
                )
                documento = congelamento.renderizar_fatos(fatos, casca_tabler=casca_tabler)
                dados_ate = ate
            else:
                if not livre_pedido and get.get("versao"):
                    messages.warning(request, "Versão pedida não encontrada; mostrando a prévia ao vivo.")
                documento = congelamento.renderizar_documento(
                    exercicio=exercicio, reuniao=reuniao_dos_fatos, de=de, ate=ate, usuario=request.user,
                    hoje=hoje, casca_tabler=casca_tabler,
                )
                if livre_valido:
                    dados_ate = hoje
                if reuniao is not None and not livre_pedido and reuniao.situacao == SituacaoReuniao.ABERTA:
                    previa = True
                    total_versoes = len(todas)
                    versoes = _lista_de_versoes(todas, exercicio, reuniao, None)
        except checkout.CheckoutErro as exc:
            erro = (
                "Não foi possível reconstituir o relatório a partir do histórico "
                f"({exc}). Tente de novo; se persistir, avise a equipe do PCA."
            )
            documento = None
            congelado = None
            versoes = []
            dados_ate = None
            previa = False
        for ordinal, item in enumerate(Reuniao.objects.filter(exercicio=exercicio).order_by("data"), start=1):
            rotulo = f"{ordinal}ª reunião – {data_br(item.data)}"
            if item.situacao == SituacaoReuniao.ABERTA:
                rotulo += " (em andamento)"
            reunioes.append({"pk": item.pk, "rotulo": rotulo, "selecionada": reuniao is not None and item.pk == reuniao.pk})
        data_arquivo = reuniao_dos_fatos.data if reuniao_dos_fatos is not None else ate
        titulo_arquivo = f"Relatorio-reuniao-PCA-{data_arquivo:%Y-%m-%d}"
        trilha = [
            (f"PCA {exercicio.ano}", f"{reverse('raiz')}?exercicio={exercicio.ano}"),
            (ROTULO, None),
        ]

    contexto = {
        "documento": documento,
        "congelado": congelado,
        "congelado_por": (
            (congelado.criado_por.get_full_name() or congelado.criado_por.email)
            if congelado is not None and congelado.criado_por_id
            else ""
        ),
        "versoes": versoes,
        "total_versoes": total_versoes,
        "previa": previa,
        "dados_ate": dados_ate,
        "integridade_ok": integridade_ok,
        "erro": erro,
        "reunioes": reunioes,
        "exercicio": exercicio,
        "exercicios_disponiveis": Exercicio.objects.order_by("-ano"),
        # QA 30/09 navegador M1 — De/Até ecoam só o que veio no GET, nunca o período efetivo: senão o
        # form reenvia esse valor a cada submit e a escolha da reunião nunca tem efeito.
        "de_querystring": get.get("de", ""),
        "ate_querystring": get.get("ate", ""),
        "titulo_arquivo": titulo_arquivo,
        "trilha": trilha,
    }
    resposta = render(request, "pca/relatorio_reuniao.html", contexto)
    # Pitfall 16 — nunca cacheável na borda; o relatório é por sessão autenticada.
    resposta["Cache-Control"] = "private, no-store"
    return resposta
