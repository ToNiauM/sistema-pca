"""Prepara a CÓPIA descartável do banco para os prints do manual do usuário.

Roda SÓ dentro da instância descartável `pca-manual-web` (chamado por `capturar.sh`):

    docker exec pca-manual-web python manual/capturas/preparar.py

1. Máscara de pessoas: todo usuário vira "Usuário Fictício NN" / usuarioNN@example.org (também na
   tabela histórica); nomes de usuários e da lista de nomes extras, e-mails, telefones e CPFs em
   qualquer coluna de texto viram "Pessoa A", pessoa@example.org, (00) 0000-0000, 000.000.000-00.
   Itens, valores, unidades e fornecedores ficam como estão.
2. Lista na tela os candidatos a nome de pessoa que sobraram (para conferência humana).
3. Cria as personas fictícias (Ana, Bruno, Carla, Daniel, Eva) e as sessões delas.
4. Cria as solicitações de exemplo pelos SERVIÇOS de `apps.solicitacoes` (`semear_solicitacoes`).
5. Grava cenario.json e sessoes.json em /app/data/manual-mascara/ (só na cópia temporária).

Guarda tripla antes de tocar o banco: PCA_MANUAL_DESCARTAVEL=1, banco em /app/data/db.sqlite3 e a
marca /app/data/.copia-descartavel-manual, que só existe na cópia temporária. Recusa rodar duas vezes.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

BANCO = "/app/data/db.sqlite3"
MARCA = Path("/app/data/.copia-descartavel-manual")
SAIDA = Path("/app/data/manual-mascara")
EXTRAS = Path("/manual/extras.txt")


def _recusar(motivo: str) -> None:
    print(f"preparar.py RECUSOU: {motivo}", file=sys.stderr)
    sys.exit(2)


# --- Guarda tripla (antes de qualquer acesso ao banco) ----------------------------------------
if os.environ.get("PCA_MANUAL_DESCARTAVEL") != "1":
    _recusar("PCA_MANUAL_DESCARTAVEL não é 1 — isto não é a instância descartável.")
from django.conf import settings  # noqa: E402

if str(settings.DATABASES["default"]["NAME"]) != BANCO:
    _recusar(f"o banco não é {BANCO}.")
if not MARCA.exists():
    _recusar(f"falta a marca {MARCA} — este banco não é a cópia descartável.")
if (SAIDA / "feito").exists():
    _recusar("a cópia já foi preparada (existe manual-mascara/feito).")

import django  # noqa: E402

django.setup()

from datetime import date, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from django.apps import apps  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.hashers import make_password  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.db import connection, models, transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils.timezone import localdate  # noqa: E402

Usuario = get_user_model()

MESES = (
    "janeiro fevereiro março marco abril maio junho julho agosto setembro outubro novembro dezembro"
).split()
CONECTORES = ("da", "de", "do", "dos", "das", "e")
# Termos institucionais e palavras comuns que começam frase em maiúscula: nunca são pessoa.
TERMOS_INSTITUCIONAIS = """
Conselho Federal Contabilidade Termo Referência Referencia Ata Registro Preços Precos Estudo Técnico
Tecnico Preliminar Plano Contratações Contratacoes Anual Diretoria Executiva Gerência Gerencia Gelic
Delic Projur Gecont Gex Lic Presidência Presidencia Vice Presidente Conselheiro Conselheira Plenário
Plenario Tribunal Contas União Uniao Lei Decreto Portaria Instrução Instrucao Normativa Resolução
Resolucao Sistema Eletrônico Eletronico Informações Informacoes Pregão Pregao Dispensa Inexigibilidade
Edital Contrato Aditivo Apostilamento Nota Empenho Fiscal Gestor Comissão Comissao Equipe Pca Cfc Crc
Brasil Brasília Brasilia Distrito Federal Governo Ministério Ministerio Secretaria Superintendência
Setor Seção Secao Coordenação Coordenacao Assessoria Gabinete Ouvidoria Controladoria Auditoria
Departamento Divisão Divisao Unidade Serviço Servico Serviços Servicos Aquisição Aquisicao Contratação
Contratacao Renovação Renovacao Nova Prorrogação Prorrogacao Processo Sei Item Objeto Valor Prazo
Mês Mes Situação Situacao Reunião Reuniao Acompanhamento Solicitação Solicitacao Fornecedor Empresa
Ltda Eireli Me Epp Sa Banco Caixa Correios Microsoft Google Oracle Adobe Windows Office Licença Licenca
""".split()


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — a mesma regra da conferência do capturar.py."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


_VARIANTES = {
    "a": "aáàâãä", "e": "eéèêë", "i": "iíìîï", "o": "oóòôõö", "u": "uúùûü", "c": "cç", "n": "nñ",
}


def _padrao_de_nome(nome_normalizado: str) -> str:
    partes = []
    for palavra in nome_normalizado.split():
        partes.append(
            "".join(
                f"[{_VARIANTES[ch]}]" if ch in _VARIANTES else re.escape(ch) for ch in palavra
            )
        )
    return r"\s+".join(partes)


def _rotulo(indice: int) -> str:
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return f"Pessoa {letras}"


# Contas técnicas (robô do SEI, importador, verificações): não são pessoas — mantêm o nome
# ("Robo Sei" aparece nos históricos) e só o e-mail vira @example.org.
DOMINIO_TECNICO = "@pca.local"


def _tecnico(usuario) -> bool:
    return (usuario.email or "").lower().endswith(DOMINIO_TECNICO)


RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_TELEFONE = re.compile(r"\(\d{2}\)\s?\d{4,5}-\d{4}")
RE_CPF = re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d])")


# --- 1. Dicionário de reais, grupos e máscara --------------------------------------------------


def _grupos_reais(nome_grupo: str) -> tuple:
    """Combinação de grupos mais comum entre os usuários reais de `nome_grupo` (antes da máscara)."""
    combos = Counter(
        tuple(sorted(u.groups.values_list("name", flat=True)))
        for u in Usuario.objects.filter(groups__name=nome_grupo).prefetch_related("groups")
    )
    if not combos:
        return ()
    return combos.most_common(1)[0][0]


def montar_dicionario():
    """Pessoas reais: por usuário, o nome completo e "primeiro nome + sobrenome" (4+ letras),
    também os nomes já gravados na tabela histórica; e-mails; e as linhas de /manual/extras.txt."""
    historico = Usuario.history.model
    pessoas = []  # lista de conjuntos de variantes normalizadas (uma pessoa por usuário)
    emails_por_usuario = {}
    for usuario in Usuario.objects.order_by("pk"):
        if _tecnico(usuario):
            emails_por_usuario[usuario.pk] = {usuario.email.lower()}
            continue
        nomes = {(usuario.first_name, usuario.last_name)}
        nomes |= set(
            historico.objects.filter(id=usuario.pk).values_list("first_name", "last_name").distinct()
        )
        variantes = set()
        for primeiro, ultimo in nomes:
            completo = normalizar(f"{primeiro} {ultimo}")
            palavras = completo.split()
            if len(palavras) >= 2:
                variantes.add(completo)
                for sobrenome in palavras[1:]:
                    if len(sobrenome) >= 4 and sobrenome not in CONECTORES:
                        variantes.add(f"{palavras[0]} {sobrenome}")
        pessoas.append(variantes)
        emails = {usuario.email.lower()} | {
            (e or "").lower()
            for e in historico.objects.filter(id=usuario.pk).values_list("email", flat=True)
        }
        emails_por_usuario[usuario.pk] = {e for e in emails if e}
    extras = []
    if EXTRAS.exists():
        for linha in EXTRAS.read_text(encoding="utf-8").splitlines():
            linha = normalizar(linha.split("#", 1)[0])
            if linha:
                extras.append(linha)
    return pessoas, emails_por_usuario, extras


class Mascara:
    def __init__(self, pessoas, extras, emails_ficticios):
        self.rotulo_por_nome = {}
        ordem = 0
        for variantes in pessoas:
            if not variantes:
                continue
            rotulo = _rotulo(ordem)
            ordem += 1
            for v in variantes:
                self.rotulo_por_nome.setdefault(v, rotulo)
        for extra in extras:
            if extra not in self.rotulo_por_nome:
                self.rotulo_por_nome[extra] = _rotulo(ordem)
                ordem += 1
        self.emails_ficticios = emails_ficticios  # e-mail real (minúsculo) → fictício
        nomes = sorted(self.rotulo_por_nome, key=len, reverse=True)
        self.re_nomes = (
            re.compile(
                r"(?<!\w)(?:" + "|".join(_padrao_de_nome(n) for n in nomes) + r")(?!\w)",
                re.IGNORECASE,
            )
            if nomes
            else None
        )

    def _email(self, achado):
        email = achado.group(0)
        baixo = email.lower()
        if baixo in self.emails_ficticios:
            return self.emails_ficticios[baixo]
        if baixo.endswith("@example.org"):
            return email
        return "pessoa@example.org"

    def _nome(self, achado):
        return self.rotulo_por_nome.get(normalizar(achado.group(0)), "Pessoa")

    def aplicar(self, texto: str) -> str:
        if not texto:
            return texto
        novo = RE_EMAIL.sub(self._email, texto)
        if self.re_nomes is not None:
            novo = self.re_nomes.sub(self._nome, novo)
        novo = RE_TELEFONE.sub("(00) 0000-0000", novo)
        novo = RE_CPF.sub("000.000.000-00", novo)
        return novo


def mascarar_usuarios():
    """Usuários e a tabela histórica deles com nome/e-mail fictícios; sessões, tentativas de
    login, tokens e o log do Admin apagados. Devolve o mapa e-mail real → fictício."""
    historico = Usuario.history.model
    senha = make_password(None)
    mapa = {}
    for n, usuario in enumerate(Usuario.objects.order_by("pk"), start=1):
        if _tecnico(usuario):
            local = usuario.email.split("@", 1)[0]
            ficticio = {"email": f"{local}@example.org", "password": senha}
        else:
            ficticio = {
                "first_name": "Usuário",
                "last_name": f"Fictício {n:02d}",
                "email": f"usuario{n:02d}@example.org",
                "password": senha,
            }
        for real in {usuario.email.lower()} | set(
            (e or "").lower() for e in historico.objects.filter(id=usuario.pk).values_list("email", flat=True)
        ):
            if real:
                mapa[real] = ficticio["email"]
        Usuario.objects.filter(pk=usuario.pk).update(**ficticio)
        historico.objects.filter(id=usuario.pk).update(**ficticio)
    from django.contrib.admin.models import LogEntry
    from django.contrib.sessions.models import Session

    from core.models import TokenApi

    Session.objects.all().delete()
    TokenApi.objects.all().delete()
    LogEntry.objects.all().delete()
    for modelo in apps.get_app_config("axes").get_models():
        modelo.objects.all().delete()
    return mapa


PULAR_TABELAS = {"django_migrations", "django_content_type", "auth_permission", "django_session"}


def mascarar_textos(mascara: Mascara) -> int:
    """Passada genérica em toda coluna de texto de toda tabela (menos a do usuário, já tratada),
    linha a linha, UPDATE parametrizado. Devolve quantas células mudaram."""
    pular = PULAR_TABELAS | {Usuario._meta.db_table, Usuario.history.model._meta.db_table}
    alteradas = 0
    with connection.cursor() as cursor:
        tabelas = [t for t in connection.introspection.table_names(cursor) if t not in pular]
        for tabela in tabelas:
            colunas = [
                c.name
                for c in connection.introspection.get_table_description(cursor, tabela)
                if any(t in (c.type_code or "").lower() for t in ("char", "text", "clob"))
            ]
            if not colunas:
                continue
            q = connection.ops.quote_name
            lista = ", ".join(q(c) for c in colunas)
            cursor.execute(f"SELECT rowid, {lista} FROM {q(tabela)}")
            linhas = cursor.fetchall()
            for linha in linhas:
                rowid, valores = linha[0], linha[1:]
                mudou = {}
                for coluna, valor in zip(colunas, valores):
                    if isinstance(valor, str) and valor:
                        novo = mascara.aplicar(valor)
                        if novo != valor:
                            mudou[coluna] = novo
                if mudou:
                    sets = ", ".join(f"{q(c)} = %s" for c in mudou)
                    cursor.execute(
                        f"UPDATE {q(tabela)} SET {sets} WHERE rowid = %s", [*mudou.values(), rowid]
                    )
                    alteradas += len(mudou)
    return alteradas


# --- 2. Candidatos a nome que sobraram --------------------------------------------------------

_MAIUSCULA = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇÀ][a-záéíóúâêôãõçàü]+"
RE_CANDIDATO = re.compile(
    rf"(?<![\w]){_MAIUSCULA}(?:\s+(?:(?:{'|'.join(CONECTORES)})\s+)?{_MAIUSCULA}){{1,3}}(?!\w)"
)


def listar_candidatos():
    from apps.catalogo.models import DominioBase
    from apps.pca.models import Processo

    vocabulario = set()
    for modelo in apps.get_models():
        if issubclass(modelo, DominioBase):
            vocabulario |= {normalizar(n) for n in modelo.objects.values_list("nome", flat=True)}
    vocabulario |= {
        normalizar(n)
        for n in Processo.objects.exclude(fornecedor_razao_social="")
        .values_list("fornecedor_razao_social", flat=True)
    }
    palavras_fixas = {normalizar(p) for p in TERMOS_INSTITUCIONAIS} | {normalizar(m) for m in MESES}
    palavras_vocabulario = {p for v in vocabulario for p in v.split() if len(p) >= 3}

    contagem = Counter()
    for modelo in apps.get_models():
        campos = [
            f.attname for f in modelo._meta.concrete_fields if isinstance(f, models.TextField)
        ]
        if hasattr(modelo, "history_change_reason") or modelo.__name__.startswith("Historical"):
            campos.append("history_change_reason")
        campos = [c for c in dict.fromkeys(campos) if c in {f.attname for f in modelo._meta.concrete_fields}]
        if not campos:
            continue
        for valores in modelo.objects.values_list(*campos).iterator():
            for texto in valores:
                if not isinstance(texto, str):
                    continue
                for achado in RE_CANDIDATO.findall(texto):
                    norm = normalizar(achado)
                    if any(norm in v for v in vocabulario):
                        continue
                    significativas = [p for p in norm.split() if p not in CONECTORES]
                    if all(p in palavras_fixas or p in palavras_vocabulario for p in significativas):
                        continue
                    contagem[" ".join(achado.split())] += 1
    print(f"\n== candidatos a nome de pessoa que sobraram: {len(contagem)} ==")
    for texto, n in sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:5d}  {texto}")
    print("== fim dos candidatos (nomes de pessoa física vão para o arquivo de nomes extras) ==\n")


# Razão social sem nenhuma marca de empresa: provável pessoa física (empresário individual). O
# fornecedor continua real na cópia, mas o nome vai para evitar.txt e a conferência do capturar.py
# barra o print que o mostrar (a cena troca de filtro/item/recorte).
RE_MARCA_EMPRESA = re.compile(
    r"(?i)\b(ltda|s\.?/?a\.?|eireli|me|epp|cia|companhia|com[eé]rcio|servi[cç]o|servi[cç]os|"
    r"tecnologia|tecnologias|solu[cç][oõ]es|empresa|grupo|instituto|associa[cç][aã]o|funda[cç][aã]o|banco|"
    r"caixa|correios|editora|distribuidora|engenharia|consultoria|telecom|sistemas|inform[aá]tica|"
    r"software|ag[eê]ncia|conselho|universidade|seguros|hotel|turismo|advogados|sociedade|federa[cç][aã]o|"
    r"centro|escola|eventos|serpro|comunica[cç][aã]o)\b"
)


def gravar_evitar() -> int:
    from apps.pca.models import Processo

    nomes = sorted(
        {
            r.strip()
            for r in Processo.objects.values_list("fornecedor_razao_social", flat=True)
            if r and r.strip() and not RE_MARCA_EMPRESA.search(r) and not re.search(r"\d", r)
            and 2 <= len(r.split()) <= 6
        }
    )
    caminho = SAIDA / "evitar.txt"
    caminho.write_text("\n".join(nomes) + ("\n" if nomes else ""), encoding="utf-8")
    return len(nomes)


# --- 3. Personas ------------------------------------------------------------------------------


def _itens_abertos():
    from apps.catalogo.models import SituacaoExercicio
    from apps.pca.models import Processo

    return (
        Processo.objects.para_listagem()
        .select_related("exercicio", "unidade_organizacional", "tipo")
        .filter(exercicio__situacao=SituacaoExercicio.ABERTO)
        .order_by("exercicio__ano", "item_pca")
    )


def escolher_unidade():
    """A unidade com mais itens que aceitam pedido de prazo E de valor hoje."""
    from apps.solicitacoes.regras import Campo
    from apps.solicitacoes.services import campos_aceitos_do_item

    por_unidade = Counter()
    for item in _itens_abertos():
        aceitos = campos_aceitos_do_item(item)
        if Campo.PRAZO_ENTREGA in aceitos and Campo.VALOR_ESTIMADO in aceitos:
            por_unidade[item.unidade_organizacional_id] += 1
    if not por_unidade:
        raise SystemExit("Nenhum item aceita pedido de prazo e valor no exercício aberto.")
    return por_unidade.most_common(1)[0][0]


def criar_personas(combo_solicitante, combo_diretoria, unidade_id):
    from apps.solicitacoes.models import VinculoUnidade

    existentes = set(Group.objects.values_list("name", flat=True))
    solicitante = combo_solicitante or ("solicitante",)
    diretoria = combo_diretoria or tuple(g for g in ("diretoria", "dirigentes") if g in existentes)
    definicao = {
        "ana": ("ana.exemplo@example.org", "Ana", "Exemplo", solicitante, False),
        "bruno": ("bruno.exemplo@example.org", "Bruno", "Exemplo", ("visualizador",), False),
        "carla": ("carla.exemplo@example.org", "Carla", "Exemplo", ("editor",), False),
        "daniel": ("daniel.exemplo@example.org", "Daniel", "Exemplo", diretoria, False),
        "eva": ("eva.exemplo@example.org", "Eva", "Exemplo", solicitante, True),
    }
    personas = {}
    for chave, (email, primeiro, ultimo, grupos, temporaria) in definicao.items():
        usuario = Usuario.objects.create_user(
            email=email, password=None, first_name=primeiro, last_name=ultimo,
            senha_temporaria=temporaria,
        )
        usuario.groups.set(Group.objects.filter(name__in=grupos))
        personas[chave] = usuario
    for chave in ("ana", "eva"):
        VinculoUnidade.objects.create(usuario=personas[chave], unidade_id=unidade_id)
    return personas, {"solicitante": list(solicitante), "diretoria": list(diretoria)}


def sessoes(personas):
    resultado = {}
    for chave, usuario in personas.items():
        cliente = Client()
        cliente.force_login(usuario)
        resultado[chave] = cliente.cookies[settings.SESSION_COOKIE_NAME].value
    return {"cookie": settings.SESSION_COOKIE_NAME, "personas": resultado}


# --- 4. Solicitações de exemplo ----------------------------------------------------


def _ref_item(item):
    return {"id": item.pk, "ano": item.exercicio.ano, "item_pca": item.item_pca,
            "url": reverse("pca:detalhe_processo", args=[item.exercicio.ano, item.item_pca])}


def _ref_solicitacao(solicitacao):
    solicitacao.refresh_from_db()
    return {
        "ano": solicitacao.ano,
        "numero": solicitacao.numero,
        "url": reverse("solicitacoes:detalhe", args=[solicitacao.ano, solicitacao.numero]),
        "item": _ref_item(solicitacao.processo) if solicitacao.processo_id else None,
    }


def semear_solicitacoes(cenario, personas):
    """Solicitações de exemplo, todas pelos SERVIÇOS de apps.solicitacoes (e o encerramento do
    item da "prejudicada" por apps.pca.services.alterar_estado, que dispara o gancho real).

    Itens da unidade da Ana: os que aceitam prazo/mês (a entregar) e os que aceitam valor,
    objeto e cancelamento. Executado em ordem que nunca deixa dois pedidos em análise do
    mesmo campo no mesmo item, mesmo quando a unidade tem poucos itens e algum se repete."""
    from apps.catalogo.models import Categoria, Tipo
    from apps.pca import services as servicos_pca
    from apps.pca.models import Estado, Processo
    from apps.solicitacoes import services
    from apps.solicitacoes.models import ParteSolicitacao
    from apps.solicitacoes.regras import Campo, Decisao, TIPOS_DE_INCLUSAO

    ana, carla, daniel = personas["ana"], personas["carla"], personas["daniel"]
    unidade_id = cenario["unidade"]["id"]
    hoje = localdate()

    def item(pk):
        return Processo.objects.para_listagem().select_related("exercicio").get(pk=pk)

    itens = list(_itens_abertos().filter(unidade_organizacional_id=unidade_id))
    a_entregar = [i for i in itens if Campo.PRAZO_ENTREGA in services.campos_aceitos_do_item(i)]
    so_valor = [
        i for i in itens
        if Campo.VALOR_ESTIMADO in services.campos_aceitos_do_item(i) and i not in a_entregar
    ]
    if not a_entregar:
        raise SystemExit("A unidade da Ana não tem item a entregar para os exemplos.")
    # Itens para valor/objeto/cancelamento: de preferência os que não recebem os pedidos de prazo.
    pool_valor = so_valor + [i for i in a_entregar[4:]] + [i for i in a_entregar[:4]][::-1]
    if len(pool_valor) < 3:
        raise SystemExit("A unidade da Ana tem menos de 3 itens que aceitam pedido de valor.")

    def pedido_de(item_alvo, pedidos, justificativa, numero_sei=""):
        return services.criar_solicitacao(
            usuario=ana, processo_id=item_alvo.pk, justificativa=justificativa,
            pedidos=pedidos, numero_sei=numero_sei,
        )

    def parte(solicitacao, campo):
        return ParteSolicitacao.objects.get(solicitacao=solicitacao, campo=campo)

    def valor_redondo(base, fator):
        return (Decimal(base) * Decimal(fator)).quantize(Decimal("100"))

    p = [a_entregar[i % len(a_entregar)] for i in range(4)]
    # Valor e objeto: o item de objeto mais curto (o pedido aparece inteiro nas telas).
    pool_valor.sort(key=lambda x: (x in a_entregar, len(x.descricao_objeto)))
    exemplos = {}

    def adiado(item_alvo, dias):
        """Um prazo depois do atual, dentro do exercício (pedido de adiamento plausível)."""
        base = max(item_alvo.prazo_efetivo or hoje, hoje)
        fim = date(item_alvo.exercicio.ano, 12, 31)
        novo = min(base + timedelta(days=dias), fim)
        return (novo if novo != base else base - timedelta(days=7)).isoformat()

    # 1. Decidida mista: prazo (equipe aprova) + valor (diretoria aprova com ajuste).
    c = item(p[0].pk)
    s = pedido_de(
        c,
        {Campo.PRAZO_ENTREGA: adiado(c, 20),
         Campo.VALOR_ESTIMADO: str(valor_redondo(c.valor_estimado, "1.20"))},
        "A pesquisa de preços atualizada indicou valores acima do estimado e a área técnica "
        "precisa de mais prazo para revisar o termo de referência.",
        numero_sei="99999.000001/2026-00",
    )
    services.decidir_parte(parte_id=parte(s, Campo.PRAZO_ENTREGA).pk, usuario=carla,
                           decisao=Decisao.APROVAR)
    services.decidir_parte(
        parte_id=parte(s, Campo.VALOR_ESTIMADO).pk, usuario=daniel, decisao=Decisao.AJUSTE,
        valor_ajuste=str(valor_redondo(c.valor_estimado, "1.10")),
        motivo="Aprovado um acréscimo menor, compatível com a disponibilidade orçamentária.",
    )
    exemplos["mista_ajuste"] = _ref_solicitacao(s)

    # 2. Recusada: mês previsto (equipe recusa com motivo).
    d = item(p[1].pk)
    mes = 12 if d.mes_previsto != 12 else 11
    s = pedido_de(d, {Campo.MES_PREVISTO: mes},
                  "A unidade prefere concentrar a contratação no fim do ano.")
    services.decidir_parte(
        parte_id=parte(s, Campo.MES_PREVISTO).pk, usuario=carla, decisao=Decisao.RECUSAR,
        motivo="O mês pedido coincide com o fechamento do exercício; mantido o mês atual.",
    )
    exemplos["recusada"] = _ref_solicitacao(s)

    # 3. Desistida: pedido de prazo seguido de desistência da própria unidade.
    f = item(p[2].pk)
    s = pedido_de(f, {Campo.PRAZO_ENTREGA: adiado(f, 15)},
                  "Pedido feito por engano: o prazo atual atende a unidade.")
    services.desistir(solicitacao_id=s.pk, usuario=ana)
    exemplos["desistida"] = _ref_solicitacao(s)

    # 4. Em análise da equipe: prazo para depois de 31/12 (marca "fora do exercício").
    a = item(p[3].pk)
    s = pedido_de(a, {Campo.PRAZO_ENTREGA: date(a.exercicio.ano + 1, 2, 26).isoformat()},
                  "O fornecedor único do mercado só consegue apresentar proposta no início do "
                  "ano que vem.")
    exemplos["fora_exercicio"] = _ref_solicitacao(s)

    # 5. Em análise da diretoria: valor e objeto no mesmo item.
    b = item(pool_valor[0].pk)
    s = pedido_de(
        b,
        {Campo.VALOR_ESTIMADO: str(valor_redondo(b.valor_estimado, "1.15")),
         Campo.DESCRICAO_OBJETO: f"{b.descricao_objeto.rstrip('. ')}, com ampliação do quantitativo"},
        "A demanda das áreas atendidas cresceu e o quantitativo planejado não é mais suficiente.",
    )
    exemplos["diretoria_valor_objeto"] = _ref_solicitacao(s)

    # 6. Cancelamento em análise (sozinho, outro item).
    e = item(pool_valor[1].pk)
    s = pedido_de(e, {Campo.CANCELAMENTO: None},
                  "A necessidade deixou de existir com a mudança da área para a nova sede.")
    exemplos["cancelamento"] = _ref_solicitacao(s)

    # 7. Prejudicada: valor em análise e o item encerrado pela equipe (gancho real).
    # O item a encerrar não pode ter outro pedido em análise (ele também viraria "prejudicada").
    # Nem o item de exemplo das telas (a ficha e o formulário precisam dele ativo).
    ocupados = {a.pk, b.pk, e.pk, cenario["item_exemplo"]["id"]}
    livres = [x for x in pool_valor if x.pk not in ocupados] + [x for x in p[::-1] if x.pk not in ocupados]
    if not livres:
        raise SystemExit("Falta item livre para o exemplo de solicitação prejudicada.")
    g = item(livres[0].pk)
    s = pedido_de(g, {Campo.VALOR_ESTIMADO: str(valor_redondo(g.valor_estimado, "1.25"))},
                  "Reajuste de preços do mercado desde o planejamento.")
    servicos_pca.alterar_estado(
        processo_id=g.pk, usuario=carla, estado_novo=Estado.CANCELADO,
        observacao="Contratação suspensa por decisão da unidade responsável.",
    )
    exemplos["prejudicada"] = _ref_solicitacao(s)

    # 8. Inclusões: uma em análise e outra aprovada pela diretoria (o item nasce com o próximo número).
    tipo = next(
        t for t in Tipo.objects.order_by("pk") if t.nome_normalizado == TIPOS_DE_INCLUSAO[0]
    )
    categoria = (
        Categoria.objects.annotate(n=models.Count("processos")).order_by("-n", "pk").first()
    )
    mes_inclusao = max(hoje.month + 1, 11) if hoje.month < 12 else 12
    s = services.criar_inclusao(
        usuario=ana, unidade_id=unidade_id, tipo_id=tipo.pk, categoria_id=categoria.pk,
        descricao_objeto="Contratação de serviço de digitalização do acervo documental da unidade",
        valor_estimado="85000.00", mes_previsto=mes_inclusao,
        justificativa="O acervo em papel ocupa espaço e dificulta a consulta pelas áreas.",
    )
    exemplos["inclusao_em_analise"] = _ref_solicitacao(s)
    s = services.criar_inclusao(
        usuario=ana, unidade_id=unidade_id, tipo_id=tipo.pk, categoria_id=categoria.pk,
        descricao_objeto="Aquisição de cadeiras ergonômicas para as estações de trabalho da unidade",
        valor_estimado="42000.00", mes_previsto=12,
        prazo_entrega=date(hoje.year, 11, 30).isoformat() if hoje < date(hoje.year, 11, 30) else None,
        justificativa="As cadeiras atuais têm mais de dez anos de uso e não atendem às normas de "
                      "ergonomia.",
    )
    services.decidir_parte(parte_id=parte(s, Campo.INCLUSAO).pk, usuario=daniel,
                           decisao=Decisao.APROVAR)
    exemplos["inclusao_aprovada"] = _ref_solicitacao(s)

    # Valores para as cenas que só PREENCHEM o formulário (nunca enviam).
    alvo_form = item(cenario["item_exemplo"]["id"])
    cenario["formulario"] = {
        "prazo": adiado(alvo_form, 25),
        "valor": f"{valor_redondo(alvo_form.valor_estimado, '1.10'):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "valor_ajuste_b": f"{valor_redondo(b.valor_estimado, '1.08'):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "categoria_id": categoria.pk,
        "tipo_id": tipo.pk,
    }
    cenario["solicitacoes"] = exemplos
    cenario["itens_usados"] = {
        "prazo": [_ref_item(x) for x in p], "valor": [_ref_item(x) for x in (b, e, g)],
    }
    print(f"solicitações de exemplo: {len(exemplos)} "
          f"(itens a entregar na unidade: {len(a_entregar)}; só valor: {len(so_valor)})")


# --- 5. Cenário -------------------------------------------------------------------------------


def item_de_exemplo(unidade_id):
    from apps.solicitacoes.regras import Campo
    from apps.solicitacoes.services import campos_aceitos_do_item

    for item in _itens_abertos().filter(unidade_organizacional_id=unidade_id):
        aceitos = campos_aceitos_do_item(item)
        if Campo.PRAZO_ENTREGA in aceitos and Campo.VALOR_ESTIMADO in aceitos:
            return item
    raise SystemExit("A unidade escolhida não tem item de exemplo.")


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    os.chmod(SAIDA, 0o700)

    combo_solicitante = _grupos_reais("solicitante")
    combo_diretoria = _grupos_reais("diretoria")
    pessoas, emails_por_usuario, extras = montar_dicionario()

    reais = sorted({v for variantes in pessoas for v in variantes} | set(extras))
    reais += sorted({e for es in emails_por_usuario.values() for e in es})
    caminho_reais = SAIDA / "reais.txt"
    caminho_reais.write_text("\n".join(reais) + "\n", encoding="utf-8")
    os.chmod(caminho_reais, 0o600)

    with transaction.atomic():
        mapa_emails = mascarar_usuarios()
        mascara = Mascara(pessoas, extras, mapa_emails)
        celulas = mascarar_textos(mascara)
    print(
        f"máscara: {Usuario.objects.count()} usuário(s) com nome/e-mail fictícios; "
        f"{len(mascara.rotulo_por_nome)} variante(s) de nome; {celulas} célula(s) de texto alteradas"
    )

    listar_candidatos()
    print(f"fornecedores com nome de pessoa física (não entram em print): {gravar_evitar()}")

    unidade_id = escolher_unidade()
    personas, grupos = criar_personas(combo_solicitante, combo_diretoria, unidade_id)
    item = item_de_exemplo(unidade_id)
    from apps.catalogo.models import Unidade

    cenario = {
        "grupos_personas": grupos,
        "unidade": {"id": unidade_id, "nome": Unidade.objects.get(pk=unidade_id).nome},
        "item_exemplo": {"ano": item.exercicio.ano, "item_pca": item.item_pca, "id": item.pk},
        "urls": {
            "login": reverse("core:login"),
            "inicio": reverse("core:inicio"),
            "trocar_senha": reverse("core:trocar_senha"),
            "processos": reverse("pca:tabela"),
            "ficha_exemplo": reverse("pca:detalhe_processo", args=[item.exercicio.ano, item.item_pca]),
            "resumo_uo": reverse("pca:resumo_uo"),
            "analise": reverse("pca:analise"),
            "relatorio": reverse("pca:relatorio_movimentacao"),
            "nova": reverse("solicitacoes:nova"),
            "minhas": reverse("solicitacoes:minhas"),
            "avaliar": reverse("solicitacoes:avaliar"),
            "analise_fluxo": reverse("pca:analise_fluxo"),
            "analise_estatisticas": reverse("pca:analise_estatisticas"),
            "calendario": reverse("pca:calendario"),
            "processos_unidade": f"{reverse('pca:tabela')}?uo={unidade_id}",
            "nova_item": f"{reverse('solicitacoes:nova')}?processo={item.exercicio.ano}/{item.item_pca}",
            "nova_inclusao": f"{reverse('solicitacoes:nova')}?tipo=inclusao",
            "relatorio_periodo": (
                f"{reverse('pca:relatorio_movimentacao')}?de={(localdate() - timedelta(days=30)).isoformat()}"
                f"&ate={localdate().isoformat()}"
            ),
        },
    }
    semear_solicitacoes(cenario, personas)

    (SAIDA / "cenario.json").write_text(json.dumps(cenario, ensure_ascii=False, indent=2), encoding="utf-8")
    caminho_sessoes = SAIDA / "sessoes.json"
    caminho_sessoes.write_text(json.dumps(sessoes(personas), indent=2), encoding="utf-8")
    os.chmod(caminho_sessoes, 0o600)
    for arquivo in SAIDA.iterdir():
        os.chmod(arquivo, 0o600 if arquivo.name in ("reais.txt", "evitar.txt", "sessoes.json") else 0o644)
    # O container de captura lê como root: as permissões acima só protegem de outros usuários do host.
    (SAIDA / "feito").write_text("ok\n")
    print(f"personas: {', '.join(personas)} · grupos: {json.dumps(grupos, ensure_ascii=False)}")
    print(f"unidade escolhida: {cenario['unidade']['nome']} · item de exemplo: "
          f"{item.item_pca}/{item.exercicio.ano}")


if __name__ == "__main__":
    main()
