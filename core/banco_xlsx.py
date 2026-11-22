"""Exportar/importar o banco inteiro em um único XLSX.

Exceção deliberada de arquitetura: este arquivo, embora viva em `core/`,
importa `apps.catalogo.models`/`apps.pca.models` — o mesmo raciocínio de
`core/db.py` para utilidades transversais, mas aqui com conhecimento de
modelos porque a exportação/importação É sobre TODOS os modelos do banco,
não pertence a um único app de domínio.

Núcleo puro e testável sem request: `exportar_banco_xlsx()`,
`ler_planilha_banco()`, `calcular_relatorio()` (dry-run, nenhuma escrita),
`aplicar_relatorio()` (assume já estar dentro de `transaction.atomic()` do
chamador) e `fazer_backup_sqlite()`. O fluxo web (upload/relatório/
confirmação) fica em `core/views_banco.py`.
"""

import io
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import connection, models
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.importacao.models import EventoImportacao
from apps.pca.models import (
    Acompanhamento,
    Processo,
    ProcessoAlocador,
    ProcessoSEI,
    RascunhoItemVirada,
    RascunhoVirada,
    Reuniao,
)
from core.models import Usuario

LIMITE_LINHAS_RELATORIO = 50

FORMATO_DATA = "dd/mm/yyyy"
FORMATO_DATA_HORA = "dd/mm/yyyy hh:mm:ss"

# Mesma regra de `apps/pca/exportacao.py::_texto_seguro`,
# reimplementada localmente — `core/` não importa `apps.pca` por estilo.
PREFIXOS_FORMULA = ("=", "+", "-", "@")

# Colunas nunca exportadas nem gravadas por import, mesmo se presentes no
# arquivo.
CAMPOS_EXCLUIDOS = {Usuario: frozenset({"password", "last_login"})}

# `Processo.origem` é auto-FK: precisa de duas passagens em `aplicar_relatorio`
# para que um lote com duas linhas novas referenciando uma à outra resolva.
CAMPOS_DIFERIDOS = {Processo: ("origem_id",)}

# Ordem de dependência (grupos, ordem LIVRE dentro de cada grupo — provado
# pelo toposort, não hardcoded): Exercicio; os 8 catálogos DominioBase;
# Usuario; EventoImportacao; Reuniao; ProcessoAlocador; Processo;
# Acompanhamento; ProcessoSEI; RascunhoVirada; RascunhoItemVirada.
_MODELOS_BASE = (
    Exercicio,
    Unidade,
    Categoria,
    Tipo,
    GrauPrioridade,
    Classificacao,
    Modalidade,
    InstrumentoContratual,
    SituacaoNormalizada,
    Usuario,
    EventoImportacao,
    Reuniao,
    ProcessoAlocador,
    Processo,
    Acompanhamento,
    ProcessoSEI,
    RascunhoVirada,
    RascunhoItemVirada,
)


def _toposort(grafo):
    """Kahn topológico puro: `grafo` é um `dict {nó: set(dependências)}`,
    sem nenhum conhecimento de Django — testável com qualquer grafo
    sintético de nós hasheáveis."""
    pendentes = list(grafo)
    resolvidos = set()
    ordenados = []
    while pendentes:
        progresso = False
        for no in list(pendentes):
            if grafo[no] <= resolvidos:
                ordenados.append(no)
                resolvidos.add(no)
                pendentes.remove(no)
                progresso = True
        if not progresso:
            raise ValueError("Dependência circular detectada entre os nós informados.")
    return tuple(ordenados)


def _ordenar_por_dependencia(modelos):
    """Toposort sobre FKs reais (`model._meta.get_fields()`), ignorando
    auto-FK (`Processo.origem`) e qualquer FK para fora do conjunto
    informado."""
    modelos = list(modelos)
    conjunto = set(modelos)
    grafo = {}
    for modelo in modelos:
        dependencias = set()
        for campo in modelo._meta.get_fields():
            if not isinstance(campo, models.ForeignKey):
                continue
            destino = campo.related_model
            if destino is modelo or destino not in conjunto:
                continue
            dependencias.add(destino)
        grafo[modelo] = dependencias
    return _toposort(grafo)


MODELOS_INCLUIDOS = _ordenar_por_dependencia(_MODELOS_BASE)


def nome_aba(model):
    return f"{model._meta.app_label}.{model.__name__}"


MODELO_POR_ABA = {nome_aba(modelo): modelo for modelo in MODELOS_INCLUIDOS}


def campos_modelo(model):
    """`[pk] + demais concrete_fields`, pulando `CAMPOS_EXCLUIDOS`."""
    excluidos = CAMPOS_EXCLUIDOS.get(model, frozenset())
    pk_field = model._meta.pk
    outros = [
        campo
        for campo in model._meta.concrete_fields
        if campo is not pk_field and campo.attname not in excluidos
    ]
    return [pk_field] + outros


def _texto_seguro(valor):
    if isinstance(valor, str) and valor.lstrip()[:1] in PREFIXOS_FORMULA:
        return "'" + valor
    return valor


def _valor_exportado(valor, campo):
    if valor is None:
        return None
    if isinstance(campo, models.DateTimeField):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.replace(tzinfo=None)
    if isinstance(campo, models.DateField):
        return valor
    if isinstance(campo, (models.CharField, models.TextField, models.EmailField)):
        return _texto_seguro(valor)
    return valor


def _versao_sistema():
    try:
        resultado = subprocess.run(
            ["git", "describe", "--tags"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "desconhecida"
    if resultado.returncode != 0:
        return "desconhecida"
    versao = resultado.stdout.strip()
    return versao or "desconhecida"


def _preencher_leia_me(ws, contagens):
    agora = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    ws.append([f"Exportação do banco em {agora}"])
    ws.append([f"Versão do sistema: {_versao_sistema()}"])
    ws.append([])
    ws.append(["Linhas por aba"])
    for nome, linhas in contagens:
        ws.append([nome, linhas])
    ws.append([])
    ws.append(["Regras"])
    for regra in (
        "Não renomeie abas nem colunas — o import mapeia por nome exato.",
        "Célula vazia significa valor NULO, nunca zero ou texto vazio.",
        "Pk vazio (primeira coluna) cria uma linha nova.",
        "Pk preenchido mas inexistente no banco cria a linha com esse pk.",
        "As colunas password/last_login nunca são gravadas, mesmo que "
        "apareçam manualmente no arquivo.",
    ):
        ws.append([regra])


def exportar_banco_xlsx():
    """`.xlsx` com `["_leia-me"] + uma aba por modelo de MODELOS_INCLUIDOS`."""
    livro = Workbook()
    aba_leia_me = livro.active
    aba_leia_me.title = "_leia-me"

    contagens = []
    for modelo in MODELOS_INCLUIDOS:
        ws = livro.create_sheet(title=nome_aba(modelo))
        campos = campos_modelo(modelo)
        ws.append([campo.attname for campo in campos])
        linhas = 0
        for instancia in modelo.objects.order_by("pk").iterator():
            valores = [
                _valor_exportado(getattr(instancia, campo.attname), campo)
                for campo in campos
            ]
            ws.append(valores)
            celulas = ws[ws.max_row]
            for indice, campo in enumerate(campos):
                if isinstance(campo, models.DateTimeField):
                    celulas[indice].number_format = FORMATO_DATA_HORA
                elif isinstance(campo, models.DateField):
                    celulas[indice].number_format = FORMATO_DATA
            linhas += 1
        contagens.append((nome_aba(modelo), linhas))

    _preencher_leia_me(aba_leia_me, contagens)

    buffer = io.BytesIO()
    livro.save(buffer)
    buffer.seek(0)
    return buffer


_CAMPOS_TEXTO = (models.CharField, models.TextField, models.EmailField)


def _coagir_valor(campo, bruto):
    if bruto is None and isinstance(campo, _CAMPOS_TEXTO) and not campo.null:
        # Célula vazia é NULO (regra do enunciado) — mas um TextField/
        # CharField sem `null=True` grava "" no banco para "sem valor"
        # (mesma convenção de `apps/pca/exportacao.py::_extrair`,
        # só que na direção contrária: aqui é o IMPORT que precisa
        # devolver o texto vazio que a coluna realmente aceita, não `None`
        # — `None` num NOT NULL do SQLite derruba `save()` com
        # `IntegrityError`, mesmo depois de um `full_clean()` que não via
        # problema nenhum (`blank=True` pula a checagem para valores
        # vazios, `None` incluso).
        return ""
    valor = campo.to_python(bruto)
    if isinstance(campo, models.DecimalField) and isinstance(valor, Decimal):
        # openpyxl não tem tipo Decimal — o valor volta como float e
        # `to_python` (context de precisão total) produz dígitos decimais
        # a mais do que `decimal_places` declarado, o que faria o
        # `DecimalValidator` de `full_clean()` recusar até uma linha
        # sem edição nenhuma. Quantiza para o número de casas do campo,
        # preservando o valor monetário real.
        quantizador = Decimal(1).scaleb(-campo.decimal_places)
        valor = valor.quantize(quantizador)
    elif (
        isinstance(campo, models.DateTimeField)
        and isinstance(valor, datetime)
        and timezone.is_naive(valor)
    ):
        # `_valor_exportado` grava naive em horário local (`timezone.
        # localtime().replace(tzinfo=None)`); `DateTimeField.to_python()`
        # devolve naive de volta sem relocalizar — torna aware no MESMO
        # fuso antes do `save()`, ou o Django grava um `RuntimeWarning` e
        # assume UTC em vez do fuso local configurado.
        valor = timezone.make_aware(valor)
    return valor


def ler_planilha_banco(caminho):
    """`dict[model, list[dict[str, Any]]]` — uma entrada por linha de dado
    de cada aba reconhecida (`_leia-me` e abas fora de `MODELO_POR_ABA` são
    ignoradas; colunas desconhecidas ou de `CAMPOS_EXCLUIDOS` também)."""
    livro = load_workbook(caminho, data_only=True)
    dados = {}
    for nome_da_aba in livro.sheetnames:
        if nome_da_aba == "_leia-me":
            continue
        modelo = MODELO_POR_ABA.get(nome_da_aba)
        if modelo is None:
            continue

        ws = livro[nome_da_aba]
        excluidos = CAMPOS_EXCLUIDOS.get(modelo, frozenset())
        campos_por_attname = {
            campo.attname: campo for campo in modelo._meta.concrete_fields
        }

        linhas_brutas = ws.iter_rows(values_only=True)
        try:
            cabecalho = next(linhas_brutas)
        except StopIteration:
            dados[modelo] = []
            continue

        colunas = []
        for indice, nome_coluna in enumerate(cabecalho):
            if nome_coluna in excluidos:
                continue
            campo = campos_por_attname.get(nome_coluna)
            if campo is None:
                continue
            colunas.append((indice, campo))

        linhas = []
        for linha_bruta in linhas_brutas:
            if linha_bruta is None or all(valor is None for valor in linha_bruta):
                continue
            linha = {}
            for indice, campo in colunas:
                bruto = linha_bruta[indice] if indice < len(linha_bruta) else None
                linha[campo.attname] = _coagir_valor(campo, bruto)
            linhas.append(linha)
        dados[modelo] = linhas
    return dados


@dataclass
class DiferencaCampo:
    campo: str
    antigo: Any
    novo: Any


@dataclass
class LinhaAlterada:
    pk: Any
    diferencas: list


@dataclass
class ErroLinha:
    aba: str
    linha: int
    coluna: Any
    motivo: str


@dataclass
class RelatorioAba:
    nome: str
    lidas: int = 0
    novos: list = field(default_factory=list)
    alterados: list = field(default_factory=list)
    erros: list = field(default_factory=list)
    ignorados: int = 0


@dataclass
class RelatorioImportacao:
    abas: list

    @property
    def tem_erros(self):
        return any(aba.erros for aba in self.abas)

    def formatar(self):
        linhas_texto = []
        for aba in self.abas:
            linhas_texto.append(
                f"{aba.nome}: {aba.lidas} lida(s), {len(aba.novos)} nova(s), "
                f"{len(aba.alterados)} alterada(s), {aba.ignorados} sem "
                f"mudança, {len(aba.erros)} erro(s)"
            )
            if aba.alterados:
                linhas_texto.append("  Alterados:")
                for alterado in aba.alterados[:LIMITE_LINHAS_RELATORIO]:
                    detalhe = "; ".join(
                        f"{diferenca.campo}: {diferenca.antigo!r} -> {diferenca.novo!r}"
                        for diferenca in alterado.diferencas
                    )
                    linhas_texto.append(f"    pk={alterado.pk}: {detalhe}")
                excesso = len(aba.alterados) - LIMITE_LINHAS_RELATORIO
                if excesso > 0:
                    linhas_texto.append(f"    +{excesso} mais")
            if aba.erros:
                linhas_texto.append("  Erros:")
                for erro in aba.erros[:LIMITE_LINHAS_RELATORIO]:
                    coluna = erro.coluna or "(geral)"
                    linhas_texto.append(f"    linha {erro.linha}, {coluna}: {erro.motivo}")
                excesso = len(aba.erros) - LIMITE_LINHAS_RELATORIO
                if excesso > 0:
                    linhas_texto.append(f"    +{excesso} mais")
        return "\n".join(linhas_texto)


def _datetime_comparavel(valor):
    if timezone.is_aware(valor):
        valor = timezone.localtime(valor).replace(tzinfo=None)
    return valor.replace(microsecond=0)


def _valores_iguais(valor_antigo, valor_novo):
    # Excel não distingue "aware"/"naive" nem preserva microssegundos —
    # normaliza os dois lados antes de comparar por valor (não por
    # representação), como pede a especificação.
    if isinstance(valor_antigo, datetime) or isinstance(valor_novo, datetime):
        if isinstance(valor_antigo, datetime):
            valor_antigo = _datetime_comparavel(valor_antigo)
        if isinstance(valor_novo, datetime):
            valor_novo = _datetime_comparavel(valor_novo)
    return valor_antigo == valor_novo


def _erros_de_validation(excecao, aba, numero_linha):
    erros = []
    if hasattr(excecao, "message_dict"):
        itens = excecao.message_dict.items()
    else:
        itens = [(NON_FIELD_ERRORS, excecao.messages)]
    for campo, mensagens in itens:
        coluna = None if campo == NON_FIELD_ERRORS else campo
        for mensagem in mensagens:
            erros.append(ErroLinha(aba=aba, linha=numero_linha, coluna=coluna, motivo=mensagem))
    return erros


def calcular_relatorio(dados_planilha):
    """Dry-run puro — nenhuma escrita no banco. Para cada linha: existente
    vira diff campo a campo; nova é validada com `full_clean()` num
    candidato descartado; qualquer `ValidationError` vira `ErroLinha`."""
    abas = []
    for modelo in MODELOS_INCLUIDOS:
        linhas = dados_planilha.get(modelo, [])
        aba_nome = nome_aba(modelo)
        relatorio_aba = RelatorioAba(nome=aba_nome, lidas=len(linhas))
        pk_attname = modelo._meta.pk.attname
        diferidos = list(CAMPOS_DIFERIDOS.get(modelo, ()))

        for numero_linha, linha in enumerate(linhas, start=2):
            pk_valor = linha.get(pk_attname)
            instancia_existente = None
            if pk_valor not in (None, ""):
                instancia_existente = modelo.objects.filter(pk=pk_valor).first()

            if instancia_existente is None:
                dados_construcao = dict(linha)
                if pk_valor in (None, ""):
                    dados_construcao.pop(pk_attname, None)
                try:
                    candidato = modelo(**dados_construcao)
                    candidato.full_clean(exclude=diferidos)
                except ValidationError as excecao:
                    relatorio_aba.erros.extend(
                        _erros_de_validation(excecao, aba_nome, numero_linha)
                    )
                else:
                    relatorio_aba.novos.append(dict(linha))
                continue

            diferencas = []
            for campo in modelo._meta.concrete_fields:
                if campo.attname not in linha or campo.attname == pk_attname:
                    continue
                valor_novo = linha[campo.attname]
                valor_antigo = getattr(instancia_existente, campo.attname)
                if not _valores_iguais(valor_antigo, valor_novo):
                    diferencas.append(
                        DiferencaCampo(campo.attname, valor_antigo, valor_novo)
                    )
            if diferencas:
                # Uma linha existente editada também precisa passar por
                # `full_clean()` — sem isso, uma FK trocada por um pk
                # inexistente (ou qualquer outra violação) só estouraria
                # dentro de `aplicar_relatorio`, depois do backup já feito
                # e sem produzir `ErroLinha` nenhum na conferência (a
                # aplicação inteira "tudo-ou-nada" ainda protegeria o
                # banco via `transaction.atomic()`, mas o usuário veria um
                # erro 500 cru em vez do relatório de erros do Passo 2).
                # Valida na PRÓPRIA instância buscada (não persistida aqui
                # — `calcular_relatorio` nunca escreve no banco).
                for diferenca in diferencas:
                    setattr(instancia_existente, diferenca.campo, diferenca.novo)
                try:
                    instancia_existente.full_clean(exclude=diferidos)
                except ValidationError as excecao:
                    relatorio_aba.erros.extend(
                        _erros_de_validation(excecao, aba_nome, numero_linha)
                    )
                else:
                    relatorio_aba.alterados.append(LinhaAlterada(pk_valor, diferencas))
            else:
                relatorio_aba.ignorados += 1

        abas.append(relatorio_aba)
    return RelatorioImportacao(abas)


def aplicar_relatorio(dados_planilha, usuario):
    """Assume já estar dentro de `transaction.atomic()` do chamador. Upsert
    por pk (`objects.get(pk=...)` + `setattr` para existente — nunca
    `model(pk=..., **campos)`, que forçaria um INSERT sobre pk existente);
    `Processo.origem` em duas passagens via `CAMPOS_DIFERIDOS`."""
    resultado = {}
    instancias_por_modelo = {}

    for modelo in MODELOS_INCLUIDOS:
        linhas = dados_planilha.get(modelo, [])
        pk_attname = modelo._meta.pk.attname
        diferidos = set(CAMPOS_DIFERIDOS.get(modelo, ()))
        excluidos = CAMPOS_EXCLUIDOS.get(modelo, frozenset())
        criados = 0
        atualizados = 0
        instancias = []

        for linha in linhas:
            pk_valor = linha.get(pk_attname)
            instancia_existente = None
            if pk_valor not in (None, ""):
                instancia_existente = modelo.objects.filter(pk=pk_valor).first()

            campos_aplicaveis = {
                chave: valor
                for chave, valor in linha.items()
                if chave not in diferidos and chave not in excluidos
            }

            if instancia_existente is not None:
                instancia = instancia_existente
                for campo_attname, valor in campos_aplicaveis.items():
                    if campo_attname == pk_attname:
                        continue
                    setattr(instancia, campo_attname, valor)
            else:
                dados_construcao = dict(campos_aplicaveis)
                if pk_valor in (None, ""):
                    dados_construcao.pop(pk_attname, None)
                instancia = modelo(**dados_construcao)

            era_criacao = instancia._state.adding
            instancia._history_user = usuario
            instancia._change_reason = "Importação XLSX do banco"
            instancia.full_clean(exclude=list(diferidos))
            instancia.save()

            if era_criacao:
                criados += 1
            else:
                atualizados += 1
            instancias.append((linha, instancia))

        resultado[modelo] = {"criados": criados, "atualizados": atualizados}
        instancias_por_modelo[modelo] = instancias

    for modelo, campos_diferidos in CAMPOS_DIFERIDOS.items():
        for linha, instancia in instancias_por_modelo.get(modelo, []):
            mudou = False
            for campo_attname in campos_diferidos:
                if campo_attname not in linha:
                    continue
                novo_valor = linha[campo_attname]
                if getattr(instancia, campo_attname) != novo_valor:
                    setattr(instancia, campo_attname, novo_valor)
                    mudou = True
            if mudou:
                instancia._history_user = usuario
                instancia._change_reason = "Importação XLSX do banco"
                instancia.full_clean()
                instancia.save()

    return resultado


def fazer_backup_sqlite():
    """`None` fora do SQLite; senão, `sqlite3.Connection.backup()` nativo
    para `<dir-do-banco>/backups/pre-import-AAAAMMDD_HHMMSS.sqlite3`. Erros
    do sqlite/SO propagam — o chamador decide abortar a importação."""
    if connection.vendor != "sqlite":
        return None

    connection.ensure_connection()
    if not connection.get_autocommit():
        # `sqlite3.Connection.backup()` faz `sqlite3_backup_step` em loop,
        # dormindo e retentando pra sempre em SQLITE_BUSY — chamado com uma
        # transação aberta na MESMA conexão, trava para sempre em vez de
        # falhar (não é retry limitado). `confirmar_view` já chama esta
        # função ANTES de abrir `transaction.atomic()`; esta
        # guarda transforma um travamento silencioso em erro imediato.
        raise RuntimeError(
            "fazer_backup_sqlite() não pode rodar dentro de uma transação "
            "aberta — chame antes de transaction.atomic()."
        )
    origem = connection.connection
    caminho_banco = Path(connection.settings_dict["NAME"])
    diretorio_backups = caminho_banco.parent / "backups"
    diretorio_backups.mkdir(parents=True, exist_ok=True)
    destino_caminho = (
        diretorio_backups / f"pre-import-{timezone.localtime():%Y%m%d_%H%M%S}.sqlite3"
    )

    destino = sqlite3.connect(str(destino_caminho))
    try:
        origem.backup(destino)
    finally:
        destino.close()
    return destino_caminho
