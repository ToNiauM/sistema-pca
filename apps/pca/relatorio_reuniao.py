"""Relatório da reunião — o documento que a equipe junta ao processo do PCA no SEI.

Monta, para uma reunião de acompanhamento (a aberta, por padrão), tudo o que o modelo aprovado em
15/10/2026 mostra: cabeçalho, indicadores da reunião, movimentação do período, situação do PCA,
registros feitos na reunião, detalhamento da movimentação, solicitações das unidades (Fase 43) e dois anexos (resumo por unidade e todos
os processos em ordem de item). Nenhuma regra de negócio nova: reaproveita o motor do relatório de
movimentação (`montar_relatorio`, histórico em lote, apuração de compromissos), o resumo por unidade
(`calcular_resumo_uo`) e os totais financeiros do Início — os números daqui nunca divergem das telas.

Os gráficos são colunas (verticais ou empilhadas) e saem prontos para SVG, com coordenadas absolutas no
viewBox de 604 px (16 cm a 1:1 na folha A4): a casca DSGov proíbe `style` inline, então o template só
desenha, e a geometria (inclusive o rótulo inclinado quando os nomes não cabem na fatia da coluna) mora em
`_grafico_colunas`.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Min
from django.utils import timezone

from apps.catalogo.models import InstrumentoContratual, Modalidade, Unidade
from apps.pca import graficos_pca
from apps.pca.filtros import NOMES_MES
from apps.pca.models import Acompanhamento, Estado, Processo, Reuniao, Situacao, SituacaoReuniao
from apps.pca.relatorio_movimentacao import (
    CAMPOS_ALTERACOES,
    FRASES_CAMPO,
    _contexto_compromissos_em_lote,
    _historico_ate_por_processo,
    _limites_do_dia,
    _reuniao_id_valido,
    apurar_situacao_compromisso,
    consolidar_mudancas,
    formatar_valor_campo,
    montar_relatorio,
    mudancas_no_periodo,
    resolver_periodo_relatorio,
)
from apps.pca.resumo_uo import calcular_resumo_uo
from core.templatetags.dsgov import data_br, moeda

# Largura do viewBox dos gráficos (px CSS): a folha inteira (16 cm úteis) a 1:1.
LARGURA_GRAFICO = 604
# Acima disso, as unidades menores se juntam numa coluna "Outras N unidades".
MAX_COLUNAS_UNIDADES = 20
# Gráficos de colunas (px do viewBox): TOPO reserva o espaço do total em cima da coluna mais alta; MARGEM é a
# folga lateral; LARGURA_CARACTERE estima a largura de um caractere a 9 pt (com folga para a Liberation Sans,
# a substituta da Calibri fora do Windows); ZONA_* são as faixas de rótulo e de legenda sob o eixo.
TOPO = 20
MARGEM = 8
LARGURA_CARACTERE = 7.0
ALTURA_TEXTO = 12  # 9 pt em px: a caixa do rótulo inclinado também se estende para a esquerda por essa altura
ZONA_ROTULO = 22
ZONA_LEGENDA = 26
ALTURA_MINIMA = 1.5
SEN_45 = 0.71

ABREV_MES_ABNT = {1: "jan.", 2: "fev.", 3: "mar.", 4: "abr.", 5: "maio", 6: "jun.", 7: "jul.", 8: "ago.",
                  9: "set.", 10: "out.", 11: "nov.", 12: "dez."}

# Campos já mostrados na coluna "contratação" das concluídas — não repetem como alteração.
CAMPOS_CONTRATO = {
    "modalidade", "numero_contratacao", "numero_arp", "instrumento_contratual",
    "numero_instrumento_contratual", "valor_contratado", "fornecedor_cnpj", "fornecedor_razao_social",
    "data_assinatura_contrato", "vigencia_inicio", "vigencia_fim",
}
# Agrupamento das "Outras alterações" por tipo (ordem de leitura).
GRUPOS_ALTERACAO = (
    ("Dados do contrato", CAMPOS_CONTRATO),
    ("Planejamento", {"valor_estimado", "mes_previsto", "unidade_organizacional"}),
    ("Mudança de situação", {"situacao"}),
    ("Publicação", {"data_lancamento_spw", "data_lancamento_wordpress", "data_lancamento_dados_abertos"}),
)

# Evento gravado pela importação da planilha ("Reunião de 28/07/2026") não é registro de conteúdo.
_RE_EVENTO_GENERICO = re.compile(r"^\s*Reuni[ãa]o de \d{2}/\d{2}/\d{4}\.?\s*$")


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------


def _plural(n, singular, plural):
    return singular if n == 1 else plural


def _reais(valor):
    """Valor em reais sem o "R$" (o cabeçalho da coluna já diz a unidade)."""
    if valor is None:
        return ".."
    return moeda(valor).replace("R$", "").strip()


def _milhoes(valor):
    return f"{(Decimal(valor or 0) / Decimal(1_000_000)):.1f}".replace(".", ",")


def _pct_txt(numerador, denominador):
    if not denominador:
        return "—"
    return f"{Decimal(numerador) / Decimal(denominador) * 100:.1f}".replace(".", ",") + "%"


def _fmt(x):
    # Ponto decimal fixo: o valor vai para atributo SVG, nunca pela localização do template.
    return f"{x:.2f}"


def data_extenso(d):
    return f"{d.day} de {NOMES_MES[d.month].lower()} de {d.year}"


def data_abnt(d):
    return f"{d.day} {ABREV_MES_ABNT[d.month]} {d.year}"


def _capfirst(texto):
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]


def _rotulo_campo(campo):
    return _capfirst(FRASES_CAMPO[campo][0])


# ---------------------------------------------------------------------------
# Gráficos de colunas (geometria pronta para SVG)
# ---------------------------------------------------------------------------


def _grafico_colunas(colunas, *, largura=LARGURA_GRAFICO, altura_area, fracao, legenda=None):
    """Geometria completa de um gráfico de colunas (verticais, simples ou empilhadas) em SVG.

    `colunas` = lista de dicts com `rotulo` (texto sob a coluna), `segmentos` (pares (valor, classe CSS), de
    baixo para cima) e `valor` (texto do total, em cima). Todas as colunas usam a mesma escala (a maior soma
    ocupa `altura_area`); a largura de cada uma é `fracao` da sua fatia do eixo. Quando algum rótulo não cabe
    reto na fatia, o gráfico inteiro inclina os rótulos a 45° (terminando sob a coluna) e a margem esquerda
    cresce o bastante para que nenhum cruze o início do desenho. Todo número sai de `_fmt` (ponto decimal):
    vai para atributo SVG, nunca pela localização do template.
    """
    n = len(colunas)
    base_y = TOPO + altura_area
    totais = [sum(float(valor or 0) for valor, _ in c["segmentos"]) for c in colunas]
    maximo = max(totais, default=0)
    escala = altura_area / maximo if maximo else 0
    maior_rotulo = max((len(c["rotulo"]) for c in colunas), default=0)

    margem_esq = MARGEM
    fatia = (largura - margem_esq - MARGEM) / n if n else 0
    inclinado = any(len(c["rotulo"]) * LARGURA_CARACTERE > fatia - 4 for c in colunas)
    if inclinado:
        zona_rotulo = math.ceil(maior_rotulo * LARGURA_CARACTERE * SEN_45) + 16
        # Cada rótulo se estende para a esquerda por (caracteres × largura + altura do texto) × 0,71 a partir do
        # centro da sua coluna (a altura entra porque o topo da caixa do texto, girada, aponta para a esquerda):
        # margem_esq + (largura - margem_esq - MARGEM) × (i + 0,5) / n >= extensão (+ 1 de folga).
        for i, c in enumerate(colunas):
            extensao = (len(c["rotulo"]) * LARGURA_CARACTERE + ALTURA_TEXTO) * SEN_45 + 1
            parte = (i + 0.5) / n
            precisa = (extensao - (largura - MARGEM) * parte) / (1 - parte)
            margem_esq = max(margem_esq, precisa)
        fatia = (largura - margem_esq - MARGEM) / n
    else:
        zona_rotulo = ZONA_ROTULO

    saida = []
    for i, c in enumerate(colunas):
        centro = margem_esq + fatia * (i + 0.5)
        largura_coluna = fatia * fracao
        y = base_y
        segmentos = []
        for valor, classe in c["segmentos"]:
            if not valor:
                continue
            altura = max(float(valor) * escala, ALTURA_MINIMA)
            y -= altura
            segmentos.append({
                "x": _fmt(centro - largura_coluna / 2), "y": _fmt(y), "w": _fmt(largura_coluna), "h": _fmt(altura),
                "classe": classe,
            })
        rotulo_y = base_y + (10 if inclinado else 14)
        saida.append({
            "rotulo": c["rotulo"], "valor": c["valor"], "x": _fmt(centro), "y_valor": _fmt(y - 5),
            "rotulo_x": _fmt(centro), "rotulo_y": _fmt(rotulo_y),
            "transform": f"rotate(-45.00 {_fmt(centro)} {_fmt(rotulo_y)})" if inclinado else "",
            "segmentos": segmentos,
        })
    altura_total = TOPO + altura_area + zona_rotulo + (ZONA_LEGENDA if legenda else 6)
    return {
        "largura": _fmt(largura),
        "altura": _fmt(altura_total),
        "base_y": _fmt(base_y),
        "eixo_x1": _fmt(margem_esq),
        "eixo_x2": _fmt(largura - MARGEM),
        "inclinado": inclinado,
        "colunas": saida,
        "legenda": legenda or [],
        "legenda_x": _fmt((margem_esq + largura - MARGEM) / 2),
        "legenda_y": _fmt(base_y + zona_rotulo + 14),
    }


def _colunas_por_unidade(linhas):
    """Colunas do gráfico de unidades a partir das linhas do resumo: `(colunas, demais)`.

    Só unidades com itens ativos, da maior para a menor (empate pelo nome). Até `MAX_COLUNAS_UNIDADES` todas
    aparecem; acima disso, as maiores ficam e as demais se juntam numa coluna "Outras N unidades" (as linhas
    juntadas voltam em `demais`, para a nota da figura). Cada coluna empilha concluído, em tramitação e a
    entregar à Gelic (no prazo + atrasado); o total em cima é o número de itens ativos."""
    unidades = sorted((l for l in linhas if l["ativos"]), key=lambda l: (-l["ativos"], l["uo"]))
    visiveis, demais = unidades, []
    if len(unidades) > MAX_COLUNAS_UNIDADES:
        visiveis, demais = unidades[: MAX_COLUNAS_UNIDADES - 1], unidades[MAX_COLUNAS_UNIDADES - 1:]

    def coluna(rotulo, grupo):
        return {
            "rotulo": rotulo,
            "segmentos": [
                (sum(l["concluido"] for l in grupo), "abnt-cor-1"),
                (sum(l["em_tramitacao_ativos"] for l in grupo), "abnt-cor-2"),
                (sum(l["no_prazo_ativos"] + l["atrasado_ativos"] for l in grupo), "abnt-cor-3"),
            ],
            "valor": str(sum(l["ativos"] for l in grupo)),
        }

    colunas = [coluna(l["uo"], [l]) for l in visiveis]
    if demais:
        colunas.append(coluna(f"Outras {len(demais)} unidades", demais))
    return colunas, demais


def _referencias(rotulo, numeros):
    """"Tabela 3", "Tabelas 3 e 4", "Tabelas 3 a 5" — para o texto corrido citar o que existe."""
    numeros = sorted(n for n in numeros if n)
    if not numeros:
        return ""
    if len(numeros) == 1:
        return f"{rotulo} {numeros[0]}"
    if len(numeros) == 2:
        return f"{rotulo}s {numeros[0]} e {numeros[1]}"
    if numeros == list(range(numeros[0], numeros[-1] + 1)):
        return f"{rotulo}s {numeros[0]} a {numeros[-1]}"
    return f"{rotulo}s {', '.join(map(str, numeros[:-1]))} e {numeros[-1]}"


def _lista(nomes):
    nomes = list(nomes)
    if len(nomes) <= 1:
        return "".join(nomes)
    return f"{', '.join(nomes[:-1])} e {nomes[-1]}"


def periodo_por_extenso(de, ate):
    """"de 6 a 15 de outubro de 2026", "de 6 de setembro a 15 de outubro de 2026"..."""
    if de.year != ate.year:
        return f"de {data_extenso(de)} a {data_extenso(ate)}"
    if de.month != ate.month:
        return f"de {de.day} de {NOMES_MES[de.month].lower()} a {data_extenso(ate)}"
    if de.day == ate.day:
        return f"em {data_extenso(ate)}"
    return f"de {de.day} a {data_extenso(ate)}"


def periodo_curto(de, ate):
    """"6 a 15/10/2026", "6/9 a 15/10/2026", "6/9/2025 a 15/10/2026"."""
    if de.year != ate.year:
        return f"{data_br(de)} a {data_br(ate)}"
    if de.month != ate.month:
        return f"{de.day}/{de.month} a {data_br(ate)}"
    return f"{de.day} a {data_br(ate)}"


# Anexo I — as mesmas colunas da tela Resumo por unidade: (quantidade, percentual, abre grupo).
COLUNAS_ANEXO_RESUMO = (
    ("total_previsto", "percentual_no_pca", True),
    ("cancelados", "percentual_cancelados", False),
    ("ativos", "percentual_ativos", False),
    ("nova", "percentual_nova", True),
    ("renovacao", "percentual_renovacao", False),
    ("vigente", "percentual_vigente", False),
    ("concluido_meta", "percentual_concluido_meta", True),
    ("em_tramitacao", "percentual_em_tramitacao", False),
    ("no_prazo", "percentual_no_prazo", False),
    ("fora_prazo", "percentual_fora_prazo", False),
    ("concluido", "percentual_concluido", True),
)


def _pct_decimal(valor):
    return "" if valor is None else f"{valor:.1f}".replace(".", ",") + "%"


def _celulas_resumo(linha):
    return {
        "uo": linha["uo"],
        "celulas": [
            {"n": linha.get(chave) or 0, "pct": _pct_decimal(linha.get(pct)) if linha.get(chave) else "", "sep": sep}
            for chave, pct, sep in COLUNAS_ANEXO_RESUMO
        ],
    }


# ---------------------------------------------------------------------------
# Reunião e período
# ---------------------------------------------------------------------------


def resolver_reuniao(get, exercicio, *, hoje=None):
    """Reunião escolhida no GET (do mesmo exercício) > a aberta > a mais recente até hoje."""
    hoje = hoje or timezone.localdate()
    qs = Reuniao.objects.filter(exercicio=exercicio).select_related("condutor")
    reuniao_id = _reuniao_id_valido(get.get("reuniao"))
    if reuniao_id is not None:
        escolhida = qs.filter(pk=reuniao_id).first()
        if escolhida is not None:
            return escolhida
    aberta = qs.filter(situacao=SituacaoReuniao.ABERTA).order_by("-data").first()
    if aberta is not None:
        return aberta
    return qs.filter(data__lte=hoje).order_by("-data").first() or qs.order_by("-data").first()


def resolver_periodo(get, exercicio, reuniao, *, hoje=None):
    """Datas livres válidas > período da reunião (do dia seguinte à anterior até a data dela; se ela
    ainda está aberta, até hoje — "captar tudo na reunião aberta") > padrão do motor. Devolve
    `(de, ate, aviso)`."""
    hoje = hoje or timezone.localdate()
    if (get.get("de") and get.get("ate")) or reuniao is None:
        return resolver_periodo_relatorio(get, exercicio)
    anterior = (
        Reuniao.objects.filter(exercicio=exercicio, data__lt=reuniao.data).order_by("-data").first()
    )
    de = anterior.data + timedelta(days=1) if anterior else date(exercicio.ano, 1, 1)
    ate = reuniao.data
    if reuniao.situacao == SituacaoReuniao.ABERTA and hoje > ate:
        ate = hoje
    return de, ate, None


# ---------------------------------------------------------------------------
# Registros da reunião
# ---------------------------------------------------------------------------


def _apurar_registros(reuniao, *, hoje, contexto):
    """FATOS dos registros da reunião (JSON puro): grupos por unidade, nº de itens e a contagem de
    compromissos. Gráfico e destaques saem de `_apresentar_registros`."""
    vazio = {"grupos": [], "itens": 0, "cumpridos": 0, "repactuados": 0, "vencidos": 0}
    if reuniao is None:
        return vazio
    acompanhamentos = list(
        Acompanhamento.objects.filter(reuniao=reuniao)
        .select_related("processo", "processo__unidade_organizacional", "situacao")
        .order_by("processo__unidade_organizacional__nome", "processo__item_pca", "id")
    )
    if not acompanhamentos:
        return vazio
    por_processo = {}
    for acompanhamento in acompanhamentos:
        por_processo.setdefault(acompanhamento.processo_id, []).append(acompanhamento)
    anteriores = {}
    for acompanhamento in (
        Acompanhamento.objects.filter(
            processo_id__in=list(por_processo), prazo_prometido__isnull=False,
            referencia_data__lt=reuniao.data,
        )
        .exclude(reuniao=reuniao)
        .select_related("processo", "processo__unidade_organizacional", "reuniao")
        .order_by("processo_id", "-referencia_data", "-id")
    ):
        anteriores.setdefault(acompanhamento.processo_id, acompanhamento)

    grupos = {}
    contagem = {"cumpridos": 0, "repactuados": 0, "vencidos": 0}
    for registros in por_processo.values():
        processo = registros[0].processo
        ultimo = registros[-1]
        textos = []
        rotulo_situacao = str(ultimo.situacao) if ultimo.situacao_id else processo.get_situacao_display()
        for registro in registros:
            for texto in (registro.situacao_informada, registro.evento):
                texto = (texto or "").strip()
                if texto and not _RE_EVENTO_GENERICO.match(texto) and texto != rotulo_situacao and texto not in textos:
                    textos.append(texto)
        novo = next((r.prazo_prometido for r in reversed(registros) if r.prazo_prometido), None)
        anterior = anteriores.get(processo.pk)
        status = ""
        if novo and anterior and anterior.prazo_prometido != novo:
            prazo = f"{data_br(anterior.prazo_prometido)} → {data_br(novo)}"
            status = "repactuado"
            contagem["repactuados"] += 1
        elif novo:
            prazo = data_br(novo)
            status = "mantido" if anterior else "assumido nesta reunião"
        elif anterior:
            codigo, rotulo = apurar_situacao_compromisso(anterior, hoje=hoje, contexto=contexto)
            prazo = data_br(anterior.prazo_prometido)
            status = rotulo
            if codigo == "cumprido":
                contagem["cumpridos"] += 1
            elif codigo == "vencido":
                contagem["vencidos"] += 1
        else:
            prazo = "–"
        uo = processo.unidade_organizacional.nome
        grupos.setdefault(uo, []).append({
            "item": processo.item_pca,
            "objeto": _capfirst(processo.descricao_objeto),
            "situacao": rotulo_situacao,
            "registro": " ".join(textos) if textos else "",
            "prazo": prazo,
            "status": status,
        })
    lista = [{"uo": uo, "linhas": linhas} for uo, linhas in sorted(grupos.items())]
    return {"grupos": lista, "itens": len(por_processo), **contagem}


def _apresentar_registros(fatos):
    lista = fatos["grupos"]
    por_uo = sorted(((len(g["linhas"]), g["uo"]) for g in lista), key=lambda t: (-t[0], t[1]))
    maximo = por_uo[0][0] if por_uo else 0
    lideres = [uo for n, uo in por_uo if n == maximo] if maximo > 1 else []
    return {"grupos": lista, "itens": fatos["itens"], "unidades": len(lista),
            "lideres": lideres, "maior": maximo, "cumpridos": fatos["cumpridos"],
            "repactuados": fatos["repactuados"], "vencidos": fatos["vencidos"]}


# ---------------------------------------------------------------------------
# Mudanças estruturadas do período (para as colunas e as "outras alterações")
# ---------------------------------------------------------------------------


def _mudancas(processo, *, de, ate, historico):
    """`{campo: (de, para, data, trilha)}` — o mesmo motor de diff do relatório de movimentação."""
    por_campo = mudancas_no_periodo(
        processo, de=de, ate=ate, campos=CAMPOS_ALTERACOES, registros=historico.get(processo.pk, [])
    )
    resultado = {}
    for campo, mudancas in por_campo.items():
        if not mudancas:
            continue
        valor_de, valor_para, trilha = consolidar_mudancas(mudancas)
        resultado[campo] = (valor_de, valor_para, max(m.data for m in mudancas), trilha)
    return resultado


def _vazio(campo, valor, mapas_fk):
    return valor in (None, "") or formatar_valor_campo(campo, valor, mapas_fk=mapas_fk) in (
        "—", "sem mês previsto definido"
    )


def _texto_mudanca(campo, valor_de, valor_para, quando, trilha, mapas_fk):
    rotulo = _rotulo_campo(campo)
    de_txt = formatar_valor_campo(campo, valor_de, mapas_fk=mapas_fk)
    para_txt = formatar_valor_campo(campo, valor_para, mapas_fk=mapas_fk)
    data_txt = data_br(timezone.localtime(quando).date())
    if de_txt == para_txt and trilha:
        passos = [formatar_valor_campo(campo, trilha[0][0], mapas_fk=mapas_fk)]
        passos += [formatar_valor_campo(campo, passo[1], mapas_fk=mapas_fk) for passo in trilha]
        return f"{rotulo}: {' → '.join(passos)} ({data_txt})"
    if _vazio(campo, valor_de, mapas_fk):
        return f"{rotulo}: {para_txt} ({data_txt})"
    return f"{rotulo}: {de_txt} → {para_txt} ({data_txt})"


def _textos(mudancas, campos, mapas_fk, *, ignorar_preenchimento=False):
    """Linhas "Rótulo: de → para (data)" dos `campos`; início e fim de vigência viram uma linha só."""
    linhas = []
    escolhidos = [c for c in CAMPOS_ALTERACOES if c in campos and c in mudancas]
    if ignorar_preenchimento:
        escolhidos = [c for c in escolhidos if not _vazio(c, mudancas[c][0], mapas_fk)]
    if "vigencia_inicio" in escolhidos and "vigencia_fim" in escolhidos:
        ini, fim = mudancas["vigencia_inicio"], mudancas["vigencia_fim"]
        quando = data_br(timezone.localtime(max(ini[2], fim[2])).date())
        antes = f"{data_br(ini[0])} a {data_br(fim[0])}" if ini[0] and fim[0] else ""
        depois = f"{data_br(ini[1])} a {data_br(fim[1])}"
        linhas.append(f"Vigência: {antes + ' → ' if antes else ''}{depois} ({quando})")
        escolhidos = [c for c in escolhidos if c not in ("vigencia_inicio", "vigencia_fim")]
    for campo in escolhidos:
        valor_de, valor_para, quando, trilha = mudancas[campo]
        linhas.append(_texto_mudanca(campo, valor_de, valor_para, quando, trilha, mapas_fk))
    return linhas


def _campo_e_texto(texto):
    """"Situação: A → B (data)" → {"campo": "Situação", "texto": "A → B (data)"} (o campo sai em negrito)."""
    campo, _, resto = texto.partition(": ")
    return {"campo": campo, "texto": resto} if resto else {"campo": "", "texto": texto}


def _datas_transicao(exercicio, filtro, inicio, fim):
    """`{processo_id: data local}` da PRIMEIRA vez que o history mostra `filtro` dentro do período."""
    linhas = (
        Processo.history.filter(exercicio=exercicio, **filtro).values("id").annotate(desde=Min("history_date"))
    )
    return {
        linha["id"]: timezone.localtime(linha["desde"]).date()
        for linha in linhas
        if inicio <= linha["desde"] <= fim
    }


# ---------------------------------------------------------------------------
# Apuração (FATOS) e apresentação (o que o template recebe)
# ---------------------------------------------------------------------------
#
# (decisão do usuário): o que se congela são os FATOS, não a página. `apurar_relatorio`
# devolve só dados — linhas, somas, contagens, datas ISO, ids e nomes, textos de linha já compostos a
# partir do histórico — em JSON puro (nada de instância de modelo nem Decimal: valores em str). Gráficos,
# numeração de tabelas e figuras, parágrafos compostos, "R$" com espaço fixo etc. saem de
# `apresentar_relatorio(fatos)`, sempre com o código ATUAL: melhoria visual vale também para reunião
# antiga; números, itens e textos de linha nunca mudam.

VERSAO_FATOS = 1


def _d(valor):
    """Decimal (ou None) → str (ou None) para os fatos."""
    return None if valor is None else str(valor)


def _fatos_resumo(linha):
    return {chave: (str(valor) if isinstance(valor, Decimal) else valor) for chave, valor in linha.items()}


def _resumo_de_fatos(linha):
    return {
        chave: (Decimal(valor) if chave.startswith("percentual_") and isinstance(valor, str) else valor)
        for chave, valor in linha.items()
    }


def apurar_relatorio(*, exercicio, reuniao, de, ate, usuario, hoje=None):
    """Os FATOS do relatório (JSON puro) sobre o banco ativo. `reuniao=None` = relatório de período
    (título, introdução e seções sem a reunião)."""
    hoje = hoje or timezone.localdate()
    agora = timezone.now()
    inicio, fim = _limites_do_dia(de, ate)
    base = Processo.objects.para_listagem().filter(exercicio=exercicio)
    mapas_fk = {
        "unidade_organizacional": dict(Unidade.objects.values_list("id", "nome")),
        "modalidade": dict(Modalidade.objects.values_list("id", "nome")),
        "instrumento_contratual": dict(InstrumentoContratual.objects.values_list("id", "nome")),
    }
    historico = _historico_ate_por_processo(exercicio, agora)
    contexto = _contexto_compromissos_em_lote(exercicio, historico_por_processo=historico)

    movimentacao = montar_relatorio(exercicio=exercicio, de=de, ate=ate, usuario=usuario)
    blocos = {bloco.chave: bloco for bloco in movimentacao.blocos}
    mudancas = {}
    for bloco in movimentacao.blocos:
        for item in bloco.itens:
            mudancas[item.processo.pk] = _mudancas(item.processo, de=de, ate=ate, historico=historico)

    # 5.1 Contratações concluídas — dados do contrato numa coluna.
    concluiu_em = _datas_transicao(exercicio, {"situacao": Situacao.CONCLUIDO}, inicio, fim)
    concluidas = []
    for item in blocos["concluidos"].itens:
        p = item.processo
        partes = [p.unidade_organizacional.nome]
        if p.fornecedor_razao_social or p.fornecedor_cnpj:
            fornecedor = p.fornecedor_razao_social or ""
            if p.fornecedor_cnpj:
                fornecedor = f"{fornecedor}, CNPJ {p.fornecedor_cnpj}" if fornecedor else f"CNPJ {p.fornecedor_cnpj}"
            partes.append(fornecedor)
        contratacao = " ".join(
            filter(None, [mapas_fk["modalidade"].get(p.modalidade_id), f"nº {p.numero_contratacao}" if p.numero_contratacao else ""])
        )
        if contratacao:
            partes.append(contratacao)
        instrumento = mapas_fk["instrumento_contratual"].get(p.instrumento_contratual_id) or ""
        if p.numero_instrumento_contratual:
            instrumento = f"{instrumento or 'Instrumento'} nº {p.numero_instrumento_contratual}"
        if p.data_assinatura_contrato:
            instrumento = f"{instrumento or 'Contrato'} assinado em {data_br(p.data_assinatura_contrato)}"
        if instrumento:
            partes.append(instrumento)
        if p.vigencia_inicio and p.vigencia_fim:
            partes.append(f"vigência de {data_br(p.vigencia_inicio)} a {data_br(p.vigencia_fim)}")
        if p.pk in concluiu_em:
            partes.append(f"concluído em {data_br(concluiu_em[p.pk])}")
        extras = _textos(mudancas.get(p.pk, {}), set(CAMPOS_ALTERACOES) - CAMPOS_CONTRATO - {"situacao"}, mapas_fk,
                         ignorar_preenchimento=True)
        concluidas.append({
            "item": p.item_pca, "objeto": _capfirst(p.descricao_objeto), "detalhe": " · ".join(partes),
            "extras": extras, "estimado": _d(p.valor_estimado), "contratado": _d(p.valor_contratado),
        })

    # 5.2 Itens incluídos — o preenchimento inicial não conta como alteração.
    inclusoes = []
    for item in blocos["inclusoes"].itens:
        p = item.processo
        inclusoes.append({
            "item": p.item_pca, "uo": p.unidade_organizacional.nome, "objeto": _capfirst(p.descricao_objeto),
            "mes": p.mes_previsto, "valor": _d(p.valor_estimado),
            "extras": _textos(mudancas.get(p.pk, {}), set(CAMPOS_ALTERACOES), mapas_fk, ignorar_preenchimento=True),
        })

    # 5.3 Itens excluídos.
    cancelou_em = _datas_transicao(exercicio, {"estado": Estado.CANCELADO}, inicio, fim)
    exclusoes = []
    for item in blocos["exclusoes"].itens:
        p = item.processo
        if p.pk in cancelou_em:
            motivo = f"Cancelado em {data_br(cancelou_em[p.pk])}."
        else:
            motivo = _capfirst(item.frase_principal.split("): ", 1)[-1])
        antes = _textos(mudancas.get(p.pk, {}), set(CAMPOS_ALTERACOES), mapas_fk, ignorar_preenchimento=True)
        exclusoes.append({
            "item": p.item_pca, "uo": p.unidade_organizacional.nome, "objeto": _capfirst(p.descricao_objeto),
            "motivo": motivo, "extras": antes, "valor": _d(p.valor_estimado),
        })

    # 5.4 Encaminhados à Gelic.
    gelic = [
        {
            "item": item.processo.item_pca, "uo": item.processo.unidade_organizacional.nome,
            "objeto": _capfirst(item.processo.descricao_objeto),
            "data": item.processo.data_envio_gelic.isoformat() if item.processo.data_envio_gelic else None,
            "extras": _textos(mudancas.get(item.processo.pk, {}), set(CAMPOS_ALTERACOES), mapas_fk,
                              ignorar_preenchimento=True),
        }
        for item in blocos["iniciados"].itens
    ]

    # 5.5 Outras alterações — agrupadas por tipo; um item pode aparecer em mais de um grupo.
    alteracoes = []
    for titulo, campos in GRUPOS_ALTERACAO:
        linhas = []
        for item in blocos["alteracoes"].itens:
            p = item.processo
            textos = _textos(mudancas.get(p.pk, {}), campos, mapas_fk)
            if textos:
                linhas.append({"item": p.item_pca, "uo": p.unidade_organizacional.nome,
                               "objeto": _capfirst(p.descricao_objeto),
                               "mudancas": [_campo_e_texto(texto) for texto in textos]})
        if linhas:
            alteracoes.append({"tipo": titulo, "linhas": linhas})

    # 5.6 Compromissos assumidos em reunião no período (quando o motor encontrou algum).
    adiados = [
        {"item": item.processo.item_pca, "uo": item.processo.unidade_organizacional.nome,
         "objeto": _capfirst(item.processo.descricao_objeto),
         "frases": [f.split("): ", 1)[-1] if f.startswith("Item ") else f for f in [item.frase_principal, *item.frases_extra]]}
        for item in blocos["adiados"].itens
    ]

    # 6 Solicitações das unidades (Fase 43) — o domínio mora em `apps.solicitacoes`, que depende
    # de `apps.pca`: o import é local para não fechar um ciclo.
    from apps.solicitacoes.relatorio import montar_bloco as montar_solicitacoes

    solicitacoes = montar_solicitacoes(exercicio=exercicio, inicio=inicio, fim=fim)

    # Situação do PCA — a MESMA conta do Resumo por unidade (anexo I), para o documento não se contradizer.
    linhas_uo, total_uo = calcular_resumo_uo(base)
    financeiro = graficos_pca.calcular_totais_financeiros(base)

    registros = _apurar_registros(reuniao, hoje=hoje, contexto=contexto)

    # Anexo II — todos os processos do exercício em ordem de item.
    processos = [
        {
            "item": p.item_pca, "objeto": _capfirst(p.descricao_objeto), "uo": p.unidade_organizacional.nome,
            "data": p.prazo_efetivo.isoformat() if p.prazo_efetivo else None,
            "situacao": "Cancelado" if p.estado == Estado.CANCELADO else (
                Situacao(p.situacao_efetiva).label if p.situacao_efetiva else "–"
            ),
        }
        for p in base.select_related("unidade_organizacional").order_by("item_pca")
    ]

    dados_reuniao = None
    if reuniao is not None:
        anterior = Reuniao.objects.filter(exercicio=exercicio, data__lt=reuniao.data).order_by("-data").first()
        dados_reuniao = {
            "id": reuniao.pk,
            "data": reuniao.data.isoformat(),
            "ordinal": Reuniao.objects.filter(exercicio=exercicio, data__lte=reuniao.data).count(),
            "anterior_data": anterior.data.isoformat() if anterior else None,
            "condutor": (reuniao.condutor.get_full_name() or reuniao.condutor.email) if reuniao.condutor_id else "",
            "em_andamento": reuniao.situacao == SituacaoReuniao.ABERTA,
        }

    return {
        "versao_fatos": VERSAO_FATOS,
        "exercicio": {"id": exercicio.pk, "ano": exercicio.ano},
        "reuniao": dados_reuniao,
        "de": de.isoformat(),
        "ate": ate.isoformat(),
        "hoje": hoje.isoformat(),
        "gerado_em": timezone.localtime(agora).isoformat(),
        "gerado_por": (usuario.get_full_name() or usuario.email) if usuario else "Sistema PCA CFC",
        "concluidas": concluidas,
        "inclusoes": {
            "contagem": blocos["inclusoes"].contagem, "soma_valor": _d(blocos["inclusoes"].soma_valor or Decimal(0)),
            "linhas": inclusoes,
        },
        "exclusoes": {
            "contagem": blocos["exclusoes"].contagem, "soma_valor": _d(blocos["exclusoes"].soma_valor or Decimal(0)),
            "linhas": exclusoes,
        },
        "iniciados": {"contagem": blocos["iniciados"].contagem, "linhas": gelic},
        "alteracoes": {"contagem": blocos["alteracoes"].contagem, "grupos": alteracoes},
        "adiados": adiados,
        "houve_movimentacao": any(blocos[c].itens for c in blocos),
        "solicitacoes": solicitacoes,
        "resumo_uo": {"linhas": [_fatos_resumo(l) for l in linhas_uo], "total": _fatos_resumo(total_uo)},
        "financeiro": {
            "estimado": _d(financeiro["estimado"] or Decimal(0)),
            "contratado": _d(financeiro["contratado"] or Decimal(0)),
        },
        "registros": registros,
        "processos": processos,
    }


def apresentar_relatorio(fatos):
    """Contexto do documento (`pca/_relatorio_reuniao_documento.html`) a partir dos FATOS, com o código
    de apresentação atual. Não toca no banco."""
    hoje = date.fromisoformat(fatos["hoje"])
    de = date.fromisoformat(fatos["de"])
    ate = date.fromisoformat(fatos["ate"])
    exercicio = SimpleNamespace(pk=fatos["exercicio"]["id"], ano=fatos["exercicio"]["ano"])
    fr = fatos["reuniao"]
    reuniao = None
    ordinal = None
    anterior_data = None
    condutor = ""
    em_andamento = False
    if fr is not None:
        data_da_reuniao = date.fromisoformat(fr["data"])
        reuniao = SimpleNamespace(pk=fr["id"], data=data_da_reuniao, ordinal=fr["ordinal"], condutor=fr["condutor"],
                                  em_andamento=fr["em_andamento"])
        ordinal = fr["ordinal"]
        anterior_data = date.fromisoformat(fr["anterior_data"]) if fr["anterior_data"] else None
        condutor = fr["condutor"]
        em_andamento = fr["em_andamento"]

    # 5.1 Concluídas — maior valor contratado primeiro.
    concluidas = []
    for c in fatos["concluidas"]:
        estimado = Decimal(c["estimado"]) if c["estimado"] is not None else None
        contratado = Decimal(c["contratado"]) if c["contratado"] is not None else None
        concluidas.append({
            "item": c["item"], "objeto": c["objeto"], "detalhe": c["detalhe"], "extras": c["extras"],
            "estimado": estimado, "contratado": contratado,
            "estimado_txt": _reais(estimado), "contratado_txt": _reais(contratado),
        })
    concluidas.sort(key=lambda c: (-(c["contratado"] or 0), c["item"]))
    soma_estimado_conc = sum((c["estimado"] or Decimal(0)) for c in concluidas)
    soma_contratado_conc = sum((c["contratado"] or Decimal(0)) for c in concluidas)

    # 5.2 Incluídos — por mês previsto, maior valor primeiro.
    inclusoes = fatos["inclusoes"]
    por_mes = defaultdict(list)
    for l in inclusoes["linhas"]:
        valor = Decimal(l["valor"]) if l["valor"] is not None else None
        por_mes[l["mes"]].append({
            "item": l["item"], "uo": l["uo"], "objeto": l["objeto"], "valor": valor, "valor_txt": _reais(valor),
            "extras": l["extras"],
        })
    incluidos = []
    for mes in sorted(por_mes, key=lambda m: (m is None, m or 0)):
        linhas = sorted(por_mes[mes], key=lambda l: (-(l["valor"] or 0), l["item"]))
        subtotal = sum((l["valor"] or Decimal(0)) for l in linhas)
        incluidos.append({
            "mes": NOMES_MES.get(mes, "Sem mês previsto"), "linhas": linhas, "n": len(linhas),
            "subtotal_txt": _reais(subtotal),
        })
    soma_incluidos = Decimal(inclusoes["soma_valor"])
    n_inc = inclusoes["contagem"]

    # 5.3 Excluídos — maior valor primeiro.
    exclusoes = fatos["exclusoes"]
    excluidos = []
    for l in exclusoes["linhas"]:
        valor = Decimal(l["valor"]) if l["valor"] is not None else None
        excluidos.append({
            "item": l["item"], "uo": l["uo"], "objeto": l["objeto"], "motivo": l["motivo"], "extras": l["extras"],
            "valor": valor, "valor_txt": _reais(valor),
        })
    excluidos.sort(key=lambda l: (-(l["valor"] or 0), l["item"]))
    soma_excluidos = Decimal(exclusoes["soma_valor"])

    # 5.4 Encaminhados à Gelic.
    gelic = [
        {"item": l["item"], "uo": l["uo"], "objeto": l["objeto"],
         "data": data_br(date.fromisoformat(l["data"]) if l["data"] else None), "extras": l["extras"]}
        for l in fatos["iniciados"]["linhas"]
    ]
    alteracoes = fatos["alteracoes"]["grupos"]
    adiados = fatos["adiados"]
    solicitacoes = fatos["solicitacoes"]
    contagem_gelic = fatos["iniciados"]["contagem"]
    contagem_alteracoes = fatos["alteracoes"]["contagem"]

    # Seções: a do relatório de período (sem reunião) não tem "Registros da reunião", e as seguintes sobem.
    secoes = {"movimentacao": 5 if reuniao else 4, "solicitacoes": 6 if reuniao else 5}
    mov = secoes["movimentacao"]

    # Tabela 1 — uma linha por movimentação; – zero, .. não se aplica.
    linhas_mov = [
        ("Contratações concluídas", len(concluidas), _reais(soma_estimado_conc) if concluidas else "–",
         _reais(soma_contratado_conc) if concluidas else "–", f"{mov}.1"),
        ("Itens incluídos no PCA", n_inc, _reais(soma_incluidos) if n_inc else "–", "..", f"{mov}.2"),
        ("Itens excluídos do PCA", exclusoes["contagem"], _reais(soma_excluidos) if exclusoes["contagem"] else "–", "..", f"{mov}.3"),
        ("Encaminhados à Gelic", contagem_gelic, "..", "..", f"{mov}.4"),
        ("Outras alterações", contagem_alteracoes, "..", "..", f"{mov}.5"),
    ]
    if adiados:
        linhas_mov.append(("Compromissos assumidos em reunião", len(adiados), "..", "..", f"{mov}.6"))
    tabela1 = [
        {"rotulo": r, "itens": n or "–", "estimado": e, "contratado": c, "secao": s}
        for r, n, e, c, s in linhas_mov
    ]

    linhas_uo = [_resumo_de_fatos(l) for l in fatos["resumo_uo"]["linhas"]]
    total_uo = _resumo_de_fatos(fatos["resumo_uo"]["total"])
    ativos = total_uo["ativos"]
    a_entregar = total_uo["no_prazo_ativos"] + total_uo["atrasado_ativos"]
    cartoes_situacao = [
        {"rotulo": "Concluído", "n": total_uo["concluido"], "classe": "abnt-cartao-1"},
        {"rotulo": "Em tramitação", "n": total_uo["em_tramitacao_ativos"], "classe": "abnt-cartao-2"},
        {"rotulo": "No prazo", "n": total_uo["no_prazo_ativos"], "classe": "abnt-cartao-3"},
        {"rotulo": "Atrasado", "n": total_uo["atrasado_ativos"], "classe": "abnt-cartao-alerta"},
    ]
    estimado = Decimal(fatos["financeiro"]["estimado"])
    contratado = Decimal(fatos["financeiro"]["contratado"])
    grafico_valores = _grafico_colunas(
        [
            {"rotulo": "Previsto", "segmentos": [(estimado, "abnt-cor-3")], "valor": f"R$ {_milhoes(estimado)} milhões"},
            {"rotulo": "Contratado", "segmentos": [(contratado, "abnt-cor-1")],
             "valor": f"R$ {_milhoes(contratado)} milhões"},
        ],
        altura_area=150, fracao=0.40,
    )
    unidades = sorted((l for l in linhas_uo if l["ativos"]), key=lambda l: (-l["ativos"], l["uo"]))
    colunas_uo, demais = _colunas_por_unidade(linhas_uo)
    grafico_unidades = _grafico_colunas(
        colunas_uo, altura_area=180, fracao=0.60,
        legenda=[{"classe": "abnt-cor-1", "texto": "Concluído"}, {"classe": "abnt-cor-2", "texto": "Em tramitação"},
                 {"classe": "abnt-cor-3", "texto": "A entregar à Gelic"}],
    )
    maior_entregar = max((l["no_prazo_ativos"] + l["atrasado_ativos"] for l in unidades), default=0)
    lideres = [l["uo"] for l in unidades if maior_entregar and l["no_prazo_ativos"] + l["atrasado_ativos"] == maior_entregar]

    registros = _apresentar_registros(fatos["registros"])
    processos = [
        {"item": p["item"], "objeto": p["objeto"], "uo": p["uo"],
         "data": data_br(date.fromisoformat(p["data"])) if p["data"] else "–", "situacao": p["situacao"]}
        for p in fatos["processos"]
    ]
    gerado_em = datetime.fromisoformat(fatos["gerado_em"])

    # Numeração dos quadros, tabelas e gráficos na ordem em que aparecem — só o que existe ganha número, e o
    # texto corrido cita esses números (nunca "Tabela 3" fixo). Os quadros são os indicadores da reunião (só
    # no relatório de reunião) e os cartões de situação; os gráficos são os dois de colunas, sempre presentes.
    tabelas, graficos = {"movimentacao": 1}, {"valores": 1, "unidades": 2}
    quadros = {"indicadores": 1, "situacao": 2} if reuniao else {"situacao": 1}
    for chave, presente in (
        ("registros", registros["grupos"]), ("concluidas", concluidas), ("incluidos", incluidos),
        ("excluidos", excluidos), ("gelic", gelic), ("alteracoes", alteracoes), ("adiados", adiados),
        ("solicitacoes", solicitacoes["grupos"]),
    ):
        if presente:
            tabelas[chave] = len(tabelas) + 1
    tabelas["anexo_resumo"] = len(tabelas) + 1
    tabelas["anexo_processos"] = len(tabelas) + 1

    # Textos corridos (compostos aqui para concordância de número e de zero).
    extenso = periodo_por_extenso(de, ate)
    no_periodo = extenso if extenso.startswith("em ") else f"no período {extenso}"
    if anterior_data is not None and de == anterior_data + timedelta(days=1):
        dia_anterior = (
            f"{anterior_data.day} de {NOMES_MES[anterior_data.month].lower()}"
            if anterior_data.year == ate.year else data_extenso(anterior_data)
        )
        desde = f"desde a reunião anterior, de {dia_anterior}"
    else:
        desde = no_periodo
    plano = f"Plano de Contratações Anual (PCA) {exercicio.ano} do Conselho Federal de Contabilidade"
    anexos = "O Anexo I traz o resumo por unidade e o Anexo II, todos os processos em ordem de item."
    if reuniao is not None:
        introducao = (
            f"Este relatório registra o que foi tratado na {ordinal}ª reunião de acompanhamento do {plano} e a "
            f"movimentação dos itens {desde}, apurada pelo sistema PCA CFC a partir do histórico de alterações. {anexos}"
        )
    else:
        introducao = (
            f"Este relatório registra a movimentação dos itens do {plano} {no_periodo}, apurada pelo sistema PCA CFC "
            f"a partir do histórico de alterações. {anexos}"
        )

    n_reg, n_uo = registros["itens"], registros["unidades"]
    if n_reg:
        sintese = (
            f"Foram tratados {n_reg} {_plural(n_reg, 'item', 'itens')} de {n_uo} "
            f"{_plural(n_uo, 'unidade', 'unidades')}: {registros['cumpridos']} "
            f"{_plural(registros['cumpridos'], 'compromisso de prazo cumprido', 'compromissos de prazo cumpridos')}, "
            f"{registros['repactuados']} {_plural(registros['repactuados'], 'prazo repactuado', 'prazos repactuados')} e "
            f"{registros['vencidos']} {_plural(registros['vencidos'], 'compromisso vencido', 'compromissos vencidos')} "
            f"(Quadro {quadros['indicadores']})."
        )
    elif reuniao is not None:
        sintese = f"Nenhum item tem registro nesta reunião (Quadro {quadros['indicadores']})."
    else:
        # Relatório de período: não é de uma reunião; a síntese fala só da movimentação.
        sintese = ""
    sintese += (
        f" No período, {len(concluidas)} {_plural(len(concluidas), 'contratação foi concluída', 'contratações foram concluídas')}"
        + (f", somando R$ {_milhoes(soma_contratado_conc)} milhões contratados" if concluidas else "")
        + f", {n_inc} {_plural(n_inc, 'item entrou', 'itens entraram')} no PCA e "
        f"{exclusoes['contagem']} {_plural(exclusoes['contagem'], 'saiu', 'saíram')} (Tabela 1)."
    )
    sintese = sintese.lstrip()
    situacao_texto = (
        f"Em {data_br(hoje)}, o PCA {exercicio.ano} tinha {total_uo['total_previsto']} itens previstos: "
        f"{total_uo['total_previsto'] - ativos} cancelados e {ativos} ativos. Dos ativos, {total_uo['concluido']} "
        f"estavam concluídos, {total_uo['em_tramitacao_ativos']} em tramitação na Gelic e {a_entregar} ainda a "
        f"entregar, sendo {total_uo['no_prazo_ativos']} no prazo e {total_uo['atrasado_ativos']} "
        f"{_plural(total_uo['atrasado_ativos'], 'atrasado', 'atrasados')} (Quadro {quadros['situacao']}). Do valor "
        f"previsto de R$ {_milhoes(estimado)} milhões, R$ {_milhoes(contratado)} milhões "
        f"({_pct_txt(contratado, estimado)}) já estavam contratados (Gráfico {graficos['valores']})."
    )
    if lideres:
        situacao_texto += (
            f" {_plural(len(lideres), 'A unidade com mais itens a entregar era', 'As unidades com mais itens a entregar eram')} "
            f"{_lista(lideres)}, com {maior_entregar} {_plural(maior_entregar, 'item', 'itens')}"
            f"{' cada' if len(lideres) > 1 else ''} (Gráfico {graficos['unidades']})."
        )

    if n_reg:
        registros_texto = (
            f"{_plural(n_reg, 'O item tratado na reunião é', f'Os {n_reg} itens tratados na reunião vêm')} de "
            f"{_plural(n_uo, '1 unidade', f'{n_uo} unidades')}"
        )
        if registros["lideres"]:
            registros_texto += (
                f"; {_lista(registros['lideres'])} {_plural(len(registros['lideres']), 'teve', 'tiveram')} "
                f"{registros['maior']} itens{' cada' if len(registros['lideres']) > 1 else ''}"
            )
        registros_texto += (
            f". A Tabela {tabelas['registros']} traz os registros agrupados por "
            "unidade, com a situação informada, o que foi registrado e o prazo de entrega à Gelic."
        )
    elif reuniao is not None:
        registros_texto = "Nenhum item teve registro nesta reunião."
    else:
        registros_texto = ""

    if fatos["houve_movimentacao"]:
        movimentacao_texto = (
            f"Esta seção detalha a movimentação dos itens do PCA {extenso}. Cada item aparece uma única vez, na "
            "movimentação mais relevante, e as demais alterações do mesmo item constam junto dele."
        )
        com_valor = [tabelas.get(c) for c in ("concluidas", "incluidos", "excluidos") if tabelas.get(c)]
        if com_valor:
            refs = _referencias("Tabela", com_valor)
            movimentacao_texto += f" {'Na' if len(com_valor) == 1 else 'Nas'} {refs}, os itens estão ordenados do maior para o menor valor"
            movimentacao_texto += (
                f"; na Tabela {tabelas['alteracoes']}, agrupados pelo tipo de alteração." if alteracoes else "."
            )
        elif alteracoes:
            movimentacao_texto += f" Na Tabela {tabelas['alteracoes']}, os itens estão agrupados pelo tipo de alteração."
    else:
        movimentacao_texto = f"Não houve movimentação de itens do PCA {extenso}."

    def _de_unidades(linhas):
        nomes = sorted({l["uo"] for l in linhas})
        return f"da unidade {nomes[0]}" if len(nomes) == 1 else f"de {len(nomes)} unidades"

    if concluidas:
        concluidas_texto = (
            f"{_plural(len(concluidas), 'Foi concluída 1 contratação', f'Foram concluídas {len(concluidas)} contratações')}, "
            f"com R$ {_reais(soma_contratado_conc)} contratados para R$ {_reais(soma_estimado_conc)} estimados "
            f"(Tabela {tabelas['concluidas']})."
        )
        # Diferença de 10% ou mais entre contratado e estimado: item a item quando são poucas; senão, um resumo.
        diferencas = [
            (c["item"], (Decimal(c["contratado"]) - Decimal(c["estimado"])) / Decimal(c["estimado"]) * 100)
            for c in concluidas if c["estimado"] and c["contratado"] is not None
        ]
        diferencas = [(item, d) for item, d in diferencas if abs(d) >= 10]
        if len(diferencas) <= 2:
            for item, d in diferencas:
                concluidas_texto += (
                    f" No item {item}, o valor contratado ficou {abs(d):.0f}% {'abaixo' if d < 0 else 'acima'} do estimado."
                )
        else:
            item, d = max(diferencas, key=lambda par: abs(par[1]))
            concluidas_texto += (
                f" Em {len(diferencas)} contratações, o valor contratado diferiu 10% ou mais do estimado; a maior "
                f"diferença foi a do item {item}, {abs(d):.0f}% {'abaixo' if d < 0 else 'acima'} do estimado."
            )
    else:
        concluidas_texto = "Nenhuma contratação foi concluída no período."

    if incluidos:
        partes_mes = []
        for indice, grupo in enumerate(incluidos):
            if grupo["mes"] == "Sem mês previsto":
                partes_mes.append(f"{grupo['n']} sem mês previsto")
            else:
                partes_mes.append(f"{grupo['n']} {'com mês previsto em ' if indice == 0 else 'em '}{grupo['mes'].lower()}")
        linhas_inc = [l for g in incluidos for l in g["linhas"]]
        if len(incluidos) == 1 and incluidos[0]["mes"] != "Sem mês previsto":
            meses = f"{_plural(n_inc, 'com', 'todos com')} mês previsto em {incluidos[0]['mes'].lower()}"
        else:
            meses = _lista(partes_mes)
        incluidos_texto = (
            f"{_plural(n_inc, 'Foi incluído 1 item', f'Foram incluídos {n_inc} itens')} {_de_unidades(linhas_inc)}, "
            f"no valor estimado de R$ {_reais(soma_incluidos)}: {meses} "
            f"(Tabela {tabelas['incluidos']})."
        )
    else:
        incluidos_texto = "Nenhum item foi incluído no PCA no período."

    n_exc = len(excluidos)
    excluidos_texto = (
        f"{_plural(n_exc, 'Foi excluído 1 item', f'Foram excluídos {n_exc} itens')} {_de_unidades(excluidos)}, com "
        f"valor estimado total de R$ {_reais(soma_excluidos)} (Tabela {tabelas['excluidos']})."
        if excluidos else "Nenhum item foi excluído do PCA no período."
    )
    gelic_texto = (
        f"{_plural(len(gelic), '1 item teve', f'{len(gelic)} itens tiveram')} a data de envio à Gelic registrada no "
        f"período (Tabela {tabelas['gelic']})."
        if gelic else "Nenhum item teve a data de envio à Gelic registrada no período."
    )
    alteracoes_texto = (
        f"A Tabela {tabelas['alteracoes']} reúne as demais alterações do período, agrupadas pelo tipo: "
        f"{_lista(g['tipo'].lower() for g in alteracoes)}."
        if alteracoes else "Não houve outras alterações no período."
    )
    adiados_texto = (
        f"A Tabela {tabelas.get('adiados')} reúne os compromissos de prazo assumidos em reunião no período." if adiados else ""
    )

    n_dec, n_pen = solicitacoes["decididas"], solicitacoes["pendentes"]
    if n_dec or n_pen:
        partes_texto = []
        if n_dec:
            detalhe_dec = [
                f"{n} {rotulo}" for n, rotulo in (
                    (solicitacoes["aprovadas"], _plural(solicitacoes["aprovadas"], "aprovado", "aprovados")),
                    (solicitacoes["ajustadas"],
                     _plural(solicitacoes["ajustadas"], "aprovado com ajuste", "aprovados com ajuste")),
                    (solicitacoes["recusadas"], _plural(solicitacoes["recusadas"], "recusado", "recusados")),
                ) if n
            ]
            partes_texto.append(
                f"{_plural(n_dec, 'Foi decidido 1 pedido', f'Foram decididos {n_dec} pedidos')} das unidades "
                f"{no_periodo} ({_lista(detalhe_dec)})"
            )
        if n_pen:
            partes_texto.append(
                f"{_plural(n_pen, '1 pedido segue', f'{n_pen} pedidos seguem')} em análise"
                if n_dec else
                f"{_plural(n_pen, 'Há 1 pedido', f'Há {n_pen} pedidos')} das unidades em análise"
            )
        solicitacoes_texto = (
            f"{' e '.join(partes_texto)} (Tabela {tabelas['solicitacoes']}). Cada linha é uma parte do pedido, "
            "decidida pela equipe do PCA (prazo e mês) ou pela diretoria (inclusão, cancelamento, valor e objeto)."
        )
        sintese += (
            f" Quanto às solicitações das unidades, {n_dec} {_plural(n_dec, 'pedido foi decidido', 'pedidos foram decididos')} e "
            f"{n_pen} {_plural(n_pen, 'segue', 'seguem')} em análise (Tabela {tabelas['solicitacoes']})."
        )
    else:
        solicitacoes_texto = "Nenhum pedido das unidades foi decidido no período nem está em análise."

    resultado = {
        "exercicio": exercicio,
        "reuniao": reuniao,
        "ordinal": ordinal,
        "titulo": (
            f"{ordinal}ª reunião de acompanhamento do PCA {exercicio.ano}"
            if reuniao else f"Relatório de acompanhamento do PCA {exercicio.ano}"
        ),
        "data_reuniao": data_br(reuniao.data) if reuniao else "",
        "data_extenso": data_extenso(reuniao.data if reuniao else hoje),
        "hoje_extenso": data_extenso(hoje),
        "condutor": condutor,
        "em_andamento": em_andamento,
        "de": de,
        "ate": ate,
        "periodo_curto": periodo_curto(de, ate),
        "periodo_extenso": extenso,
        "fonte": f"Fonte: Sistema PCA CFC ({data_abnt(hoje)}).",
        "gerado_em": gerado_em,
        "gerado_por": fatos["gerado_por"],
        "secoes": secoes,
        "tabelas": tabelas,
        "graficos": graficos,
        "quadros": quadros,
        "introducao": introducao,
        "sintese": sintese,
        "registros": registros,
        "registros_texto": registros_texto,
        "tabela1": tabela1,
        "situacao_texto": situacao_texto,
        "cartoes_situacao": cartoes_situacao,
        "grafico_valores": grafico_valores,
        "grafico_unidades": grafico_unidades,
        "unidades_agrupadas": _lista(l["uo"] for l in demais),
        "n_unidades_agrupadas": len(demais),
        "movimentacao_texto": movimentacao_texto,
        "concluidas": concluidas,
        "concluidas_total": {"estimado": _reais(soma_estimado_conc), "contratado": _reais(soma_contratado_conc)},
        "concluidas_texto": concluidas_texto,
        "incluidos": incluidos,
        "incluidos_n": n_inc,
        "incluidos_total": _reais(soma_incluidos),
        "incluidos_texto": incluidos_texto,
        "excluidos": excluidos,
        "excluidos_total": _reais(soma_excluidos),
        "excluidos_texto": excluidos_texto,
        "gelic": gelic,
        "gelic_texto": gelic_texto,
        "alteracoes": alteracoes,
        "alteracoes_texto": alteracoes_texto,
        "adiados": adiados,
        "adiados_texto": adiados_texto,
        "solicitacoes": solicitacoes,
        "solicitacoes_texto": solicitacoes_texto,
        "anexo_resumo": {
            "linhas": [_celulas_resumo(l) for l in linhas_uo],
            "total": _celulas_resumo(total_uo),
        },
        "anexo_processos": processos,
    }
    # "R$" nunca separado do número na quebra de linha do texto corrido.
    for chave, valor in resultado.items():
        if isinstance(valor, str):
            resultado[chave] = valor.replace("R$ ", "R$ ")
    return resultado


def montar_relatorio_reuniao(*, exercicio, reuniao, de, ate, usuario, hoje=None):
    """Apura e apresenta de uma vez (prévia ao vivo e testes): `apresentar_relatorio(apurar_relatorio(...))`."""
    return apresentar_relatorio(
        apurar_relatorio(exercicio=exercicio, reuniao=reuniao, de=de, ate=ate, usuario=usuario, hoje=hoje)
    )
