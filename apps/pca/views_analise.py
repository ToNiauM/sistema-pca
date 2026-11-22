"""Views das 3 telas novas de Análises — Fluxo de caixa / Estatísticas /
Prazos (Fase 36, documento interno de desenho §6). Módulo próprio (`views.py`
já tinha 3536+ linhas antes desta fase) — mesmo padrão de
`views_processo.py`/`views_tabela.py`.

Consome os módulos puros de `apps.pca.projecao`: a
view monta `itens: list[dict]` em UMA consulta `select_related()` +
`prefetch_related("eventos_financeiros")` (spec §3.5), chama
`fluxo.projetar`/`prazos.calcular`/`estatistica.calcular` e traduz o
resultado para o vocabulário de tela (`dsgov-kpi`, `dsgov/_par_analitico.
html`) — nenhuma consulta linha-a-linha nova (convenções do projeto/Desempenho); a
exceção declarada é a distribuição temporal em si, que GERA
linhas, não agrega.
"""

import re
import statistics
from dataclasses import replace as dataclasses_replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.timezone import localdate, localtime
from django.views.decorators.http import require_POST

from apps.catalogo.models import Unidade
from apps.pca import exportacao_fluxo, navegacao, services
from apps.pca.views import _pode_gerar_n1
from apps.pca.filtros import (
    NOMES_MES,
    exercicio_explicito,
    filtros_ativos,
    querystring_filtros,
    queryset_filtrado,
)
from apps.pca.models import CenarioFluxo, Estado, Processo, Situacao
from apps.pca.projecao import CAMADAS, CENARIOS, ROTULOS_CAMADA
from apps.pca.projecao import estatistica as estatistica_mod
from apps.pca.projecao import fluxo as fluxo_mod
from apps.pca.projecao import prazos as prazos_mod
from apps.pca.projecao import simulacao
from apps.pca.projecao import virada
from apps.pca.servicos import consultas_fluxo
from apps.pca.servicos import contratos as contratos_mod
from apps.pca.servicos.consultas_fluxo import INDICES_VALIDOS
from core import graficos
from core.templatetags.dsgov import moeda, numero, percentual
from core.templatetags.formatos import moeda_curta

# Fase 38 — mapeamento de classe utilitária do
# `core.min.css` para cada `Destino` (`br-tag` da coluna "Destino em N+1"
# em "Contratos a vencer"); constante de módulo, único lugar onde a chave
# de `Destino` vira cor de tag.
CLASSE_TAG_DESTINO = {
    "vencido": "bg-danger",
    "encerra_n": "bg-warning",
    "renova_n": "bg-info",
    "renovacao_n1": "bg-success",
    "encerra_n1": "bg-warning",
    "vigente_n1": "bg-success",
}

# Fase 37 (spec §3.2) — o rascunho de simulação vive só na
# sessão (nunca no banco); `fluxo_cenario_id` (ainda não usado
# por nenhuma view) guarda de qual `CenarioFluxo` salvo o rascunho partiu,
# quando aplicável.
CHAVE_SESSAO_FLUXO_AJUSTES = "fluxo_ajustes"
CHAVE_SESSAO_FLUXO_CENARIO_ID = "fluxo_cenario_id"

# Campos da querystring/hidden-fields preservados por toda view de ação de
# simulação (POST) ao redirecionar de volta para `pca:analise_fluxo`
# (spec §3.3 — mesmo recorte de onde a ação partiu).
CAMPOS_QUERYSTRING_FLUXO = ("exercicio", "cenario", "indice", "uo", "ano", "mes")

# Rótulos de tela dos 4 cenários (só o vocabulário da Lei 14.133,
# o jargão de mercado descartado pelo usuário nunca aparece) — `CENARIOS`
# (apps.pca.projecao) é só a tupla de chaves; o rótulo pt-BR vive aqui,
# perto do form GET que o usa.
ROTULOS_CENARIO = {
    "base": "Tudo: contratado, renovações, reajustes e planejado",
    "contratado": "Só o que já está contratado",
    "sem_reajuste": "Tudo, menos os reajustes",
    "sem_renovacao": "Tudo, menos as renovações",
}

# O que cada camada do fluxo significa, em linguagem de gestor — legenda do resumo e "Como ler" da tela
# (as duas cascas mostram o mesmo texto). A ordem é a de `ROTULOS_CAMADA`, a mesma das séries dos gráficos.
DESCRICOES_CAMADA = {
    "contratado": "Parcelas dos contratos já assinados, pelo valor contratado.",
    "renovacao": "Contratos que vencem no período e devem ser renovados: a parcela segue depois do fim da vigência.",
    "reajuste": "Só o acréscimo da correção anual pelo índice escolhido, sobre contratos e renovações.",
    "planejado": "Itens do PCA ainda sem contrato, pelo valor estimado, a partir da data provável de contratação.",
}
GRAU_CAMADA = {"contratado": "certo", "renovacao": "previsto", "reajuste": "estimado", "planejado": "estimado"}
# Cor de cada camada = cor da série no gráfico (paleta categórica de cada casca, na ordem das séries).
CORES_CAMADA_TABLER = {"contratado": "blue", "renovacao": "green", "reajuste": "orange", "planejado": "purple"}
CORES_CAMADA_HEX = {"contratado": "#1351b4", "renovacao": "#168821", "reajuste": "#cf4900", "planejado": "#93348c"}
# Mesmas cores como classe de texto do DSGov (a casca DSGov não aceita estilo inline).
CORES_CAMADA_DSGOV = {
    "contratado": "text-blue-warm-vivid-70", "renovacao": "text-green-cool-vivid-50",
    "reajuste": "text-orange-warm-vivid-50", "planejado": "text-violet-warm-vivid-60",
}

MOTIVOS_SEM_DADO = {
    "sem_vigencia": "Sem vigência (início/fim) nem data de assinatura.",
    "sem_valor": "Sem valor contratado nem estimado na competência.",
    "sem_mes_previsto": "Sem mês previsto (PCA) nem prazo efetivo.",
}

FAIXAS_VALOR_ROTULOS = {
    "ate_10_mil": "Até R$ 10 mil",
    "10_mil_a_100_mil": "R$ 10 mil a R$ 100 mil",
    "100_mil_a_1_mi": "R$ 100 mil a R$ 1 mi",
    "1_mi_a_10_mi": "R$ 1 mi a R$ 10 mi",
    "acima_de_10_mi": "Acima de R$ 10 mi",
}
FAIXAS_VALOR_ORDEM = (
    "ate_10_mil",
    "10_mil_a_100_mil",
    "100_mil_a_1_mi",
    "1_mi_a_10_mi",
    "acima_de_10_mi",
)

FAIXAS_DURACAO_ROTULOS = {
    "0-6": "0 a 6 meses",
    "7-12": "7 a 12 meses",
    "13-24": "13 a 24 meses",
    "25-60": "25 a 60 meses",
    "acima_de_60": "Acima de 60 meses",
}
FAIXAS_DURACAO_ORDEM = ("0-6", "7-12", "13-24", "25-60", "acima_de_60")

_NOMES_MES_ABREV = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


# --------------------------------------------------------------------------
# Montagem comum — itens/parâmetros (uma consulta, reaproveitada
# pelas 3 views; DRY dentro deste módulo).


def _itens_para_projecao(qs):
    """Wrapper compatível (Fase 39) — corpo movido
    para `apps.pca.servicos.consultas_fluxo.itens_para_projecao`; mesmo
    nome/assinatura para que `_contexto_fluxo`/`analise_fluxo_memoria_view`
    e qualquer teste que ainda importe este nome continuem funcionando sem
    nenhuma outra linha alterada."""
    return consultas_fluxo.itens_para_projecao(qs)


def _contratos_do_processo(p):
    """Wrapper compatível — corpo movido para `apps.pca.servicos.
    consultas_fluxo.contratos_do_processo` (Fase 39)."""
    return consultas_fluxo.contratos_do_processo(p)


def _cenario_valido(get):
    cenario = get.get("cenario") or "base"
    return cenario if cenario in CENARIOS else "base"


def _indice_valido(get):
    indice = get.get("indice") or settings.PCA_INDICE_REAJUSTE_PADRAO
    return indice if indice in INDICES_VALIDOS else settings.PCA_INDICE_REAJUSTE_PADRAO


def _uo_valida(get):
    valor = get.get("uo")
    if not valor:
        return None
    try:
        uo_id = int(valor)
    except (TypeError, ValueError):
        return None
    return uo_id if Unidade.objects.filter(pk=uo_id).exists() else None


def _ano_valido(get, exercicio):
    """Fase 37 (spec §4) — `?ano=` só entra no recorte
    dentro do horizonte que a própria tela já projeta
    (`exercicio.ano..exercicio.ano+5`, mesmo intervalo de `_anos_horizonte`);
    fora do horizonte, ausente ou não-numérico, devolve `None` SEMPRE em
    silêncio — nunca levanta erro, nunca vira `500` (mesmo padrão de
    `_uo_valida`/`_cenario_valido` acima: allowlist fechada, valor inválido
    é ignorado, não rejeitado com erro)."""
    valor = get.get("ano")
    if not valor:
        return None
    try:
        ano = int(valor)
    except (TypeError, ValueError):
        return None
    if exercicio is None:
        return None
    return ano if exercicio.ano <= ano <= exercicio.ano + 5 else None


def _mes_valido(get, ano):
    """`?mes=` só é válido ACOMPANHADO de um `ano` já válido (spec §4 — "mês
    1–12, só com ano"); sem `ano`, `mes` sozinho nunca ativa um recorte
    mensal."""
    if ano is None:
        return None
    valor = get.get("mes")
    if not valor:
        return None
    try:
        mes = int(valor)
    except (TypeError, ValueError):
        return None
    return mes if 1 <= mes <= 12 else None


def _querystring_com(get, **overrides):
    """Mesmo contrato de `core.templatetags.dsgov.url_com` (preserva a
    querystring ATUAL, sobrescreve ou remove só as chaves passadas —
    `None`/`""` remove) — usado do lado da VIEW (não do template) porque o
    `urls=` de `core.graficos.colunas`/`tabela_dados` (drill-down do
    gráfico/tabela, spec §4) é montado dentro do JSON do ECharts, onde a
    template tag não está disponível. Os links/chips que o TEMPLATE
    constrói diretamente (paginação, "Limpar filtros") usam `{% url_com %}`
    — este helper existe só para o que precisa ser Python."""
    params = get.copy()
    for chave, valor in overrides.items():
        if valor is None or valor == "":
            params.pop(chave, None)
        else:
            params[chave] = valor
    return params.urlencode()


def _indices_do_ano(indice):
    """Wrapper compatível — corpo movido para `apps.pca.servicos.
    consultas_fluxo.indices_do_ano` (Fase 39)."""
    return consultas_fluxo.indices_do_ano(indice)


def _parametros(exercicio, cenario, indice, hoje):
    """Wrapper compatível — corpo movido para `apps.pca.servicos.
    consultas_fluxo.parametros_oficiais` (Fase 39)."""
    return consultas_fluxo.parametros_oficiais(exercicio, cenario, indice, hoje)


def _mapa_uo_nomes():
    return dict(Unidade.objects.values_list("id", "nome"))


def _ajustes_da_sessao(request):
    """`Ajustes` do rascunho de simulação em `request.session` — nunca
    lança: `simulacao.de_json` cai no default de cada campo
    quando o valor gravado está corrompido/no formato antigo."""
    return simulacao.de_json(request.session.get(CHAVE_SESSAO_FLUXO_AJUSTES) or {})


def _gravar_ajustes(request, ajustes):
    request.session[CHAVE_SESSAO_FLUXO_AJUSTES] = simulacao.para_json(ajustes)


def _redirect_analise_fluxo(request, sim):
    """PRG de toda view de ação de simulação (spec §3.3) — volta para
    `pca:analise_fluxo` preservando exercicio/cenario/indice/uo/ano/mes
    vindos do POST (hidden fields do form de origem, nunca de um parâmetro
    de retorno arbitrário) mais `sim=<sim>` (a ação sempre resulta em
    rascunho ativo, mesmo partindo de `sim=<id salvo>` — spec §3.2)."""
    params = {
        chave: request.POST[chave]
        for chave in CAMPOS_QUERYSTRING_FLUXO
        if request.POST.get(chave)
    }
    params["sim"] = sim
    return redirect(f"{reverse('pca:analise_fluxo')}?{urlencode(params)}")


def _kpi_com_comparacao(rotulo, oficial, simulado, icone):
    """Fase 37 (spec §3.4) — trio Oficial/Simulado/Diferença de
    um KPI de valor (`kpi["apoio"]` mostra o simulado e a diferença em R$,
    `dsgov/_kpi_card.html` já renderiza `apoio` sem markup nova).
    `simulado=None` (sem comparação ativa) devolve o KPI de sempre, sem
    `apoio`."""
    kpi = {"rotulo": rotulo, "valor": moeda(oficial), "icone": icone}
    if simulado is not None:
        diferenca = simulado - oficial
        sinal = "+" if diferenca >= 0 else "−"
        kpi["apoio"] = f"Simulado: {moeda(simulado)} ({sinal}{moeda(abs(diferenca))})"
    return kpi



def _soma_anos(projecao, anos, camada=None):
    """Soma de `projecao.por_ano` nos `anos` (uma camada só, ou todas)."""
    total = Decimal("0")
    for ano in anos:
        camadas = projecao.por_ano.get(ano, {})
        total += camadas.get(camada, Decimal("0")) if camada else sum(camadas.values(), Decimal("0"))
    return total


def _participacao(parte, todo):
    """% de participação legível: "< 0,1%" em vez de um "0,0%" que parece zero."""
    if not todo:
        return "—"
    pct = parte / todo * 100
    return "< 0,1%" if 0 < pct < Decimal("0.1") else percentual(pct)


def _comparacao(oficial, simulado):
    """Texto "Simulado: R$ X (+R$ Y)" de um valor com comparação ativa; `None` sem comparação."""
    if simulado is None:
        return None
    diferenca = simulado - oficial
    sinal = "+" if diferenca >= 0 else "−"
    return f"Simulado: {moeda(simulado)} ({sinal}{moeda(abs(diferenca))})"


def _resumo_fluxo(projecao, projecao_sim, exercicio, competencias_mensal, get):
    """O resumo que abre a tela, lido de cima para baixo como uma história:
    quanto o PCA vai custar no horizonte inteiro, QUANDO (restante do exercício · ano seguinte · os 4 anos
    depois — blocos sem sobreposição, que somam o total) e DE ONDE vem (as 4 camadas, do mais certo ao mais
    estimado, com a participação de cada uma). Só lê os agregados que o motor já devolveu (`por_ano`)."""
    ano = exercicio.ano
    anos = _anos_horizonte(exercicio)
    total = _soma_anos(projecao, anos)
    total_sim = _soma_anos(projecao_sim, anos) if projecao_sim is not None else None
    url_fluxo = reverse("pca:analise_fluxo")

    if competencias_mensal:
        primeiro = _NOMES_MES_ABREV[int(competencias_mensal[0][5:7])].lower()
        ultimo = _NOMES_MES_ABREV[int(competencias_mensal[-1][5:7])].lower()
        periodo_restante = f"{primeiro} a {ultimo}/{ano}" if primeiro != ultimo else f"{ultimo}/{ano}"
    else:
        periodo_restante = "exercício encerrado"
    definicoes = [
        (f"Restante de {ano}", periodo_restante, [ano], True),
        (str(ano + 1), "ano inteiro", [ano + 1], True),
        (f"{ano + 2}–{ano + 5}", "4 anos seguintes", list(range(ano + 2, ano + 6)), False),
    ]
    blocos = []
    for rotulo, periodo, anos_bloco, com_link in definicoes:
        valor = _soma_anos(projecao, anos_bloco)
        simulado = _soma_anos(projecao_sim, anos_bloco) if projecao_sim is not None else None
        blocos.append({
            "rotulo": rotulo,
            "periodo": periodo,
            "valor": moeda(valor),
            "valor_curto": moeda_curta(valor),
            "percentual": percentual(valor / total * 100) if total else "—",
            "comparacao": _comparacao(valor, simulado),
            "url": (
                f"{url_fluxo}?{_querystring_com(get, ano=anos_bloco[0], mes=None, pagina=None)}#fluxo-recorte"
                if com_link else None
            ),
        })

    camadas = []
    for camada, rotulo in ROTULOS_CAMADA.items():
        valor = _soma_anos(projecao, anos, camada)
        camadas.append({
            "chave": camada,
            "rotulo": rotulo,
            "descricao": DESCRICOES_CAMADA[camada],
            "grau": GRAU_CAMADA[camada],
            "valor": moeda(valor),
            "valor_curto": moeda_curta(valor),
            "largura": f"{(valor / total * 100) if total else 0:.2f}",
            "percentual": percentual(valor / total * 100) if total else "—",
            "cor": CORES_CAMADA_TABLER[camada],
            "cor_hex": CORES_CAMADA_HEX[camada],
            "cor_dsgov": CORES_CAMADA_DSGOV[camada],
        })
    contratado = _soma_anos(projecao, anos, "contratado")
    # Certeza ano a ano: quanto do valor de cada ano já é contrato assinado. É o dado que mostra até onde a
    # projeção é conta e a partir de onde é estimativa.
    certeza = []
    for i, a in enumerate(anos):
        total_ano = _soma_anos(projecao, [a])
        pct = (_soma_anos(projecao, [a], "contratado") / total_ano * 100) if total_ano else None
        certeza.append({
            "ano": a,
            "parcial": i == 0 and bool(competencias_mensal),
            "percentual": percentual(pct) if pct is not None else "—",
            "largura": f"{pct or 0:.2f}",
            "nivel": "alta" if pct is not None and pct >= 70 else ("media" if pct is not None and pct >= 40 else "baixa"),
        })
    return {
        "periodo": f"{anos[0]}–{anos[-1]}",
        "total": moeda(total),
        "total_curto": moeda_curta(total),
        "comparacao": _comparacao(total, total_sim),
        "blocos": blocos,
        "camadas": camadas,
        "percentual_contratado": percentual(contratado / total * 100) if total else "—",
        "percentual_projetado": percentual((total - contratado) / total * 100) if total else "—",
        "certeza": certeza,
    }


def _leituras_fluxo(projecao, exercicio, linhas_uo, uo_nomes):
    """O que os números dizem, em frases curtas para quem não é da área — cada frase sai de uma conta sobre a
    própria projeção (pico, virada de certeza, concentração por unidade), nunca de texto fixo."""
    anos = _anos_horizonte(exercicio)
    leituras = []
    totais = {a: _soma_anos(projecao, [a]) for a in anos}
    anos_cheios = anos[1:]
    if any(totais[a] for a in anos_cheios):
        pico = max(anos_cheios, key=lambda a: totais[a])
        camadas_pico = projecao.por_ano.get(pico, {})
        maior = max(ROTULOS_CAMADA, key=lambda c: camadas_pico.get(c, Decimal("0")))
        leituras.append({
            "icone": "chart-bar",
            "texto": f"O ano de maior desembolso é {pico}: R$ {moeda_curta(totais[pico])}, "
                     f"a maior parte em {ROTULOS_CAMADA[maior].lower()}.",
        })
    virada = next(
        (a for a in anos_cheios
         if totais[a] and _soma_anos(projecao, [a], "contratado") / totais[a] < Decimal("0.5")),
        None,
    )
    if virada is not None:
        leituras.append({
            "icone": "alert-triangle",
            "texto": f"A partir de {virada}, menos da metade do valor de cada ano está contratada: "
                     "esses anos são estimativa e mudam conforme as renovações e contratações acontecerem.",
        })
    total_uo = sum((linha["total"] for linha in linhas_uo), Decimal("0"))
    if total_uo and len(linhas_uo) > 2:
        acumulado, maiores = Decimal("0"), []
        for linha in linhas_uo:
            acumulado += linha["total"]
            maiores.append(linha["uo"])
            if acumulado / total_uo >= Decimal("0.7"):
                break
        leituras.append({
            "icone": "building",
            "texto": f"{len(maiores)} de {len(linhas_uo)} unidades concentram "
                     f"{percentual(acumulado / total_uo * 100)} do fluxo: {', '.join(maiores)}.",
        })
    return leituras


def _alertas_dados_fluxo(premissas):
    """Falhas de cadastro que distorcem a projeção, ditas às claras (hoje: índice de reajuste sem valor, que
    faz o motor repetir o último índice conhecido em todos os anos)."""
    anos, base = [], None
    for texto in premissas:
        achado = _PREMISSA_INDICE.match(texto)
        if achado:
            anos.append(int(achado["ano"]))
            base = (achado["indice"], achado["base"], achado["pct"])
    if not anos:
        return []
    indice, ano_base, pct = base
    periodo = str(min(anos)) if min(anos) == max(anos) else f"{min(anos)} a {max(anos)}"
    return [
        f"O índice {indice} de {periodo} não está cadastrado: o reajuste repete o de {ano_base} ({pct}) em todos "
        "esses anos. Cadastrar os índices deixa a parte \"Reajuste projetado\" mais fiel."
    ]


_PREMISSA_INDICE = re.compile(
    r"^Índice (?P<indice>.+?) sem valor para (?P<ano>\d{4}): usado o de (?P<base>\d{4}) "
    r"\((?P<pct>[^)]+)\) em (?P<n>\d+) (?:item|itens)\.$"
)


def _premissas_agrupadas(premissas):
    """As premissas do motor vêm uma por ano ("Índice IPCA sem valor para 2027: usado o de 2025 (3,00 %) em
    58 itens.", repetida para 2028, 2029…). Para ler, anos seguidos com o mesmo índice e a mesma base viram
    uma linha só ("… para 2027 a 2031 …"). Só apresentação: o texto de cada premissa não muda."""
    agrupadas = []
    grupo = None
    for texto in premissas:
        achado = _PREMISSA_INDICE.match(texto)
        chave = (achado["indice"], achado["base"], achado["pct"]) if achado else None
        if achado and grupo and grupo["chave"] == chave and int(achado["ano"]) == grupo["ate"] + 1:
            grupo["ate"] = int(achado["ano"])
            grupo["itens"] = max(grupo["itens"], int(achado["n"]))
            continue
        if grupo:
            agrupadas.append(grupo)
        grupo = (
            {"chave": chave, "de": int(achado["ano"]), "ate": int(achado["ano"]), "itens": int(achado["n"])}
            if achado else {"chave": None, "texto": texto}
        )
    if grupo:
        agrupadas.append(grupo)
    linhas = []
    for g in agrupadas:
        if g["chave"] is None:
            linhas.append(g["texto"])
            continue
        indice, base, pct = g["chave"]
        anos = str(g["de"]) if g["de"] == g["ate"] else f"{g['de']} a {g['ate']}"
        plural = "item" if g["itens"] == 1 else "itens"
        linhas.append(
            f"Índice {indice} sem valor para {anos}: usado o de {base} ({pct}), em até {g['itens']} {plural} por ano."
        )
    return linhas


def _totais_no_topo(opcoes, totais, legenda):
    """Escreve o total de cada coluna empilhada acima dela (R$ abreviado) — série de linha invisível, fora da
    legenda, que o tooltip também mostra como "Total". Mesmo JSON para as duas cascas."""
    opcoes["series"].append({
        "type": "line",
        "name": "Total",
        "data": [{"value": float(t), "label": {"formatter": moeda_curta(t) if t else ""}} for t in totais],
        "symbol": "circle",
        "symbolSize": 1,
        "showSymbol": True,
        "lineStyle": {"opacity": 0},
        "itemStyle": {"color": "rgba(0,0,0,0)"},
        "emphasis": {"disabled": True},
        "label": {"show": True, "position": "top", "fontWeight": "bold"},
        "silent": True,
        "z": 10,
    })
    if isinstance(opcoes.get("legend"), dict) and opcoes["legend"].get("show", True):
        opcoes["legend"]["data"] = list(legenda)
    return opcoes


def _data_valida_simulacao(bruto):
    """Aceita tanto o formato ISO nativo de `<input type="date">`
    (`AAAA-MM-DD`) quanto `DD/MM/AAAA` — nunca lança, devolve `None` para
    qualquer entrada que não seja uma data válida em nenhum dos dois
    formatos."""
    bruto = (bruto or "").strip()
    if not bruto:
        return None
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        pass
    try:
        return datetime.strptime(bruto, "%d/%m/%Y").date()
    except ValueError:
        return None


def _competencias_mensal(hoje, exercicio_ano):
    """Competências "AAAA-MM" do mês corrente até dezembro do exercício
    (gráfico mensal "até dezembro") — vazio quando o mês corrente
    já passou de dezembro do exercício filtrado (exercício encerrado)."""
    inicio = hoje.replace(day=1)
    fim = date(exercicio_ano, 12, 1)
    competencias = []
    atual = inicio
    while (atual.year, atual.month) <= (fim.year, fim.month):
        competencias.append(f"{atual.year:04d}-{atual.month:02d}")
        atual = date(atual.year + 1, 1, 1) if atual.month == 12 else date(atual.year, atual.month + 1, 1)
    return competencias


def _rotulo_competencia(competencia):
    ano, mes = competencia.split("-")
    return f"{_NOMES_MES_ABREV[int(mes)]}/{ano}"


def _anos_horizonte(exercicio):
    """Único horizonte de anos usado no gráfico anual, na tabela UO × ano e
    no CSV: `exercicio..exercicio+5` (restante do exercício corrente + 5
    exercícios seguintes — o mesmo intervalo que `_parametros` já fecha em
    `horizonte_fim`, /M11). Antes deste fix, o gráfico/CSV cobriam 6
    anos e a tabela UO cobria 5 anos DIFERENTES entre si."""
    return list(range(exercicio.ano, exercicio.ano + 6))


# --------------------------------------------------------------------------
# Fluxo de caixa


def _contexto_fluxo(request):
    """Fase 37 (spec §6, "a função reaproveita, nunca
    recalcula") — todo o cálculo compartilhado entre `analise_fluxo_view`
e `analise_fluxo_xlsx_view`: leitura de
    filtros, `itens`/`parametros`/projeção OFICIAL, rascunho de sessão,
    resolução de `sim`/comparação SIMULADA (motor chamado no máximo 2x) e a lista "Contratações neste recorte" já agregada.
Refatoração — MESMO comportamento de antes desta
    extração, nenhuma chamada extra ao motor."""
    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]
    hoje = localdate()

    cenario = _cenario_valido(get)
    indice = _indice_valido(get)
    uo_id = _uo_valida(get)
    if uo_id:
        qs = qs.filter(unidade_organizacional_id=uo_id)

    itens = _itens_para_projecao(qs)
    parametros = _parametros(exercicio, cenario, indice, hoje)
    projecao = fluxo_mod.projetar(itens, parametros)

    # Fase 37 (spec §3.2/§3.3) — rascunho de simulação da
    # sessão, lido SEMPRE (independente de `sim=`) para pré-preencher o
    # painel "Simular" e o estado dos botões de ação por item; a projeção
    # SIMULADA em si (motor chamado 2x) só entra quando `sim != "oficial"`
    # (abaixo).
    ajustes_atuais = _ajustes_da_sessao(request)
    simulacao_ativa_sessao = ajustes_atuais != simulacao.vazio()
    indices_horizonte = [
        (ano, ajustes_atuais.indices_por_ano.get(ano, parametros.indices.get(ano)))
        for ano in range(exercicio.ano, exercicio.ano + 6)
    ]
    lead_time_mediano_dias_exibicao = (
        ajustes_atuais.lead_time_dias
        if ajustes_atuais.lead_time_dias is not None
        else parametros.lead_time_mediano_dias
    )

    # Fase 37 (spec §4) — recorte por ano/mês: `ano_recorte`
    # dentro do horizonte (`_ano_valido`), `mes_recorte` só acompanhado de
    # `ano_recorte` (`_mes_valido`). `totais_recorte` é o MESMO dict por
    # camada que `projecao.por_mes`/`projecao.por_ano` já agregam — nenhum
    # recálculo, só leitura do agregado certo conforme o recorte.
    ano_recorte = _ano_valido(get, exercicio)
    mes_recorte = _mes_valido(get, ano_recorte)
    if ano_recorte is not None:
        if mes_recorte is not None:
            competencia_recorte = f"{ano_recorte:04d}-{mes_recorte:02d}"
            totais_recorte = projecao.por_mes.get(competencia_recorte, {})
            recorte_rotulo = f"{NOMES_MES[mes_recorte]}/{ano_recorte}"
        else:
            totais_recorte = projecao.por_ano.get(ano_recorte, {})
            recorte_rotulo = str(ano_recorte)
    else:
        totais_recorte = {}
        recorte_rotulo = None
    mes_recorte_nome = NOMES_MES.get(mes_recorte) if mes_recorte is not None else None

    # Fase 37 (spec §3.4) — `sim` resolve a
    # comparação Oficial × Simulado × Diferença. "oficial" (padrão) NUNCA
    # aplica simulação, mesmo com rascunho ativo na sessão — precisa de
    # `sim=rascunho`/`sim=<id>` explícito. `sim=<id>` só LÊ um
    # `CenarioFluxo` do MESMO exercício; inválido/de outro
    # exercício cai em "oficial" silenciosamente, nunca 500.
    sim = get.get("sim") or "oficial"
    cenario_salvo = None
    ajustes_comparacao = None
    if sim == "rascunho":
        ajustes_comparacao = ajustes_atuais
    elif sim != "oficial":
        try:
            sim_id = int(sim)
        except (TypeError, ValueError):
            sim_id = None
        if sim_id is not None:
            cenario_salvo = CenarioFluxo.objects.filter(pk=sim_id, exercicio=exercicio).first()
        if cenario_salvo is not None:
            ajustes_comparacao = simulacao.de_json(cenario_salvo.ajustes)
        else:
            sim = "oficial"

    projecao_sim = None
    variaveis_alteradas = []
    if ajustes_comparacao is not None:
        # Motor chamado 2x por requisição (oficial + simulado);
        # orçamento medido pelo teste de carga (500 itens × 72 meses).
        itens_sim, parametros_sim = simulacao.aplicar(itens, parametros, ajustes_comparacao)
        projecao_sim = fluxo_mod.projetar(itens_sim, parametros_sim)
        rotulos_itens = {
            item["item_pca"]: (
                item["_processo"].descricao_objeto[:60]
                if item.get("_processo") and item["_processo"].descricao_objeto
                else f"Item {item['item_pca']}"
            )
            for item in itens
        }
        variaveis_alteradas = simulacao.descrever(ajustes_comparacao, rotulos_itens)

    uo_nomes = _mapa_uo_nomes()
    mapa_itens = {item["item_pca"]: item for item in itens}

    # Fase 37 (spec §4) — "Contratações neste recorte": SEM
    # recorte ativo a lista fica vazia (a lista é do RECORTE, não da visão
    # geral, spec §4). Agregada sobre `projecao.parcelas` JÁ GERADAS (lista
    # em memória — exceção declarada da Fase 36/convenções do projeto/Desempenho, não é
    # consulta por linha nova), filtradas ao ano (e ao mês quando presente)
    # e agrupadas por item. Fase 37 — a MESMA lista alimenta a
    # aba "Contratações" do XLSX (`exportacao_fluxo.py`), sem recalcular.
    lista_recorte = []
    if ano_recorte is not None:
        agregados = {}
        for p in projecao.parcelas:
            ano_p, mes_p = (int(v) for v in p.competencia.split("-"))
            if ano_p != ano_recorte:
                continue
            if mes_recorte is not None and mes_p != mes_recorte:
                continue
            agr = agregados.setdefault(
                p.item_pca,
                {
                    "item_pca": p.item_pca,
                    "valores_por_camada": {camada: Decimal("0") for camada in ROTULOS_CAMADA},
                    "instrumentos": set(),
                    "total": Decimal("0"),
                },
            )
            agr["valores_por_camada"][p.camada] += p.valor
            agr["instrumentos"].add(p.instrumento)
            agr["total"] += p.valor

        for item_pca, agr in agregados.items():
            item_info = mapa_itens.get(item_pca)
            processo = item_info["_processo"] if item_info else None
            instrumentos_legiveis = sorted(
                "Principal" if i == fluxo_mod.INSTRUMENTO_PRINCIPAL else i
                for i in agr["instrumentos"]
                if i
            )
            lista_recorte.append(
                {
                    "item_pca": item_pca,
                    "objeto": processo.descricao_objeto if processo else "",
                    "uo": uo_nomes.get(item_info["uo"], "Sem unidade") if item_info else "Sem unidade",
                    "instrumentos": ", ".join(instrumentos_legiveis) or "—",
                    "valores_por_camada": agr["valores_por_camada"],
                    "total": agr["total"],
                    "url_ficha": reverse("pca:detalhe_processo", args=[exercicio.ano, item_pca]),
                    # Fase 37 (spec §5) — "Memória" ao lado do
                    # link do item, mesmo recorte de cenario/indice da
                    # tela de origem (querystring atual preservada).
                    "url_memoria": (
                        f"{reverse('pca:analise_fluxo_memoria', args=[item_pca])}"
                        f"?{_querystring_com(get)}"
                    ),
                }
            )
        lista_recorte.sort(key=lambda linha: linha["total"], reverse=True)

    return {
        "get": get,
        "exercicio": exercicio,
        "hoje": hoje,
        "cenario": cenario,
        "indice": indice,
        "uo_id": uo_id,
        "itens": itens,
        "parametros": parametros,
        "projecao": projecao,
        "ajustes_atuais": ajustes_atuais,
        "simulacao_ativa_sessao": simulacao_ativa_sessao,
        "indices_horizonte": indices_horizonte,
        "lead_time_mediano_dias_exibicao": lead_time_mediano_dias_exibicao,
        "ano_recorte": ano_recorte,
        "mes_recorte": mes_recorte,
        "mes_recorte_nome": mes_recorte_nome,
        "recorte_rotulo": recorte_rotulo,
        "totais_recorte": totais_recorte,
        "sim": sim,
        "cenario_salvo": cenario_salvo,
        "ajustes_comparacao": ajustes_comparacao,
        "projecao_sim": projecao_sim,
        "variaveis_alteradas": variaveis_alteradas,
        "uo_nomes": uo_nomes,
        "mapa_itens": mapa_itens,
        "lista_recorte": lista_recorte,
    }


@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_view(request):
    """Fase 36 (spec §6.3) — 4 KPIs, 2 gráficos empilhados
    (mensal/anual) + tabela gêmea, tabela UO × ano, "Itens sem dado" e
    "Premissas", CSV. Fase 37 (spec §7): exige
    `pca.ver_analises` — a tela estratégica não é mais leitura aberta a
    todo autenticado; só `pca:analise` (Painel quantitativo) continua sem
    restrição. Fase 37 — a leitura de filtros/cenário/
    simulação vem de `_contexto_fluxo` (reaproveitada por
    `analise_fluxo_xlsx_view`)."""
    # QA 30/09 (dominio nº11) — sem exercício aberto, `_parametros`
    # (`consultas_fluxo.py::parametros_oficiais`) desreferencia `exercicio.ano`
    # sem checar `None`; nunca monta o contexto pesado nesse cenário.
    if filtros_ativos(request.GET)["exercicio"] is None:
        return render(
            request,
            "pca/sem_exercicio_aberto.html",
            {
                "nome_tela": "Fluxo de caixa",
                "trilha": navegacao.trilha_padrao(None, "Fluxo de caixa"),
            },
        )
    ctx = _contexto_fluxo(request)
    get = ctx["get"]
    exercicio = ctx["exercicio"]
    hoje = ctx["hoje"]
    cenario = ctx["cenario"]
    indice = ctx["indice"]
    uo_id = ctx["uo_id"]
    projecao = ctx["projecao"]
    ajustes_atuais = ctx["ajustes_atuais"]
    simulacao_ativa_sessao = ctx["simulacao_ativa_sessao"]
    indices_horizonte = ctx["indices_horizonte"]
    lead_time_mediano_dias_exibicao = ctx["lead_time_mediano_dias_exibicao"]
    ano_recorte = ctx["ano_recorte"]
    mes_recorte = ctx["mes_recorte"]
    mes_recorte_nome = ctx["mes_recorte_nome"]
    recorte_rotulo = ctx["recorte_rotulo"]
    totais_recorte = ctx["totais_recorte"]
    sim = ctx["sim"]
    cenario_salvo = ctx["cenario_salvo"]
    projecao_sim = ctx["projecao_sim"]
    variaveis_alteradas = ctx["variaveis_alteradas"]
    uo_nomes = ctx["uo_nomes"]
    mapa_itens = ctx["mapa_itens"]
    lista_recorte = ctx["lista_recorte"]

    # Recorte por ano/mês (clique numa barra ou num bloco do resumo): card próprio com o total do recorte e
    # a composição pelas 4 camadas, acima da lista "Contratações neste recorte".
    kpi_recorte = None
    if ano_recorte is not None:
        total_recorte = sum(
            (totais_recorte.get(camada, Decimal("0")) for camada in ROTULOS_CAMADA), Decimal("0")
        )
        kpi_recorte = {
            "rotulo": recorte_rotulo,
            "valor": moeda(total_recorte),
            "camadas": [
                {"rotulo": rotulo, "valor": moeda(totais_recorte.get(camada, Decimal("0"))),
                 "cor": CORES_CAMADA_TABLER[camada], "cor_hex": CORES_CAMADA_HEX[camada],
                 "cor_dsgov": CORES_CAMADA_DSGOV[camada]}
                for camada, rotulo in ROTULOS_CAMADA.items()
            ],
        }

    # Gráfico 1 — mensal empilhado por camada, até dezembro do exercício.
    competencias_mensal = _competencias_mensal(hoje, exercicio.ano)
    categorias_mensal = [_rotulo_competencia(c) for c in competencias_mensal]
    resumo = _resumo_fluxo(projecao, projecao_sim, exercicio, competencias_mensal, get)
    # Os mesmos dados do resumo em gráfico (a casca DSGov não tem barra de progresso nem estilo inline):
    # de onde vem o valor (rosca das 4 camadas) e quanto já é certo em cada ano (% contratado).
    anos_resumo = _anos_horizonte(exercicio)
    grafico_composicao = {
        "id": "analise-fluxo-composicao",
        "titulo": "De onde vem o valor",
        "subtitulo": "Do mais certo (contratado) ao mais estimado (planejado).",
        "opcoes": graficos.rosca(
            [(rotulo, float(_soma_anos(projecao, anos_resumo, camada))) for camada, rotulo in ROTULOS_CAMADA.items()],
            total=(resumo["total_curto"], "no horizonte"),
            rotulo_externo=True,
            formato_valor=moeda_curta,
        ),
        "resumo": "Composição do valor projetado: "
                  + ", ".join(f"{c['rotulo']} {c['percentual']}" for c in resumo["camadas"]),
    }
    grafico_certeza = {
        "id": "analise-fluxo-certeza",
        "titulo": "Quanto já é certo, ano a ano",
        "subtitulo": "Parte do valor de cada ano que já é contrato assinado (%). O resto é estimativa.",
        "opcoes": graficos.colunas(
            [f"{c['ano']}{' (parcial)' if c['parcial'] else ''}" for c in resumo["certeza"]],
            {"% contratado": [float(c["largura"]) for c in resumo["certeza"]]},
            rotulos=True,
        ),
        "resumo": "Percentual contratado por ano: "
                  + ", ".join(f"{c['ano']} {c['percentual']}" for c in resumo["certeza"]),
    }
    serie_certeza = grafico_certeza["opcoes"]["series"][0]
    serie_certeza["data"] = [
        {"value": round(float(c["largura"]), 1), "label": {"formatter": c["percentual"]}} for c in resumo["certeza"]
    ]
    serie_certeza["label"] = {"show": True, "position": "top"}
    grafico_certeza["opcoes"]["yAxis"] = {"type": "value", "max": 100, "axisLabel": {"formatter": "{value}%"}}

    def _valor_float(decimal_valor):
        return float(decimal_valor)

    series_mensal = {
        rotulo: [
            _valor_float(projecao.por_mes.get(c, {}).get(camada, Decimal("0")))
            for c in competencias_mensal
        ]
        for camada, rotulo in ROTULOS_CAMADA.items()
    }
    # Fase 37 (spec §4) — drill-down: clique numa barra do
    # gráfico mensal navega para `?ano=A&mes=M` da própria competência,
    # preservando cenario/indice/uo/exercicio (via `_querystring_com`, que
    # parte do GET atual). Mesma URL para toda camada — o clique depende só
    # da CATEGORIA (competência), não de qual série foi clicada; por isso
    # `urls_mensal` repete a mesma lista para cada rótulo de
    # `ROTULOS_CAMADA.values()` (contrato de `graficos.colunas`).
    url_analise_fluxo = reverse("pca:analise_fluxo")
    urls_mensal_por_competencia = [
        f"{url_analise_fluxo}?{_querystring_com(get, ano=int(c[:4]), mes=int(c[5:7]), pagina=None)}#fluxo-recorte"
        for c in competencias_mensal
    ]
    urls_mensal = {rotulo: urls_mensal_por_competencia for rotulo in ROTULOS_CAMADA.values()}
    linhas_mensal_tabela = [
        [
            {"valor": _rotulo_competencia(c), "url": urls_mensal_por_competencia[i]},
            *[
                moeda(projecao.por_mes.get(c, {}).get(camada, Decimal("0")))
                for camada in ROTULOS_CAMADA
            ],
        ]
        for i, c in enumerate(competencias_mensal)
    ]
    par_mensal = {
        "titulo": f"Mês a mês até dezembro de {exercicio.ano}",
        "subtitulo": "Quanto sai em cada mês que falta do exercício. Clique num mês para ver as contratações.",
        "grafico": {
            "id": "analise-fluxo-grafico-mensal",
            "opcoes": _totais_no_topo(
                graficos.colunas(categorias_mensal, series_mensal, empilhado=True, urls=urls_mensal),
                [
                    sum(projecao.por_mes.get(c, {}).values(), Decimal("0"))
                    for c in competencias_mensal
                ],
                ROTULOS_CAMADA.values(),
            ),
            "resumo": (
                f"Fluxo de caixa mensal de {categorias_mensal[0]} a "
                f"{categorias_mensal[-1]}, 4 camadas empilhadas."
                if categorias_mensal
                else "Sem meses no horizonte do exercício filtrado."
            ),
        },
        "tabela": graficos.tabela_dados(
            ["Mês", *ROTULOS_CAMADA.values()], linhas_mensal_tabela
        ),
    }

    # Gráfico 2 — anual empilhado, {ano}..{ano+5} (M11 — mesmo horizonte
    # único da tabela UO × ano abaixo e do CSV). Fase 37 (spec
    # §3.4) — com comparação ativa (`projecao_sim`), as barras passam a
    # mostrar o SIMULADO por camada (a mesma projeção que o rascunho está
    # editando), com o total OFICIAL sobreposto em linha — a tabela gêmea
    # espelha exatamente o que o gráfico plota (acessibilidade — "Ver
    # dados" nunca mostra um número que a barra não mostrou), mais 3
    # colunas de resumo (Total Simulado/Total Oficial/Δ).
    anos_anual = _anos_horizonte(exercicio)
    # O primeiro ano só tem os meses que faltam: o eixo avisa, para ninguém comparar a barra com anos cheios.
    categorias_anual = [
        f"{a}\n({resumo['blocos'][0]['periodo']})" if i == 0 and competencias_mensal else str(a)
        for i, a in enumerate(anos_anual)
    ]
    fonte_anual = projecao_sim if projecao_sim is not None else projecao
    series_anual = {
        rotulo: [
            _valor_float(fonte_anual.por_ano.get(a, {}).get(camada, Decimal("0")))
            for a in anos_anual
        ]
        for camada, rotulo in ROTULOS_CAMADA.items()
    }
    linha_anual_oficial = None
    if projecao_sim is not None:
        linha_anual_oficial = {
            "Oficial": [
                _valor_float(
                    sum(
                        (
                            projecao.por_ano.get(a, {}).get(camada, Decimal("0"))
                            for camada in ROTULOS_CAMADA
                        ),
                        Decimal("0"),
                    )
                )
                for a in anos_anual
            ]
        }
    # Fase 37 (spec §4) — drill-down do gráfico anual: clique
    # numa barra navega para `?ano=A` (sem `mes` — recorte do ano inteiro).
    urls_anual_por_ano = [
        f"{url_analise_fluxo}?{_querystring_com(get, ano=a, mes=None, pagina=None)}#fluxo-recorte"
        for a in anos_anual
    ]
    urls_anual = {rotulo: urls_anual_por_ano for rotulo in ROTULOS_CAMADA.values()}
    colunas_anual = ["Ano", *ROTULOS_CAMADA.values()]
    if projecao_sim is not None:
        colunas_anual = [*colunas_anual, "Total (Simulado)", "Total (Oficial)", "Δ"]
    linhas_anual = []
    for i, a in enumerate(anos_anual):
        valores_camada = [
            fonte_anual.por_ano.get(a, {}).get(camada, Decimal("0")) for camada in ROTULOS_CAMADA
        ]
        linha_tabela = [
            {"valor": str(a), "url": urls_anual_por_ano[i]},
            *[moeda(v) for v in valores_camada],
        ]
        if projecao_sim is not None:
            total_sim_ano = sum(valores_camada, Decimal("0"))
            total_of_ano = sum(
                (
                    projecao.por_ano.get(a, {}).get(camada, Decimal("0"))
                    for camada in ROTULOS_CAMADA
                ),
                Decimal("0"),
            )
            diferenca_ano = total_sim_ano - total_of_ano
            sinal_ano = "+" if diferenca_ano >= 0 else "−"
            linha_tabela.extend(
                [
                    moeda(total_sim_ano),
                    moeda(total_of_ano),
                    f"{sinal_ano}{moeda(abs(diferenca_ano))}",
                ]
            )
        linhas_anual.append(linha_tabela)
    par_anual = {
        "titulo": f"Fluxo de caixa anual — {anos_anual[0]}–{anos_anual[-1]}",
        "subtitulo": (
            f"{anos_anual[0]} conta só os meses que faltam. Clique num ano para ver as contratações."
            + (" A linha mostra o total oficial, para comparar com a simulação." if projecao_sim is not None else "")
        ),
        "grafico": {
            "id": "analise-fluxo-grafico-anual",
            "opcoes": _totais_no_topo(
                graficos.colunas(
                    categorias_anual, series_anual, empilhado=True, urls=urls_anual,
                    linha=linha_anual_oficial,
                ),
                [_soma_anos(fonte_anual, [a]) for a in anos_anual],
                [*ROTULOS_CAMADA.values(), *(linha_anual_oficial or {}).keys()],
            ),
            "resumo": (
                f"Fluxo de caixa anual SIMULADO de {anos_anual[0]} a {anos_anual[-1]}, 4 camadas "
                "empilhadas, com o total oficial sobreposto em linha."
                if projecao_sim is not None
                else f"Fluxo de caixa anual de {anos_anual[0]} a {anos_anual[-1]}, 4 camadas empilhadas."
            ),
        },
        "tabela": graficos.tabela_dados(colunas_anual, linhas_anual),
    }

    # Tabela UO × ano ({ano}..{ano+5} + total, M11 — mesmo horizonte único
    # do gráfico anual acima), ordenada por total desc, linha clicável para
    # Processos filtrado pela UO. Fase 37 — o detalhamento por
    # ano permanece OFICIAL (mesmas células/urls de drill-down de sempre);
    # com comparação ativa, a coluna "Total" vira "Oficial" e ganha
    # "Simulado"/"Δ" ao lado (soma sobre `Projecao.por_uo_ano` já
    # calculado, nenhuma consulta nova).
    anos_uo = anos_anual
    linhas_uo = []
    for uo_id_linha, por_ano in projecao.por_uo_ano.items():
        valores_anos = [por_ano.get(a, Decimal("0")) for a in anos_uo]
        total = sum(valores_anos, Decimal("0"))
        total_sim = None
        if projecao_sim is not None:
            por_ano_sim = projecao_sim.por_uo_ano.get(uo_id_linha, {})
            total_sim = sum((por_ano_sim.get(a, Decimal("0")) for a in anos_uo), Decimal("0"))
        linhas_uo.append(
            {
                "uo": uo_nomes.get(uo_id_linha, "Sem unidade"),
                "uo_id": uo_id_linha,
                "valores": valores_anos,
                "total": total,
                "total_sim": total_sim,
            }
        )
    linhas_uo.sort(key=lambda linha: linha["total"], reverse=True)
    total_todas_uo = sum((linha["total"] for linha in linhas_uo), Decimal("0"))
    leituras = _leituras_fluxo(projecao, exercicio, linhas_uo, uo_nomes)
    tabela_uo_linhas = [
        [
            {
                "valor": linha["uo"],
                "url": (
                    f"{reverse('pca:tabela')}?{querystring_filtros(get, uo=linha['uo_id'])}"
                    if linha["uo_id"]
                    else None
                ),
            },
            # Fase 37 (spec §4) — cada célula de ANO (não
            # "Unidade" nem "Total") vira drill-down para `?ano=A&uo=U`,
            # mesma tela; "Total" fica sem link (recorte ambíguo, nenhum
            # ano específico).
            *[
                {
                    "valor": moeda(v),
                    "curto": moeda_curta(v) if v else "—",
                    "url": (
                        f"{url_analise_fluxo}?{_querystring_com(get, ano=a, uo=linha['uo_id'], mes=None, pagina=None)}#fluxo-recorte"
                        if linha["uo_id"]
                        else None
                    ),
                }
                for a, v in zip(anos_uo, linha["valores"])
            ],
            {"valor": moeda(linha["total"]), "curto": moeda_curta(linha["total"])},
            _participacao(linha["total"], total_todas_uo),
            *(
                [
                    moeda(linha["total_sim"]),
                    f"{'+' if (linha['total_sim'] - linha['total']) >= 0 else '−'}"
                    f"{moeda(abs(linha['total_sim'] - linha['total']))}",
                ]
                if linha["total_sim"] is not None
                else []
            ),
        ]
        for linha in linhas_uo
    ]
    colunas_uo_ano = ["Unidade", *[str(a) for a in anos_uo]]
    colunas_uo_ano.append("Oficial" if projecao_sim is not None else "Total")
    colunas_uo_ano.append("% do total")
    if projecao_sim is not None:
        colunas_uo_ano.extend(["Simulado", "Δ"])
    tabela_uo_ano = graficos.tabela_dados(
        colunas_uo_ano, tabela_uo_linhas
    )

    sem_dado = [
        {
            "item_pca": item["item_pca"],
            "motivo": MOTIVOS_SEM_DADO.get(item["motivo"], item["motivo"]),
            "url": reverse(
                "pca:editar_processo", args=[exercicio.ano, item["item_pca"]]
            ),
        }
        for item in projecao.sem_dado
    ]

    # Fase 37 (spec §4) — "Contratações neste recorte": SEM
    # recorte ativo a lista fica vazia (a lista é do RECORTE, não da visão
    # geral, spec §4). `lista_recorte` já vem agregada de `_contexto_fluxo`
    # (a MESMA lista alimenta a aba "Contratações" do XLSX,
    # sem recalcular); aqui só falta paginar e montar as células HTML
    # (links/mini-formulários) desta tela.
    pagina_recorte = None
    tabela_recorte = None
    if ano_recorte is not None:
        paginador_recorte = Paginator(lista_recorte, settings.DSGOV["ITENS_POR_PAGINA"])
        pagina_recorte = paginador_recorte.get_page(get.get("pagina"))
        linhas_recorte_tabela = [
            [
                {
                    # Fase 37 — duas âncoras na mesma célula
                    # "Item" (nº do item → ficha, "Memória" → memória de
                    # cálculo); `format_html` escapa os dois argumentos
                    # dinâmicos (URLs geradas por `reverse`/querystring do
                    # servidor, não texto livre) e devolve `SafeString`,
                    # que `{{ cel.valor }}` (sem `url` no dict) renderiza
                    # sem escapar de novo.
                    "valor": format_html(
                        '<a href="{}">{}</a> <a href="{}" class="ml-2">Memória</a>',
                        linha["url_ficha"],
                        linha["item_pca"],
                        linha["url_memoria"],
                    )
                },
                linha["objeto"] or "—",
                linha["uo"],
                linha["instrumentos"],
                *[moeda(linha["valores_por_camada"][camada]) for camada in ROTULOS_CAMADA],
                moeda(linha["total"]),
                {
                    # Fase 37 (spec §3.3) — 4 mini-formulários
                    # POST por linha (excluir/incluir, renovar, alterar
                    # valor, adiar/antecipar início); `mark_safe` porque
                    # `render_to_string` já devolve o HTML totalmente
                    # server-renderizado (nenhum texto livre do usuário
                    # entra nesse contexto — item_pca é int, valores são
                    # Decimal, ids vêm da allowlist de cenario/indice).
                    "valor": mark_safe(
                        render_to_string(
                            "pca/_fluxo_acoes_item.html",
                            {
                                "item_pca": linha["item_pca"],
                                "excluido": linha["item_pca"] in ajustes_atuais.itens_excluidos,
                                "tem_contratos": bool(
                                    (mapa_itens.get(linha["item_pca"]) or {}).get("contratos")
                                ),
                                "renovacao_atual": ajustes_atuais.renovacao_por_item.get(
                                    linha["item_pca"],
                                    (mapa_itens.get(linha["item_pca"]) or {}).get(
                                        "renovacao_prevista", False
                                    ),
                                ),
                                "valor_atual": ajustes_atuais.valor_por_item.get(
                                    linha["item_pca"]
                                ),
                                "exercicio": exercicio,
                                "cenario": cenario,
                                "indice": indice,
                                "uo_id": uo_id,
                                "ano_recorte": ano_recorte,
                                "mes_recorte": mes_recorte,
                            },
                            request=request,
                        )
                    )
                },
            ]
            for linha in pagina_recorte.object_list
        ]
        tabela_recorte = graficos.tabela_dados(
            [
                "Item", "Objeto", "Unidade", "Instrumento", *ROTULOS_CAMADA.values(), "Total",
                "Ações",
            ],
            linhas_recorte_tabela,
        )

    trilha = navegacao.trilha_padrao(exercicio, "Fluxo de caixa")

    # Fase 37 (spec §3.2) — cenários salvos do exercício, mais
    # recente primeiro (`CenarioFluxo.Meta.ordering`); `pode_editar_
    # cenario_selecionado` só é `True` quando `sim` já resolveu para um
    # `CenarioFluxo` existente (`cenario_salvo`, de `_contexto_fluxo`) E o
    # usuário é autor ou superusuário, mesma checagem das views
    # de sobrescrever/excluir abaixo, aqui só para decidir se os botões
    # "Salvar"/"Excluir" aparecem (a view continua sendo o guarda real).
    cenarios_salvos = CenarioFluxo.objects.filter(exercicio=exercicio).order_by("-atualizado_em")
    pode_editar_cenario_selecionado = cenario_salvo is not None and (
        cenario_salvo.autor_id == request.user.id or request.user.is_superuser
    )
    # Fase 37 (spec §6) — "Baixar XLSX" preserva a MESMA
    # querystring de filtros/cenário/simulação da tela (diferente do CSV
    # acima, que não carrega `sim` — o CSV sempre lista parcelas oficiais,
    # spec §1; o XLSX leva o Oficial × Simulado que a tela está mostrando).
    querystring_xlsx = urlencode(
        [
            ("exercicio", exercicio.ano),
            ("cenario", cenario),
            ("indice", indice),
            *([("uo", uo_id)] if uo_id else []),
            *([("ano", ano_recorte)] if ano_recorte is not None else []),
            *([("mes", mes_recorte)] if mes_recorte is not None else []),
            *([("sim", sim)] if sim and sim != "oficial" else []),
        ]
    )

    contexto = {
        "exercicio": exercicio,
        "trilha": trilha,
        "cenarios": ROTULOS_CENARIO.items(),
        "cenario_selecionado": cenario,
        "indices": INDICES_VALIDOS,
        "indice_selecionado": indice,
        "unidades": Unidade.objects.all(),
        "uo_selecionada": uo_id,
        # `cenario`/`indice`/`uo` NÃO são chaves canônicas de
        # `PARAMETROS_FILTRO` (querystring_filtros só reserializa Processos)
        # — construída aqui à mão, mesmos 3 parâmetros que o form GET desta
        # tela usa.
        "querystring_csv": urlencode(
            [
                ("exercicio", exercicio.ano),
                ("cenario", cenario),
                ("indice", indice),
                *([("uo", uo_id)] if uo_id else []),
                # Fase 37 (spec §4) — ano/mês do recorte
                # preservados no CSV (o CSV em si continua listando TODAS
                # as parcelas, spec §1; só a querystring do link carrega o
                # recorte, para quem reabrir a URL do link "Exportar" ver o
                # mesmo contexto de onde clicou).
                *([("ano", ano_recorte)] if ano_recorte is not None else []),
                *([("mes", mes_recorte)] if mes_recorte is not None else []),
            ]
        ),
        "resumo": resumo,
        "leituras": leituras,
        "grafico_composicao": grafico_composicao,
        "grafico_certeza": grafico_certeza,
        "alertas_dados": _alertas_dados_fluxo(projecao.premissas),
        "kpi_recorte": kpi_recorte,
        "descricoes_camada": [
            {"rotulo": rotulo, "descricao": DESCRICOES_CAMADA[camada], "grau": GRAU_CAMADA[camada],
             "cor": CORES_CAMADA_TABLER[camada], "cor_hex": CORES_CAMADA_HEX[camada],
             "cor_dsgov": CORES_CAMADA_DSGOV[camada]}
            for camada, rotulo in ROTULOS_CAMADA.items()
        ],
        "par_mensal": par_mensal,
        "par_anual": par_anual,
        # Os mesmos pares no formato do card de gráfico com "Ver dados" recolhido (as duas cascas).
        "grafico_anual": {**par_anual["grafico"], "titulo": par_anual["titulo"], "subtitulo": par_anual["subtitulo"],
                          "tabela": par_anual["tabela"], "alto": True, "col": "col-12"},
        "grafico_mensal": {**par_mensal["grafico"], "titulo": par_mensal["titulo"],
                           "subtitulo": par_mensal["subtitulo"], "tabela": par_mensal["tabela"], "col": "col-12"},
        "tabela_uo_ano": tabela_uo_ano,
        "sem_dado": sem_dado,
        "premissas": _premissas_agrupadas(projecao.premissas),
        # Fase 37 (spec §4) — recorte por ano/mês: chips,
        # "Limpar filtros" e os hidden do form GET usam `ano_recorte`/
        # `mes_recorte`/`mes_recorte_nome` diretamente (via `{% url_com %}`
        # no template); `tabela_recorte`/`pagina_recorte` alimentam a lista
        # paginada "Contratações neste recorte" (None/vazia sem recorte).
        "ano_recorte": ano_recorte,
        "mes_recorte": mes_recorte,
        "mes_recorte_nome": mes_recorte_nome,
        "recorte_rotulo": recorte_rotulo,
        "tabela_recorte": tabela_recorte,
        "pagina_recorte": pagina_recorte,
        # Fase 37 (spec §3.2/§3.3) — painel "Simular" e o "sim"
        # ativo (rascunho de sessão) — acrescenta a comparação
        # Oficial×Simulado propriamente dita a partir daqui.
        "simulacao_ativa_sessao": simulacao_ativa_sessao,
        "indices_horizonte": indices_horizonte,
        "lead_time_mediano_dias_exibicao": lead_time_mediano_dias_exibicao,
        # Fase 37 (spec §3.4) — comparação Oficial × Simulado
        # ativa nesta resposta (`sim != "oficial"` já resolvido acima).
        "sim": sim,
        "comparacao_ativa": projecao_sim is not None,
        "variaveis_alteradas": variaveis_alteradas,
        # Fase 37 (spec §3.2/§6) — seletor "Cenário salvo",
        # botões Carregar/Salvar/Excluir e "Baixar XLSX".
        "cenarios_salvos": cenarios_salvos,
        "cenario_selecionado_obj": cenario_salvo,
        "pode_editar_cenario_selecionado": pode_editar_cenario_selecionado,
        "querystring_xlsx": querystring_xlsx,
    }
    return render(request, "pca/analise_fluxo.html", contexto)


@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_csv_view(request):
    """CSV de parcelas (`StreamingHttpResponse`), mesmos filtros da tela —
    `item_pca;competencia;camada;valor;origem`. -05 (accept): toda
    célula é vocabulário fixo/numérico gerado pelo servidor (`item_pca`
    int, `competencia` "AAAA-MM", `camada`/`origem` enum) — nenhuma deriva
    de texto livre do usuário, sem necessidade de prefixo anti-fórmula."""
    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]
    hoje = localdate()

    cenario = _cenario_valido(get)
    indice = _indice_valido(get)
    uo_id = _uo_valida(get)
    if uo_id:
        qs = qs.filter(unidade_organizacional_id=uo_id)

    itens = _itens_para_projecao(qs)
    parametros = _parametros(exercicio, cenario, indice, hoje)
    projecao = fluxo_mod.projetar(itens, parametros)

    def linhas():
        # BOM UTF-8 — mesma técnica de `exportacao.py::exportar_csv`
        # (Pitfall 22): faz o Excel pt-BR escolher UTF-8 ao abrir direto.
        yield "﻿item_pca;competencia;camada;valor;origem\r\n"
        for p in projecao.parcelas:
            valor_str = f"{p.valor:.2f}".replace(".", ",")
            yield f"{p.item_pca};{p.competencia};{p.camada};{valor_str};{p.origem}\r\n"

    resposta = StreamingHttpResponse(linhas(), content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = 'attachment; filename="pca-fluxo-de-caixa.csv"'
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def _linhas_memoria_comparacao(memoria, chaves_alteradas):
    """Linhas de `Memoria.linhas` (Fase 37, spec §5 item 5) já
    traduzidas para tela, com `alterado` (bool) por linha — `br-tag` no
    template quando `(competencia, camada)` está em `chaves_alteradas`
    (conciliação Oficial × Simulado, continua valendo: cada
    tabela conserva a mesma conciliação de `Memoria.linhas` por camada)."""
    if memoria is None:
        return []
    linhas_ordenadas = sorted(memoria.linhas, key=lambda l: l.competencia)
    return [
        {
            "competencia": l.competencia,
            "camada": ROTULOS_CAMADA.get(l.camada, l.camada),
            "valor": moeda(l.valor),
            "formula": l.formula,
            "alterado": (l.competencia, l.camada) in chaves_alteradas,
        }
        for l in linhas_ordenadas
    ]


@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_memoria_view(request, item_pca):
    """Fase 37 (spec §5, itens 1-4) — memória de cálculo de UM
    item: fonte(s)/eventos considerados, eventos descartados, premissas e
    parcelas com fórmula em texto — a resposta direta a "de onde veio este
    número?" (`melhorias.md` §2.6). Lê só `Projecao.memorias` (Plano
    37-02), NUNCA recalcula nada; `cenario`/`indice` lidos da querystring
    (mesmo padrão de `analise_fluxo_view`) para a memória refletir o MESMO
    recorte que o usuário estava vendo ao clicar "Memória".

    `item_pca` inexistente no exercício corrente é 404 normal (não
    é sobre isso); item existente sem projeção suficiente é `memoria=None`
    — o template mostra "sem dado", nunca 404 (o item existe)."""
    get = request.GET
    exercicio = filtros_ativos(get)["exercicio"]
    processo = get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)

    hoje = localdate()
    cenario = _cenario_valido(get)
    indice = _indice_valido(get)
    parametros = _parametros(exercicio, cenario, indice, hoje)

    # `.para_listagem()` (não `.filter()` cru) — `_itens_para_projecao` lê
    # `p.prazo_efetivo` (annotation COALESCE de `para_listagem()`, mesma
    # fonte de `queryset_filtrado`); sem ela, o mesmo `AttributeError` que
    # `analise_fluxo_view` nunca teve porque sempre parte de
    # `queryset_filtrado(request)`.
    itens = _itens_para_projecao(
        Processo.objects.para_listagem().filter(pk=processo.pk)
    )
    projecao = fluxo_mod.projetar(itens, parametros)
    memoria = projecao.memorias.get(item_pca)

    tabela_parcelas = None
    totais_por_camada = {}
    if memoria is not None:
        totais_por_camada = {
            camada: sum((l.valor for l in memoria.linhas if l.camada == camada), Decimal("0"))
            for camada in CAMADAS
        }
        linhas_ordenadas = sorted(memoria.linhas, key=lambda l: l.competencia)
        linhas_parcelas = [
            [l.competencia, ROTULOS_CAMADA.get(l.camada, l.camada), moeda(l.valor), l.formula]
            for l in linhas_ordenadas
        ]
        for camada in CAMADAS:
            total_camada = totais_por_camada[camada]
            if total_camada:
                linhas_parcelas.append(
                    ["Total", ROTULOS_CAMADA[camada], moeda(total_camada), ""]
                )
        tabela_parcelas = graficos.tabela_dados(
            ["Competência", "Camada", "Valor", "Fórmula"], linhas_parcelas
        )

    # Fase 37 (spec §5 item 5) — memória DUPLA quando há
    # comparação ativa (`sim != "oficial"`, mesma leitura de `analise_fluxo_
    # view`): `memoria_simulada` usa o MESMO item (`itens`/`projecao` já
    # montados acima), só com `simulacao.aplicar` entre a montagem e o
    # motor — sem alterar em nada o comportamento de `sim == "oficial"`
    # (uma memória só).
    sim = get.get("sim") or "oficial"
    ajustes_comparacao = None
    if sim == "rascunho":
        ajustes_comparacao = _ajustes_da_sessao(request)
    elif sim != "oficial":
        cenario_salvo = None
        try:
            sim_id = int(sim)
        except (TypeError, ValueError):
            sim_id = None
        if sim_id is not None:
            cenario_salvo = CenarioFluxo.objects.filter(pk=sim_id, exercicio=exercicio).first()
        if cenario_salvo is not None:
            ajustes_comparacao = simulacao.de_json(cenario_salvo.ajustes)
        else:
            sim = "oficial"

    memoria_simulada = None
    linhas_alteradas = set()
    variaveis_alteradas = []
    if ajustes_comparacao is not None:
        itens_sim, parametros_sim = simulacao.aplicar(itens, parametros, ajustes_comparacao)
        projecao_sim = fluxo_mod.projetar(itens_sim, parametros_sim)
        memoria_simulada = projecao_sim.memorias.get(item_pca)
        if memoria is not None and memoria_simulada is not None:
            linhas_oficiais = {(l.competencia, l.camada): l.valor for l in memoria.linhas}
            linhas_simuladas = {(l.competencia, l.camada): l.valor for l in memoria_simulada.linhas}
            linhas_alteradas = {
                chave
                for chave in set(linhas_oficiais) | set(linhas_simuladas)
                if linhas_oficiais.get(chave) != linhas_simuladas.get(chave)
            }
        rotulo_item = {
            item_pca: processo.descricao_objeto[:60] if processo.descricao_objeto else f"Item {item_pca}"
        }
        variaveis_alteradas = simulacao.descrever(ajustes_comparacao, rotulo_item)

    comparacao_ativa = ajustes_comparacao is not None and memoria_simulada is not None
    linhas_oficial_comparacao = (
        _linhas_memoria_comparacao(memoria, linhas_alteradas) if comparacao_ativa else []
    )
    linhas_simulada_comparacao = (
        _linhas_memoria_comparacao(memoria_simulada, linhas_alteradas) if comparacao_ativa else []
    )

    contexto = {
        "processo": processo,
        "exercicio": exercicio,
        "memoria": memoria,
        "totais_por_camada": totais_por_camada,
        "tabela_parcelas": tabela_parcelas,
        "memoria_simulada": memoria_simulada,
        "linhas_oficial_comparacao": linhas_oficial_comparacao,
        "linhas_simulada_comparacao": linhas_simulada_comparacao,
        "variaveis_alteradas": variaveis_alteradas,
        "comparacao_ativa": comparacao_ativa,
        "sim": sim,
        "trilha": [
            (f"PCA {exercicio.ano}", f"{reverse('raiz')}?exercicio={exercicio.ano}"),
            ("Fluxo de caixa", reverse("pca:analise_fluxo")),
            (f"Memória — Item {item_pca}", None),
        ],
    }
    return render(request, "pca/analise_fluxo_memoria.html", contexto)


# --------------------------------------------------------------------------
# Simulação de variáveis (Fase 37, spec §3.2/§3.3) — rascunho na
# sessão, nunca no banco; toda view abaixo é POST + PRG (`_redirect_analise_
# fluxo`), lê `_ajustes_da_sessao`, aplica UMA mudança pontual (`Ajustes` é
# `frozen`, `dataclasses.replace`) e grava com `_gravar_ajustes`.
# VALIDAÇÃO SEMPRE na fronteira desta view — `simulacao.py` não
# toca Django/ORM, não valida nada.


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_simular_view(request):
    """Painel "Simular" (spec §3.3) — sobrescreve `indices_por_ano`/
    `lead_time_dias` do rascunho. Só entra em `Ajustes` o que DIFERE do
    parâmetro oficial — um campo devolvido igual ao pré-preenchido não vira
    "variável alterada" na faixa "Simulação ativa"."""
    exercicio = filtros_ativos(request.POST)["exercicio"]
    if exercicio is None:
        messages.error(request, "Exercício inválido — nada foi alterado na simulação.")
        return _redirect_analise_fluxo(request, sim="rascunho")

    cenario = _cenario_valido(request.POST)
    indice = _indice_valido(request.POST)
    parametros_oficial = _parametros(exercicio, cenario, indice, localdate())

    # QA 30/09/2026 (fuzz M3/navegador M3) — `novos_indices` é recalculado
    # do zero a cada submissão, mas isso não é o bug: o achado "a view apaga
    # o conjunto inteiro de índices" é 100% explicado pela máscara pt-BR do
    # `value=` dos templates (corrigida abaixo com `|unlocalize`), não por
    # lógica aqui — investigado e descartado como bug separado.
    novos_indices = {}
    for ano in range(exercicio.ano, exercicio.ano + 6):
        bruto = request.POST.get(f"indice_{ano}")
        if bruto is None or bruto.strip() == "":
            continue
        try:
            percentual = Decimal(bruto.strip().replace(",", "."))
        except InvalidOperation:
            messages.error(
                request, f"Percentual do índice de {ano} inválido — nada foi gravado."
            )
            return _redirect_analise_fluxo(request, sim="rascunho")
        if not percentual.is_finite():
            messages.error(
                request, f"Percentual do índice de {ano} inválido — nada foi gravado."
            )
            return _redirect_analise_fluxo(request, sim="rascunho")
        if not (Decimal("-50") <= percentual <= Decimal("100")):
            messages.error(
                request,
                f"Percentual do índice de {ano} fora da faixa plausível (-50 a 100) — "
                "nada foi gravado.",
            )
            return _redirect_analise_fluxo(request, sim="rascunho")
        if percentual != parametros_oficial.indices.get(ano):
            novos_indices[ano] = percentual

    lead_time_dias = None
    lead_time_bruto = (request.POST.get("lead_time_dias") or "").strip()
    if lead_time_bruto:
        try:
            lead_time_dias = int(lead_time_bruto)
        except ValueError:
            messages.error(request, "Lead time inválido — nada foi gravado.")
            return _redirect_analise_fluxo(request, sim="rascunho")
        if not (0 <= lead_time_dias <= 3650):
            messages.error(
                request, "Lead time fora da faixa plausível (0 a 3650 dias) — nada foi gravado."
            )
            return _redirect_analise_fluxo(request, sim="rascunho")
        if lead_time_dias == parametros_oficial.lead_time_mediano_dias:
            lead_time_dias = None

    ajustes_novo = dataclasses_replace(
        _ajustes_da_sessao(request), indices_por_ano=novos_indices, lead_time_dias=lead_time_dias
    )
    _gravar_ajustes(request, ajustes_novo)
    messages.success(request, "Simulação atualizada.")
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_item_excluir_view(request, item_pca):
    exercicio = filtros_ativos(request.POST)["exercicio"]
    get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)
    ajustes = _ajustes_da_sessao(request)
    _gravar_ajustes(
        request,
        dataclasses_replace(ajustes, itens_excluidos=ajustes.itens_excluidos | {item_pca}),
    )
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_item_incluir_view(request, item_pca):
    exercicio = filtros_ativos(request.POST)["exercicio"]
    get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)
    ajustes = _ajustes_da_sessao(request)
    _gravar_ajustes(
        request,
        dataclasses_replace(ajustes, itens_excluidos=ajustes.itens_excluidos - {item_pca}),
    )
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_item_renovacao_view(request, item_pca):
    exercicio = filtros_ativos(request.POST)["exercicio"]
    get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)
    destino = request.POST.get("destino") == "true"
    ajustes = _ajustes_da_sessao(request)
    renovacao_por_item = dict(ajustes.renovacao_por_item)
    renovacao_por_item[item_pca] = destino
    _gravar_ajustes(request, dataclasses_replace(ajustes, renovacao_por_item=renovacao_por_item))
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_item_valor_view(request, item_pca):
    exercicio = filtros_ativos(request.POST)["exercicio"]
    get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)
    bruto = (request.POST.get("valor") or "").strip().replace(",", ".")
    try:
        valor = Decimal(bruto)
    except InvalidOperation:
        messages.error(request, "Valor inválido — nada foi gravado.")
        return _redirect_analise_fluxo(request, sim="rascunho")
    if not valor.is_finite():
        messages.error(request, "Valor inválido — nada foi gravado.")
        return _redirect_analise_fluxo(request, sim="rascunho")
    # Faixa plausível fechada com `max_digits=14` do model
    # (`Processo.valor_estimado`/`EventoFinanceiro.valor`): positivo e
    # estritamente menor que o maior valor representável.
    if valor <= 0 or valor >= Decimal("999999999.99"):
        messages.error(request, "Valor fora da faixa plausível — nada foi gravado.")
        return _redirect_analise_fluxo(request, sim="rascunho")
    ajustes = _ajustes_da_sessao(request)
    valor_por_item = dict(ajustes.valor_por_item)
    valor_por_item[item_pca] = valor
    _gravar_ajustes(request, dataclasses_replace(ajustes, valor_por_item=valor_por_item))
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_item_inicio_view(request, item_pca):
    exercicio = filtros_ativos(request.POST)["exercicio"]
    get_object_or_404(Processo, exercicio=exercicio, item_pca=item_pca)
    data = _data_valida_simulacao(request.POST.get("inicio"))
    if data is None:
        messages.error(request, "Data inválida — nada foi gravado.")
        return _redirect_analise_fluxo(request, sim="rascunho")
    ajustes = _ajustes_da_sessao(request)
    inicio_por_item = dict(ajustes.inicio_por_item)
    inicio_por_item[item_pca] = data
    _gravar_ajustes(request, dataclasses_replace(ajustes, inicio_por_item=inicio_por_item))
    return _redirect_analise_fluxo(request, sim="rascunho")


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_voltar_oficial_view(request):
    """Limpa o rascunho da sessão — a tela volta a mostrar só a coluna
    Oficial (spec §3.2)."""
    request.session.pop(CHAVE_SESSAO_FLUXO_AJUSTES, None)
    request.session.pop(CHAVE_SESSAO_FLUXO_CENARIO_ID, None)
    return _redirect_analise_fluxo(request, sim="oficial")


# --------------------------------------------------------------------------
# Cenários salvos (Fase 37, spec §0 decisão 5/§3.2) — CRUD
# completo de `CenarioFluxo`: salvar como novo, sobrescrever, carregar no
# rascunho, excluir com página de confirmação (nunca modal).
# sobrescrever/excluir exigem `cenario.autor_id == request.user.id or
# request.user.is_superuser`; qualquer outro usuário recebe 403
# (`PermissionDenied`, mesmo contrato de `raise_exception=True`) ANTES de
# qualquer escrita. `nome` tem o mesmo limite de `CenarioFluxo.nome`
# (`max_length=100`, /entrada de texto livre) validado aqui — o
# model não valida sozinho fora de `full_clean()`.

NOME_CENARIO_TAMANHO_MAXIMO = 100


def _cenario_ou_403(cenario, request):
    """Mesma checagem de autor-ou-superusuário nas 3 views que
    mutam/leem um `CenarioFluxo` de outra pessoa; `PermissionDenied` vira
    403 puro (nunca 404, nunca redirect silencioso — o usuário precisa
    entender que a ação foi negada, não que o cenário sumiu)."""
    if cenario.autor_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def cenario_fluxo_salvar_como_view(request):
    """Salva o rascunho ATUAL da sessão como um `CenarioFluxo` novo — nome
    vazio ou já usado no exercício vira `messages.error` + redirect sem
    gravar (nunca um `IntegrityError` de 500)."""
    exercicio = filtros_ativos(request.POST)["exercicio"]
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Informe um nome para salvar o cenário.")
        return _redirect_analise_fluxo(request, sim="rascunho")
    if len(nome) > NOME_CENARIO_TAMANHO_MAXIMO:
        messages.error(
            request,
            f"Nome do cenário muito longo (máximo {NOME_CENARIO_TAMANHO_MAXIMO} caracteres).",
        )
        return _redirect_analise_fluxo(request, sim="rascunho")
    if CenarioFluxo.objects.filter(exercicio=exercicio, nome=nome).exists():
        messages.error(request, f'Já existe um cenário "{nome}" neste exercício.')
        return _redirect_analise_fluxo(request, sim="rascunho")

    cenario = CenarioFluxo.objects.create(
        exercicio=exercicio,
        nome=nome,
        autor=request.user,
        ajustes=request.session.get(CHAVE_SESSAO_FLUXO_AJUSTES) or {},
    )
    request.session[CHAVE_SESSAO_FLUXO_CENARIO_ID] = cenario.pk
    messages.success(request, f'Cenário "{nome}" salvo.')
    return _redirect_analise_fluxo(request, sim=str(cenario.pk))


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def cenario_fluxo_salvar_view(request, cenario_id):
    """Sobrescreve `cenario.ajustes` com o rascunho ATUAL da sessão — o
    cenário salvo só muda quando esta ação é acionada explicitamente (spec
    §3.2), nunca sozinho por `sim=<id>` estar na URL."""
    exercicio = filtros_ativos(request.POST)["exercicio"]
    cenario = get_object_or_404(CenarioFluxo, pk=cenario_id, exercicio=exercicio)
    _cenario_ou_403(cenario, request)
    cenario.ajustes = request.session.get(CHAVE_SESSAO_FLUXO_AJUSTES) or {}
    cenario.save()
    messages.success(request, f'Cenário "{cenario.nome}" atualizado.')
    return _redirect_analise_fluxo(request, sim=str(cenario.pk))


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def cenario_fluxo_carregar_view(request, cenario_id):
    """Copia `cenario.ajustes` para o rascunho da sessão — leitura aberta a
    qualquer usuário com `pca.ver_analises` (sem checagem de autor: carregar
    não muta o `CenarioFluxo`, spec §3.2)."""
    exercicio = filtros_ativos(request.POST)["exercicio"]
    cenario = get_object_or_404(CenarioFluxo, pk=cenario_id, exercicio=exercicio)
    request.session[CHAVE_SESSAO_FLUXO_AJUSTES] = cenario.ajustes
    request.session[CHAVE_SESSAO_FLUXO_CENARIO_ID] = cenario.pk
    messages.success(request, f'Cenário "{cenario.nome}" carregado no rascunho.')
    return _redirect_analise_fluxo(request, sim="rascunho")


@permission_required("pca.ver_analises", raise_exception=True)
def cenario_fluxo_excluir_confirmar_view(request, cenario_id):
    """Página de confirmação (mesmo padrão de
    `exercicio_confirmar_encerrar.html`, nunca modal); 403 antes de
    renderizar para quem não é autor nem superusuário (a checagem
    vale também para a página de confirmação, não só para o POST real)."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    cenario = get_object_or_404(CenarioFluxo, pk=cenario_id, exercicio=exercicio)
    _cenario_ou_403(cenario, request)
    contexto = {
        "cenario": cenario,
        "exercicio": exercicio,
        "trilha": [
            (f"PCA {exercicio.ano}", f"{reverse('raiz')}?exercicio={exercicio.ano}"),
            ("Fluxo de caixa", reverse("pca:analise_fluxo")),
            (f'Excluir cenário "{cenario.nome}"', None),
        ],
    }
    return render(request, "pca/cenario_fluxo_confirmar_excluir.html", contexto)


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
def cenario_fluxo_excluir_view(request, cenario_id):
    """Exclusão real — só por POST, só depois da página de confirmação
    acima (nunca DELETE direto). Limpa `fluxo_cenario_id` da sessão quando
    apontava para o cenário excluído."""
    exercicio = filtros_ativos(request.POST)["exercicio"]
    cenario = get_object_or_404(CenarioFluxo, pk=cenario_id, exercicio=exercicio)
    _cenario_ou_403(cenario, request)
    nome = cenario.nome
    if request.session.get(CHAVE_SESSAO_FLUXO_CENARIO_ID) == cenario.pk:
        request.session.pop(CHAVE_SESSAO_FLUXO_CENARIO_ID, None)
    cenario.delete()
    messages.success(request, f'Cenário "{nome}" excluído.')
    return _redirect_analise_fluxo(request, sim="oficial")


# --------------------------------------------------------------------------
# XLSX do fluxo de caixa (Fase 37, spec §0 decisão 6/§6) — 5
# abas (Resumo/Anual/Contratações/Parcelas/Memória), reaproveitando
# `_contexto_fluxo` (mesma leitura de filtros/cenário/simulação da tela,
# nenhuma chamada extra ao motor).


@permission_required("pca.ver_analises", raise_exception=True)
def analise_fluxo_xlsx_view(request):
    ctx = _contexto_fluxo(request)
    exercicio = ctx["exercicio"]
    sim = ctx["sim"]
    cenario_salvo = ctx["cenario_salvo"]

    if sim == "rascunho":
        cenario_nome = "rascunho"
        cenario_rotulo = "Rascunho (simulação não salva)"
    elif sim != "oficial" and cenario_salvo is not None:
        cenario_nome = cenario_salvo.nome
        cenario_rotulo = (
            f"{cenario_salvo.nome} (autor: "
            f"{cenario_salvo.autor.get_full_name() or cenario_salvo.autor.email}, "
            f"salvo em {localtime(cenario_salvo.atualizado_em):%d/%m/%Y %H:%M})"
        )
    else:
        cenario_nome = "oficial"
        cenario_rotulo = "Oficial"

    filtros_partes = [
        f"Cenário de projeção: {ROTULOS_CENARIO.get(ctx['cenario'], ctx['cenario'])}",
        f"Índice de reajuste: {ctx['indice']}",
    ]
    if ctx["uo_id"]:
        filtros_partes.append(f"Unidade: {ctx['uo_nomes'].get(ctx['uo_id'], ctx['uo_id'])}")
    if ctx["ano_recorte"] is not None:
        filtros_partes.append(f"Recorte: {ctx['recorte_rotulo']}")
    filtros_ativos_texto = " · ".join(filtros_partes)

    return exportacao_fluxo.exportar_fluxo_xlsx(
        exercicio=exercicio,
        cenario_nome=cenario_nome,
        cenario_rotulo=cenario_rotulo,
        autor=request.user.get_full_name() or request.user.email,
        filtros_ativos_texto=filtros_ativos_texto,
        variaveis_simuladas=ctx["variaveis_alteradas"],
        projecao_oficial=ctx["projecao"],
        projecao_simulada=ctx["projecao_sim"],
        lista_recorte=ctx["lista_recorte"],
        anos_horizonte=_anos_horizonte(exercicio),
    )


# --------------------------------------------------------------------------
# Estatísticas


@permission_required("pca.ver_analises", raise_exception=True)
def analise_estatisticas_view(request):
    """Fase 36 (spec §6.4) — 3 blocos (valores/vigência/
    perfil), cada um gráfico + tabela gêmea; filtro só de UO. Fase 37 (spec §7): exige `pca.ver_analises`."""
    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]

    uo_id = _uo_valida(get)
    if uo_id:
        qs = qs.filter(unidade_organizacional_id=uo_id)

    itens = _itens_para_projecao(qs)
    resultado = estatistica_mod.calcular(itens)

    uo_nomes = _mapa_uo_nomes()

    # Bloco 1 — Valores: execução financeira (contratado × estimado) por UO.
    execucao = resultado["valores"]["execucao_por_uo"]
    linhas_execucao = sorted(
        (
            {
                "uo": uo_nomes.get(uo_id_item, "Sem unidade"),
                "contratado": dados["contratado"],
                "estimado": dados["estimado"],
            }
            for uo_id_item, dados in execucao.items()
        ),
        key=lambda linha: linha["contratado"],
        reverse=True,
    )
    par_valores = {
        "titulo": "Execução financeira por unidade",
        "grafico": {
            "id": "analise-estatisticas-grafico-valores",
            "opcoes": graficos.colunas(
                [linha["uo"] for linha in linhas_execucao],
                {
                    "Contratado": [float(linha["contratado"]) for linha in linhas_execucao],
                    "Estimado": [float(linha["estimado"]) for linha in linhas_execucao],
                },
            ),
            "resumo": f"Execução financeira (contratado × estimado) em {len(linhas_execucao)} unidade(s).",
        },
        "tabela": graficos.tabela_dados(
            ["Unidade", "Contratado", "Estimado"],
            [
                [linha["uo"], moeda(linha["contratado"]), moeda(linha["estimado"])]
                for linha in linhas_execucao
            ],
        ),
    }

    # Bloco 2 — Vigência: duração contratada em faixas.
    faixas_duracao = resultado["vigencia"]["faixas_duracao"]
    par_vigencia = {
        "titulo": "Duração contratada por faixa",
        "grafico": {
            "id": "analise-estatisticas-grafico-vigencia",
            "opcoes": graficos.colunas(
                [FAIXAS_DURACAO_ROTULOS[f] for f in FAIXAS_DURACAO_ORDEM],
                {"Itens": [faixas_duracao.get(f, 0) for f in FAIXAS_DURACAO_ORDEM]},
            ),
            "resumo": "Duração contratada por faixa (0–6/7–12/13–24/25–60 meses).",
        },
        "tabela": graficos.tabela_dados(
            ["Faixa", "Itens"],
            [
                [FAIXAS_DURACAO_ROTULOS[f], numero(faixas_duracao.get(f, 0))]
                for f in FAIXAS_DURACAO_ORDEM
            ],
        ),
    }

    # Bloco 3 — Perfil: faixa de valor × modalidade (empilhado).
    distribuicao = resultado["perfil"]["distribuicao_por_faixa_e_modalidade"]
    modalidades_perfil = sorted(
        {modalidade for por_modalidade in distribuicao.values() for modalidade in por_modalidade}
    )
    series_perfil = {
        modalidade: [
            distribuicao.get(faixa, {}).get(modalidade, 0) for faixa in FAIXAS_VALOR_ORDEM
        ]
        for modalidade in modalidades_perfil
    }
    par_perfil = {
        "titulo": "Perfil por faixa de valor e modalidade",
        "grafico": {
            "id": "analise-estatisticas-grafico-perfil",
            "opcoes": graficos.colunas(
                [FAIXAS_VALOR_ROTULOS[f] for f in FAIXAS_VALOR_ORDEM],
                series_perfil,
                empilhado=True,
            ),
            "resumo": "Perfil do PCA por faixa de valor (escala log) e modalidade.",
        },
        "tabela": graficos.tabela_dados(
            ["Faixa", *modalidades_perfil],
            [
                [
                    FAIXAS_VALOR_ROTULOS[faixa],
                    *[numero(distribuicao.get(faixa, {}).get(m, 0)) for m in modalidades_perfil],
                ]
                for faixa in FAIXAS_VALOR_ORDEM
            ],
        ),
    }

    # (M08) — `estatistica.valores` já devolve
    # `mediana`/`p25`/`p75` em PONTOS PERCENTUAIS (quantizados na origem);
    # nenhuma conversão aqui, só repassar ao template.
    desvio_por_modalidade_pct = resultado["valores"]["desvio_por_modalidade"]

    trilha = navegacao.trilha_padrao(exercicio, "Estatísticas")

    contexto = {
        "exercicio": exercicio,
        "trilha": trilha,
        "unidades": Unidade.objects.all(),
        "uo_selecionada": uo_id,
        "par_valores": par_valores,
        "par_vigencia": par_vigencia,
        "par_perfil": par_perfil,
        "desvio_por_modalidade": desvio_por_modalidade_pct,
        "pareto_80": resultado["valores"]["pareto_80"],
        "top_fornecedores": resultado["valores"]["top_fornecedores"],
        "vencimentos_por_trimestre": sorted(
            resultado["vigencia"]["vencimentos_por_trimestre"].items()
        ),
        "alertas_vigencia_48_meses": resultado["vigencia"]["alertas_vigencia_acumulada_48_meses"],
    }
    return render(request, "pca/analise_estatisticas.html", contexto)


# --------------------------------------------------------------------------
# Prazos


def _multiplicador(duracoes_grupo, duracoes_geral, rotulo_estrato):
    """Multiplicador EMPÍRICO (razão de atraso observada no histórico) — `n < 5` deixa `score_risco` ignorá-lo; aqui só
    garantimos que "valor" nunca divide por zero."""
    n = len(duracoes_grupo)
    if n == 0 or not duracoes_geral:
        return {"valor": Decimal("1"), "n": n, "estrato": rotulo_estrato}
    media_geral = sum(duracoes_geral) / len(duracoes_geral)
    if not media_geral:
        return {"valor": Decimal("1"), "n": n, "estrato": rotulo_estrato}
    media_grupo = sum(duracoes_grupo) / n
    fator = Decimal(str(round(media_grupo / media_geral, 4)))
    return {"valor": fator, "n": n, "estrato": rotulo_estrato}


def _descarta_negativos(duracoes):
    """QA 30/09 (domínio nº3) — duração negativa (assinatura/Gelic de um
    CONTRATO REAPROVEITADO de ciclo anterior — Vigentes/Renovações)
    contamina mediana/P25/P75 do lead time; descarta e conta quantas foram
    descartadas, para a tela avisar."""
    validas = [d for d in duracoes if d >= 0]
    return validas, len(duracoes) - len(validas)


def _filtros_contratos(request):
    """Fase 38 — lê `request.GET` com allowlists
    fechadas de `contratos_mod`/`virada`. Valor PRESENTE e fora da
    allowlist emite `messages.warning` e cai no padrão; valor ausente usa
    o padrão em silêncio (nunca avisa por omissão). `destino` prevalece
    sobre `grupo_destino` quando os dois vêm na URL — sem aviso nesse caso
    específico, porque não é um valor inválido, é prevalência declarada.
"""
    get = request.GET

    def _validar(chave, valor, opcoes, padrao):
        if valor is None:
            return padrao
        if valor in opcoes:
            return valor
        messages.warning(request, f'Filtro "{chave}" com valor inválido foi ignorado.')
        return padrao

    vence = _validar("vence", get.get("vence"), contratos_mod.VENCE_OPCOES, "todos")
    renovacao = _validar(
        "renovacao", get.get("renovacao"), contratos_mod.RENOVACAO_OPCOES, "todas"
    )
    opcoes_destino_filtro = ("todos",) + virada.CHAVES_DESTINO
    destino_bruto = _validar(
        "destino", get.get("destino"), opcoes_destino_filtro, "todos"
    )
    destino = destino_bruto if destino_bruto != "todos" else None

    grupo_bruto = get.get("grupo_destino")
    if destino is not None:
        # Prevalência: destino válido apaga grupo_destino sem
        # emitir aviso, mesmo que grupo_bruto fosse ele próprio válido.
        grupo_destino = None
    else:
        grupo_destino = _validar(
            "grupo_destino", grupo_bruto, tuple(virada.GRUPOS_DESTINO.keys()), None
        )

    pagina_bruta = get.get("pagina")
    try:
        pagina = int(pagina_bruta) if pagina_bruta is not None else 1
    except (TypeError, ValueError):
        pagina = 1
    if pagina < 1:
        pagina = 1

    return {
        "vence": vence,
        "renovacao": renovacao,
        "destino": destino,
        "grupo_destino": grupo_destino,
        "pagina": pagina,
    }


def _url_prazos(exercicio, uos, **params):
    """Fase 38 — ÚNICO construtor de URL da seção "Contratos a
    vencer" do lado da view (cards, "Remover esses filtros" e o redirect
    da ação de renovação). `exercicio` é o objeto `Exercicio` (ou
    `None` — nesse caso não entra na querystring); valores-padrão
    (`None`/`""`/`"todos"`/`"todas"`/`1`) nunca vão para a URL. Sem
    nenhum parâmetro, devolve a rota pura (sem `"?"`)."""
    pares = []
    if exercicio is not None:
        pares.append(("exercicio", exercicio.ano))
    for uo_id in uos:
        pares.append(("uo", uo_id))
    for chave, valor in params.items():
        if valor in (None, "", "todos", "todas", 1):
            continue
        pares.append((chave, valor))
    base = reverse("pca:analise_prazos")
    if not pares:
        return base
    return f"{base}?{urlencode(pares, doseq=True)}"


@permission_required("pca.ver_analises", raise_exception=True)
@permission_required("pca.view_acompanhamento", raise_exception=True)
def analise_prazos_view(request):
    """Fase 36 (spec §6.5) — KPIs, lead time
    por etapa, curva KM, tabela de risco. Fase 38 (spec §2-§4): a antiga seção de itens vincendos em 90/180/365 dias foi
    substituída por "Contratos a vencer"
    (`apps.pca.servicos.contratos.contratos_a_vencer`)
    — primeira seção após o `<h1>`, corrige M07 (contrato `concluido`
    continuado com vigência não sumia mais da lista).

    Multiplicadores empíricos: só "nº de prorrogações já feitas"
    é calculado a partir do histórico real (concluídos com/sem
    prorrogação); "etapa atual" fica deliberadamente em 1,0 (n=0, mesmo
    comportamento de "histórico insuficiente" que o módulo já define) —
    decisão registrada em derivar um multiplicador de
    etapa a partir de itens CONCLUÍDOS (que já passaram por todas as
    etapas) não tem base histórica honesta sem uma série temporal de
    transição de etapas, fora do escopo desta fase.
    """
    get = request.GET
    exercicio = filtros_ativos(get)["exercicio"]
    # QA 30/09 (dominio nº11) — sem exercício aberto, nunca monta o contexto
    # pesado desta tela (nada aqui sobrevive a `exercicio is None`).
    if exercicio is None:
        return render(
            request,
            "pca/sem_exercicio_aberto.html",
            {"nome_tela": "Prazos", "trilha": navegacao.trilha_padrao(None, "Prazos")},
        )
    qs = queryset_filtrado(request)
    hoje = localdate()

    itens = _itens_para_projecao(qs)
    concluidos = [i for i in itens if i["situacao"] == Situacao.CONCLUIDO]
    abertos = [
        i for i in itens if i["estado"] == Estado.ATIVO and i["situacao"] != Situacao.CONCLUIDO
    ]

    for item in concluidos:
        envio = item.get("data_envio_gelic")
        recebimento = item.get("data_recebimento_gelic")
        assinatura = item.get("data_assinatura_contrato")
        conclusao = item.get("data_prevista_conclusao")
        prazo_efetivo = item.get("prazo_efetivo")
        item["dias_envio_recebimento"] = (
            (recebimento - envio).days if envio and recebimento else None
        )
        item["duracao_gelic_assinatura"] = (
            (assinatura - recebimento).days if recebimento and assinatura else None
        )
        item["dias_ate_assinatura"] = (
            (assinatura - prazo_efetivo).days if assinatura and prazo_efetivo else None
        )
        item["dias_assinatura_conclusao"] = (
            (conclusao - assinatura).days if assinatura and conclusao else None
        )

    duracoes_envio_recebimento = [
        i["dias_envio_recebimento"] for i in concluidos if i["dias_envio_recebimento"] is not None
    ]
    duracoes_recebimento_assinatura = [
        i["duracao_gelic_assinatura"] for i in concluidos if i["duracao_gelic_assinatura"] is not None
    ]
    duracoes_assinatura_conclusao = [
        i["dias_assinatura_conclusao"] for i in concluidos if i["dias_assinatura_conclusao"] is not None
    ]
    # QA 30/09 (domínio nº3) — contratos reaproveitados de ciclo anterior
    # (Vigentes/Renovações) produzem duração negativa entre marcos; essas
    # não podem contaminar mediana/P25/P75. Descartadas aqui, ANTES de
    # `lead_time_estratificado`, e contadas para a tela avisar.
    duracoes_envio_recebimento, descartados_er = _descarta_negativos(duracoes_envio_recebimento)
    duracoes_recebimento_assinatura, descartados_ra = _descarta_negativos(duracoes_recebimento_assinatura)
    duracoes_assinatura_conclusao, descartados_ac = _descarta_negativos(duracoes_assinatura_conclusao)
    lead_time_etapas = {
        "envio_recebimento": {
            "rotulo": "Envio → Recebimento no Gelic",
            **prazos_mod.lead_time_estratificado(
                duracoes_envio_recebimento, duracoes_envio_recebimento, "geral"
            ),
        },
        "recebimento_assinatura": {
            "rotulo": "Recebimento no Gelic → Assinatura",
            **prazos_mod.lead_time_estratificado(
                duracoes_recebimento_assinatura, duracoes_recebimento_assinatura, "geral"
            ),
        },
        "assinatura_conclusao": {
            "rotulo": "Assinatura → Conclusão",
            **prazos_mod.lead_time_estratificado(
                duracoes_assinatura_conclusao, duracoes_assinatura_conclusao, "geral"
            ),
        },
    }
    for chave, n_descartado in (
        ("envio_recebimento", descartados_er),
        ("recebimento_assinatura", descartados_ra),
        ("assinatura_conclusao", descartados_ac),
    ):
        lead_time_etapas[chave]["descartados"] = n_descartado
        if n_descartado > 0:
            nota = f"{n_descartado} descartado(s) por duração negativa"
            aviso_atual = lead_time_etapas[chave]["aviso"]
            lead_time_etapas[chave]["aviso"] = f"{aviso_atual}; {nota}" if aviso_atual else nota

    p25_geral = lead_time_etapas["recebimento_assinatura"]["p25"] or Decimal("0")
    p75_geral = lead_time_etapas["recebimento_assinatura"]["p75"] or Decimal("0")

    atrasos_geral = [i["dias_ate_assinatura"] for i in concluidos if i["dias_ate_assinatura"] is not None]
    atrasos_com_prorrogacao = [
        i["dias_ate_assinatura"]
        for i in concluidos
        if i["dias_ate_assinatura"] is not None and (i.get("n_prorrogacoes") or 0) >= 1
    ]
    atrasos_sem_prorrogacao = [
        i["dias_ate_assinatura"]
        for i in concluidos
        if i["dias_ate_assinatura"] is not None and (i.get("n_prorrogacoes") or 0) == 0
    ]
    multiplicador_com_prorrogacao = _multiplicador(
        atrasos_com_prorrogacao, atrasos_geral, "com_prorrogacao"
    )
    multiplicador_sem_prorrogacao = _multiplicador(
        atrasos_sem_prorrogacao, atrasos_geral, "sem_prorrogacao"
    )

    for item in abertos:
        prazo_efetivo = item.get("prazo_efetivo")
        item["dias_em_aberto"] = (hoje - prazo_efetivo).days if prazo_efetivo else None
        item["t_prazo"] = 0
        referencia = item.get("data_recebimento_gelic") or item.get("data_envio_gelic")
        dias_decorridos = (hoje - referencia).days if referencia else 0
        item["tempo_restante_p25"] = max(0, int(p25_geral) - dias_decorridos)
        item["tempo_restante_p75"] = max(0, int(p75_geral) - dias_decorridos)
        tem_prorrogacao = (item.get("n_prorrogacoes") or 0) >= 1
        item["multiplicadores"] = [
            multiplicador_com_prorrogacao if tem_prorrogacao else multiplicador_sem_prorrogacao
        ]

    resultado = prazos_mod.calcular(concluidos, abertos, hoje=hoje)

    # KPIs
    concluidos_com_prazo_original = [
        i for i in concluidos if i.get("data_prevista_conclusao") and i.get("data_assinatura_contrato")
    ]
    # "prazo original" = a 1ª previsão de conclusão da contratação;
    # "prazo vigente" = `prazo_efetivo` (a promessa vigente, COALESCE
    # prazo_vigente/prazo_entrega). Concluídos com dado suficiente em cada
    # base — denominador zero-safe (nunca número sem n).
    no_prazo_original = sum(
        1 for i in concluidos_com_prazo_original
        if i["data_assinatura_contrato"] <= i["data_prevista_conclusao"]
    )
    concluidos_com_prazo_vigente = [
        i for i in concluidos if i.get("prazo_efetivo") and i.get("data_assinatura_contrato")
    ]
    no_prazo_vigente = sum(
        1 for i in concluidos_com_prazo_vigente
        if i["data_assinatura_contrato"] <= i["prazo_efetivo"]
    )
    atrasos_positivos = [d for d in atrasos_geral if d > 0]
    atraso_mediano = statistics.median(atrasos_positivos) if atrasos_positivos else None
    itens_2_ou_mais_prorrogacoes = qs.filter(n_prorrogacoes__gte=2).count()

    kpis = [
        {
            "rotulo": "Cumprimento no prazo original",
            "valor": (
                percentual(round(no_prazo_original / len(concluidos_com_prazo_original) * 100, 1))
                if concluidos_com_prazo_original
                else "—"
            ),
            "apoio": f"n={len(concluidos_com_prazo_original)}",
            "icone": "fas fa-flag-checkered",
        },
        {
            "rotulo": "Cumprimento no prazo vigente",
            "valor": (
                percentual(round(no_prazo_vigente / len(concluidos_com_prazo_vigente) * 100, 1))
                if concluidos_com_prazo_vigente
                else "—"
            ),
            "apoio": f"n={len(concluidos_com_prazo_vigente)}",
            "icone": "fas fa-calendar-check",
        },
        {
            "rotulo": "Atraso mediano",
            "valor": f"{numero(atraso_mediano)} dias" if atraso_mediano is not None else "—",
            "apoio": f"n={len(atrasos_positivos)}",
            "icone": "fas fa-hourglass-half",
        },
        {
            "rotulo": "Itens com 2+ prorrogações",
            "valor": numero(itens_2_ou_mais_prorrogacoes),
            "icone": "fas fa-redo",
        },
    ]

    # Par — curva de sobrevivência (Kaplan-Meier).
    curva = resultado["sobrevivencia"]["geral"]["curva"]
    par_km = {
        "titulo": "Curva de sobrevivência (Kaplan-Meier)",
        "subtitulo": f"n={resultado['sobrevivencia']['geral']['n']} — dias desde o prazo original até a assinatura.",
        "grafico": {
            "id": "analise-prazos-grafico-km",
            "opcoes": graficos.linha(
                [str(p["t"]) for p in curva],
                {"Sobrevivência (%)": [float(p["s"] * 100) for p in curva]},
            ),
            "resumo": "Probabilidade de ainda não ter sido assinado a cada dia de atraso, geral.",
        },
        "tabela": graficos.tabela_dados(
            ["Dias", "Sobrevivência (%)", "Em risco", "Eventos"],
            [
                [str(p["t"]), percentual(round(float(p["s"]) * 100, 1)), numero(p["n_risco"]), numero(p["eventos"])]
                for p in curva
            ],
        ),
    }

    # Tabela de risco — item aberto, ordenada por score decrescente.
    mapa_processos = {i["item_pca"]: i["_processo"] for i in itens}
    linhas_risco = []
    for item_risco in sorted(resultado["risco"], key=lambda r: r["score"], reverse=True):
        processo = mapa_processos.get(item_risco["item_pca"])
        if processo is None:
            continue
        linhas_risco.append(
            {
                "processo": processo,
                "prorrogacoes": processo.n_prorrogacoes,
                "dias_ate_prazo": -( (hoje - processo.prazo_efetivo).days ) if processo.prazo_efetivo else None,
                "score_percentual": round(float(item_risco["score"]) * 100, 1),
                "faixa": item_risco["faixa"],
                "data_provavel_p25": item_risco["data_provavel"]["p25"],
                "data_provavel_p75": item_risco["data_provavel"]["p75"],
            }
        )

    trilha = navegacao.trilha_padrao(exercicio, "Prazos")

    # Contratos a vencer (Fase 38, spec §2-§4) — substitui a antiga seção de itens vincendos em
    # 90/180/365 dias (M07): itens com contrato e vigência informada,
    # independente de `situacao`/`tipo`, com destino em N+1 derivado por
    # `virada.destino`.
    # NÃO herda `queryset_filtrado`/`qs` (C05 — os filtros legados de
    # situação/estado/tipo daquela função contradizem o universo desta
    # seção, ver docstring de `apps/pca/servicos/contratos.py`).
    filtros = filtros_ativos(get)
    fc = _filtros_contratos(request)
    res = contratos_mod.contratos_a_vencer(
        exercicio,
        horizonte=fc["vence"],
        uos=filtros["uo"],
        renovacao=fc["renovacao"],
        destino=fc["destino"],
        grupo_destino=fc["grupo_destino"],
        hoje=hoje,
    )
    k = res.kpis
    paginador = Paginator(res.queryset, settings.DSGOV["ITENS_POR_PAGINA"])
    pagina = paginador.get_page(fc["pagina"])

    linhas_contratos = [
        {
            "processo": p,
            "destino": virada.Destino.por_chave(p.destino),
            # Rótulo/explicação com os anos no lugar de N/N+1 (29/09/2026).
            "destino_rotulo": virada.com_anos(virada.Destino.por_chave(p.destino).rotulo, res.exercicio_ano),
            "destino_explicacao": virada.com_anos(
                virada.Destino.por_chave(p.destino).explicacao, res.exercicio_ano
            ),
            "vencido": p.vigencia_fim < hoje,
            "inicio_futuro": p.vigencia_inicio is not None and p.vigencia_inicio > hoje,
            "acao_destino": "false" if p.renovacao_prevista else "true",
            "rotulo_acao": "Desmarcar renovação" if p.renovacao_prevista else "Marcar renovação",
            "classe_tag_destino": CLASSE_TAG_DESTINO[p.destino],
        }
        for p in pagina.object_list
    ]

    uos_texto = "todas as unidades"
    if filtros["uo"]:
        nomes_uo = list(
            Unidade.objects.filter(pk__in=filtros["uo"]).values_list("nome", flat=True)
        )
        if nomes_uo:
            uos_texto = ", ".join(nomes_uo)

    if res.exercicio_ano is not None:
        contexto_linha_contratos = (
            f"Exercício {res.exercicio_ano} · {uos_texto} · exercício seguinte: {res.exercicio_ano + 1}"
        )
        opcoes_vence_contratos = [
            ("todos", "Todos"),
            ("vencidos", "Vencidos"),
            ("90", "Até 90 dias"),
            ("180", "Até 180 dias"),
            ("365", "Até 365 dias"),
            ("N", f"Até 31/12/{res.exercicio_ano}"),
            ("N+1", f"Até 31/12/{res.exercicio_ano + 1}"),
        ]
    else:
        contexto_linha_contratos = "Nenhum exercício aberto."
        opcoes_vence_contratos = [
            ("todos", "Todos"),
            ("vencidos", "Vencidos"),
            ("90", "Até 90 dias"),
            ("180", "Até 180 dias"),
            ("365", "Até 365 dias"),
        ]

    base_texto_contratos = (
        "Base dos indicadores: exercício e unidades do recorte + filtros de "
        "vencimento e renovação (o filtro de destino recorta só a tabela)."
    )

    cards_contratos = [
        {
            "rotulo": "Itens com contrato",
            "valor": numero(k["total"]),
            "apoio": f"{moeda(k['soma_valor_mensal'])}/mês · {numero(k['sem_valor_mensal'])} sem valor mensal",
            "icone": "fas fa-file-contract",
            "url": _url_prazos(exercicio, filtros["uo"], vence=fc["vence"], renovacao=fc["renovacao"]),
        },
        {
            "rotulo": "Vencidos ou encerram em N",
            "valor": numero(k["encerramento_n"]),
            "apoio": "Vencidos exigem conferência; sem renovação prevista, encerram em N",
            "icone": "fas fa-exclamation-triangle",
            "url": _url_prazos(
                exercicio, filtros["uo"], vence=fc["vence"], renovacao=fc["renovacao"],
                grupo_destino="encerramento_n",
            ),
        },
        {
            "rotulo": "Renovação em N",
            "valor": numero(k["renovacao_n"]),
            "apoio": "Aditivo/renovação ainda a registrar; destino N+1 depende da nova vigência",
            "icone": "fas fa-sync-alt",
            "url": _url_prazos(
                exercicio, filtros["uo"], vence=fc["vence"], renovacao=fc["renovacao"],
                grupo_destino="renovacao_n",
            ),
        },
        {
            "rotulo": "Renovações em N+1",
            "valor": numero(k["renovacao_n1"]),
            "apoio": "Entram no PCA N+1 como Renovação",
            "icone": "fas fa-redo",
            "url": _url_prazos(
                exercicio, filtros["uo"], vence=fc["vence"], renovacao=fc["renovacao"],
                grupo_destino="renovacao_n1",
            ),
        },
        {
            "rotulo": "Vigentes em N+1",
            "valor": numero(k["vigente_n1"]),
            "apoio": "Entram no PCA N+1 como Vigente",
            "icone": "fas fa-check-circle",
            "url": _url_prazos(
                exercicio, filtros["uo"], vence=fc["vence"], renovacao=fc["renovacao"],
                grupo_destino="vigente_n1",
            ),
        },
    ]

    if fc["destino"] is None and fc["grupo_destino"] is None:
        total_contratos = k["total"]
    else:
        total_contratos = pagina.paginator.count

    contratos_contexto = {
        "contexto_linha": contexto_linha_contratos,
        "base_texto": base_texto_contratos,
        "kpis": k,
        "cards": [
            {**card, "rotulo": virada.com_anos(card["rotulo"], res.exercicio_ano),
             "apoio": virada.com_anos(card["apoio"], res.exercicio_ano)}
            for card in cards_contratos
        ],
        "opcoes_vence": opcoes_vence_contratos,
        "opcoes_renovacao": [("todas", "Todas"), ("sim", "Sim"), ("nao", "Não")],
        "opcoes_destino": [("todos", "Todos")]
        + [(d.chave, virada.com_anos(d.rotulo, res.exercicio_ano)) for d in virada.Destino],
        "ano_seguinte": res.exercicio_ano + 1 if res.exercicio_ano is not None else None,
        "destino_exibicao": fc["destino"] or "todos",
        "selecionado": fc,
        "pagina": pagina,
        "linhas": linhas_contratos,
        "total": total_contratos,
        "inicio": pagina.start_index(),
        "fim": pagina.end_index(),
        "uos": filtros["uo"],
    }

    contexto = {
        "exercicio": exercicio,
        "trilha": trilha,
        "kpis": kpis,
        "lead_time_etapas": lead_time_etapas,
        "lead_time_por_modalidade": resultado["lead_time"]["por_modalidade"],
        "par_km": par_km,
        "linhas_risco": linhas_risco,
        "contratos": contratos_contexto,
        "pode_editar": request.user.has_perm("pca.editar_pca"),
        "pode_gerar_n1": _pode_gerar_n1(request.user) if exercicio else False,
        "ano_n1": exercicio.ano + 1 if exercicio else None,
    }
    return render(request, "pca/analise_prazos.html", contexto)


@require_POST
@permission_required("pca.ver_analises", raise_exception=True)
@permission_required("pca.view_acompanhamento", raise_exception=True)
@permission_required("pca.editar_pca", raise_exception=True)
def alternar_renovacao_view(request, ano, item_pca):
    """03/04 (mitigate) — NUNCA lê um parâmetro de URL de retorno
    do POST nem o cabeçalho de origem da requisição; reconstrói o
    redirect a partir dos ocultos validados pelos MESMOS validadores dos
    filtros GET
    (`filtros_ativos`/allowlists de `contratos_mod`/`virada`/inteiro ≥ 1).
    Fase 38 (spec §5): a permissão exige a
    dupla de leitura da tela (`pca.ver_analises` + `pca.view_acompanhamento`)
    MAIS `pca.editar_pca`; `destino` (booleano estrito, só "true"/"false")
    ausente/inválido vira 400 SEM gravação, ANTES de qualquer
    `get_object_or_404`; quando o novo destino faz o item sair do recorte
    de `renovacao`/`destino_filtro`/`grupo_destino` corrente, os filtros
    são preservados no redirect e uma mensagem explica a saída com um
    link seguro (`reverse`+`urlencode` de valores validados) para
    removê-los (C02)."""
    valor = request.POST.get("destino")
    if valor not in ("true", "false"):
        return HttpResponseBadRequest("Parâmetro 'destino' inválido: use true ou false.")

    processo = get_object_or_404(Processo, exercicio__ano=ano, item_pca=item_pca)
    novo = valor == "true"
    try:
        services.alternar_renovacao_prevista(
            processo_id=processo.pk, usuario=request.user, renovacao_prevista=novo
        )
    except services.ExercicioFechado as fechado:
        messages.error(request, str(fechado))
        return redirect(_url_prazos(fechado.exercicio, [], vence="todos"))
    hoje = localdate()
    destino_novo = (
        virada.destino(processo.vigencia_fim, novo, ano, hoje)
        if processo.vigencia_fim
        else None
    )
    messages.success(
        request,
        f"Item {item_pca}: renovação prevista {'marcada' if novo else 'desmarcada'}. "
        f"Destino em {ano + 1}: {virada.com_anos(destino_novo.rotulo, ano) if destino_novo else '—'}.",
    )

    post = request.POST
    filtros_post = filtros_ativos(post)
    exercicio_redirect = filtros_post["exercicio"] if exercicio_explicito(post) else None
    uos_redirect = filtros_post["uo"]

    vence_redirect = (
        post.get("vence") if post.get("vence") in contratos_mod.VENCE_OPCOES else "todos"
    )
    renovacao_redirect = (
        post.get("renovacao")
        if post.get("renovacao") in contratos_mod.RENOVACAO_OPCOES
        else "todas"
    )
    destino_filtro_redirect = (
        post.get("destino_filtro")
        if post.get("destino_filtro") in virada.CHAVES_DESTINO
        else None
    )
    grupo_destino_redirect = (
        post.get("grupo_destino")
        if destino_filtro_redirect is None and post.get("grupo_destino") in virada.GRUPOS_DESTINO
        else None
    )
    pagina_bruta = post.get("pagina")
    pagina_redirect = None
    if (
        pagina_bruta is not None
        and pagina_bruta.isdecimal()
        and len(pagina_bruta) <= 6
        and int(pagina_bruta) >= 1
    ):
        pagina_redirect = int(pagina_bruta)

    saiu_do_recorte = (
        (renovacao_redirect == "sim" and not novo)
        or (renovacao_redirect == "nao" and novo)
        or (
            destino_filtro_redirect is not None
            and destino_novo is not None
            and destino_novo.chave != destino_filtro_redirect
        )
        or (
            grupo_destino_redirect is not None
            and destino_novo is not None
            and destino_novo not in virada.GRUPOS_DESTINO[grupo_destino_redirect]
        )
    )
    if saiu_do_recorte:
        url_sem_filtro = _url_prazos(
            exercicio_redirect, uos_redirect, vence=vence_redirect, pagina=pagina_redirect
        )
        messages.warning(
            request,
            format_html(
                "O item deixou de atender aos filtros atuais (renovação/destino). "
                '<a href="{}">Remover esses filtros</a>',
                url_sem_filtro,
            ),
        )

    return redirect(
        _url_prazos(
            exercicio_redirect,
            uos_redirect,
            vence=vence_redirect,
            renovacao=renovacao_redirect,
            destino=destino_filtro_redirect,
            grupo_destino=grupo_destino_redirect,
            pagina=pagina_redirect,
        )
    )
