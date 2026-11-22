"""Núcleo do import (01-04), extraído de
`apps/pca/management/commands/importar_pca.py` (07-02): a regra de
import passa a existir num único lugar reutilizável, chamado tanto pelo
comando de CLI quanto pela tela de importação do admin (07-03). Extração
comportamentalmente neutra — `apps/pca/tests/test_import.py` continua
passando sem edição.

Nunca `django-import-export` com `use_bulk=True`, que desliga
`post_save`/`pre_save` e mata o histórico (ver Alternatives Considered). Lê `Modelo_de_Controle_.xlsx`, normaliza via
`apps.pca.importacao.parsers`, grava com histórico sob o usuário de serviço,
é idempotente em reexecução e emite o relatório de
conferência nominal mesmo sob `--dry-run`.
"""

import zipfile
from decimal import Decimal, InvalidOperation

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils.timezone import localdate
from simple_history.utils import bulk_create_with_history

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.catalogo.utils import normalizar_nome
from apps.pca.importacao.parsers import (
    parse_data_excel,
    parse_mes_previsto,
    parse_numeros_sei,
    parse_status,
)
from apps.pca.importacao.relatorio import Relatorio
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    ProcessoSEI,
    Reuniao,
    Situacao,
    SituacaoReuniao,
)
from apps.pca.regras_situacao import situacao_inicial
from apps.pca.utils import calcular_origem_hash

# Fase 17 — os mesmos 5 rótulos de `STATUS_POR_ROTULO`
# (`parsers.py`), como conjunto literal: o enum antigo `Status` não é mais
# fonte de verdade para o import (removido do domínio vivo pelo Plano
# 17-11 — o slug legado é usado aqui só para decidir `estado`, nunca
# gravado no banco).
STATUS_LEGADO_VALIDOS = {
    "concluido", "nao_iniciado", "em_tramitacao", "vigente", "cancelado",
}

USUARIO_PADRAO = "importador@pca.local"
MOTIVO_HISTORICO = "import inicial"

# (rótulo da coluna na aba `Listas` -> modelo de catálogo). 8 colunas de
# domínio — Status e Situação do SEI são `TextChoices` no
# código, "UO (Nova Estrutura)" e "Situação do Prazo (derivada)" ficam fora
# do escopo do MVP (documento do projeto, Out of Scope).
COLUNAS_CATALOGO = [
    ("Tipo de Contratação", Tipo),
    ("Categoria", Categoria),
    ("UO (Área Demandante)", Unidade),
    ("Grau de Prioridade", GrauPrioridade),
    ("Classificação", Classificacao),
    ("Modalidade", Modalidade),
    ("Instrumento Contratual", InstrumentoContratual),
    ("Situação Normalizada", SituacaoNormalizada),
]

# `Tipo de Evento` é `TextChoices` de `apps.pca.models` — mapeado
# aqui por rótulo literal, como `STATUS_POR_ROTULO` em `parsers.py`, para
# não forçar `parsers.py` a importar `django.db.models`. A coluna 40
# ("Situação do SEI") continua no layout da planilha, mas é IGNORADA desde a
# Ter ou não processo SEI vem do próprio nº SEI.
TIPO_EVENTO_POR_ROTULO = {
    "Reunião de acompanhamento": "reuniao_acompanhamento",
    "Gestão de Riscos": "gestao_riscos",
    # Fase 17.1 — descoberto ao escrever
    # `gerar_modelo_preenchido`: 11 acompanhamentos reais têm
    # `tipo_evento="automatico"` (TipoEvento.AUTOMATICO, models.py),
    # gravados por `aplicar_regras_automaticas`/correções retroativas. Sem
    # esta entrada, o rótulo "Automático" escrito no modelo pré-preenchido
    # não seria reconhecido no reimport — `.get(..., "")` silenciosamente
    # zeraria o campo em vez de estourar erro, quebrando (round-trip
    # byte a byte) para essas 11 linhas.
    "Automático": "automatico",
}


def _texto(valor):
    """CharField tolerante a lixo de planilha (algumas células trazem tipo
    errado, ex. data numa coluna de texto) — nunca deixa passar um tipo não
    string para o ORM, mas também nunca inventa conteúdo."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


# QA 30/09/2026 (dados A1) — max_digits=14/decimal_places=2 dos campos
# monetários do model; um valor reconhecível mas fora desta faixa (ou
# NaN/Infinito) levanta `ValorMonetarioInvalido` em vez de gravar lixo ou
# estourar `IntegrityError` cru mais adiante.
LIMITE_VALOR_MONETARIO = Decimal("999999999999.99")  # max_digits=14, decimal_places=2


class ValorMonetarioInvalido(Exception):
    """Levantada só quando a célula tem algo reconhecível como número mas
    fora da faixa (NaN/Infinito ou módulo maior que o limite); célula
    vazia ou texto não numérico continuam `None` ("não reconheço, não
    invento")."""


def _decimal(valor):
    if valor is None:
        return None
    bruto = str(valor).strip()
    if not bruto:
        return None
    # QA 30/09/2026 (dados M2, barato) — leitura de valor mascarado pt-BR
    # ("R$ 1.234,56"/"1.234,56") de graça: a presença de vírgula é o sinal
    # de forma mascarada, mesmo critério de `views._normalizar_valor_
    # monetario`.
    normalizado = bruto.replace("R$", "").replace(" ", "")
    if "," in normalizado:
        normalizado = normalizado.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(normalizado)
    except InvalidOperation:
        return None
    if not numero.is_finite() or abs(numero) > LIMITE_VALOR_MONETARIO:
        raise ValorMonetarioInvalido(bruto)
    return numero.quantize(Decimal("0.01"))


class ImportadorPca:
    """Orquestração do import para um `exercicio` específico — ex-métodos
    privados de `Command`, movidos aqui na íntegra."""

    def __init__(self, exercicio):
        self.exercicio = exercicio

    @staticmethod
    def _decimal_do_item(bruto, item_pca, rotulo_campo):
        try:
            return _decimal(bruto)
        except ValorMonetarioInvalido as exc:
            raise CommandError(
                f"Processo {item_pca}: {rotulo_campo} '{exc}' é inválido "
                "(NaN/Infinito, ou maior que R$ 999.999.999.999,99) — corrija "
                "a planilha antes de importar."
            ) from exc

    # -- Orquestração ------------------------------------------------------

    def importar(self, workbook, usuario, relatorio):
        mapas_catalogo = self._upsert_catalogo(workbook["Listas"])
        # Fase 17 (emendada) — a promessa vigente por
        # item vem da PLANILHA (openpyxl), não do banco: `Acompanhamento`
        # ainda não existe para os itens novos neste ponto do fluxo, e a
        # planilha de reimport traz o histórico completo desde o início.
        mapa_prazo_vigente = self._mapa_prazo_vigente(workbook["Acompanhamento"])
        mapa_item_para_pk = self._importar_processos(
            workbook["Planilha1"], usuario, mapas_catalogo, relatorio,
            mapa_prazo_vigente,
        )
        self._importar_acompanhamentos(
            workbook["Acompanhamento"],
            usuario,
            mapas_catalogo,
            mapa_item_para_pk,
            relatorio,
        )

    def _mapa_prazo_vigente(self, aba_acompanhamento):
        """emendada (29/08/2026, gap 1) — varre a aba
        Acompanhamento UMA VEZ e devolve `{item_pca: prazo_prometido}` só com
        a promessa de MAIOR `referencia_data` por item (mesmo critério de
        desempate "mais recente" que `ProcessoQuerySet.para_listagem()` usa
        para `prazo_vigente`: maior data primeiro, e entre datas iguais, a
        última encontrada na varredura — que corresponde à ordem de inserção
        no banco, aproximando o desempate por maior id). Linhas sem
        `referencia_data` ou sem `prazo_prometido` são ignoradas."""
        linhas = list(aba_acompanhamento.iter_rows(min_row=2, values_only=True))
        mapa_data_mais_recente = {}
        mapa_prazo = {}
        for linha in linhas:
            item_processo = linha[1]
            if item_processo is None:
                continue
            referencia_data = parse_data_excel(linha[3])
            prazo_prometido = parse_data_excel(linha[8])
            if referencia_data is None or prazo_prometido is None:
                continue
            data_atual = mapa_data_mais_recente.get(item_processo)
            if data_atual is None or referencia_data >= data_atual:
                mapa_data_mais_recente[item_processo] = referencia_data
                mapa_prazo[item_processo] = prazo_prometido
        return mapa_prazo

    # -- Catálogo (upsert por nome_normalizado, nunca apaga) ---------

    def _upsert_catalogo(self, aba_listas):
        cabecalho = [c.value for c in next(aba_listas.iter_rows(min_row=1, max_row=1))]
        linhas = list(aba_listas.iter_rows(min_row=2, values_only=True))

        mapas = {}
        for nome_coluna, modelo in COLUNAS_CATALOGO:
            idx = cabecalho.index(nome_coluna)
            mapa_normalizado = {}
            for linha in linhas:
                valor = linha[idx] if idx < len(linha) else None
                if not valor:
                    continue
                # QA 30/09/2026 (dados M3) — rótulo importado nunca carrega
                # espaço nas pontas; número na coluna errada continua
                # caindo no TypeError genérico (convertido em CommandError
                # mais acima).
                if isinstance(valor, str):
                    valor = valor.strip()
                    if not valor:
                        continue
                chave = normalizar_nome(valor)
                if chave in mapa_normalizado:
                    continue
                instancia, criado = modelo.objects.get_or_create(
                    nome_normalizado=chave, defaults={"nome": valor}
                )
                if not criado and instancia.nome != valor:
                    instancia.nome = valor
                    instancia.save()
                mapa_normalizado[chave] = instancia
            mapas[modelo] = mapa_normalizado
        return mapas

    def _resolver_fk(self, mapa, valor, *, obrigatorio=False, item_pca=None, campo=None):
        if not valor:
            if obrigatorio:
                raise CommandError(
                    f"Processo {item_pca}: campo obrigatório '{campo}' vazio na planilha."
                )
            return None
        instancia = mapa.get(normalizar_nome(valor))
        if instancia is None:
            if obrigatorio:
                raise CommandError(
                    f"Processo {item_pca}: valor '{valor}' de '{campo}' não "
                    "consta na aba Listas."
                )
            return None
        return instancia

    # -- Processo (upsert por item_pca, só insere o que falta) --

    def _importar_processos(
        self, aba_planilha1, usuario, mapas_catalogo, relatorio,
        mapa_prazo_vigente=None,
    ):
        # Fase 29 — `min_row=2` pula a linha 1
        # (cabeçalho) por completo: nunca lida por texto, só por POSIÇÃO
        # fixa (`linha[N]`, ver abaixo). Um arquivo com "Prazo inicial" em
        # vez de "Data prevista para entrega" na coluna 14 (o rótulo novo
        # de tela/XLSX) importa IDÊNTICO a um com o cabeçalho
        # histórico — o texto da célula A1..AN1 é só decorativo para quem
        # abre a planilha, `_importar_processos` nunca compara contra
        # `CABECALHOS_PLANILHA1`.
        mapa_prazo_vigente = mapa_prazo_vigente or {}
        linhas = list(aba_planilha1.iter_rows(min_row=2, values_only=True))
        existentes = dict(
            Processo.objects.filter(exercicio=self.exercicio).values_list(
                "item_pca", "pk"
            )
        )

        novos = []
        numeros_sei_por_item = {}

        for linha in linhas:
            item_pca = linha[0]
            if item_pca is None:
                continue  # linha em branco no rodapé da aba

            if item_pca in existentes:
                relatorio.registrar_processo_ignorado()
                continue

            mes_bruto = linha[8]
            mes_previsto = parse_mes_previsto(mes_bruto)
            if mes_bruto and mes_previsto is None:
                # Item 137 (e qualquer outro caso futuro do mesmo tipo).
                relatorio.registrar_mes_ambiguo(item_pca)

            data_envio = parse_data_excel(linha[12])
            data_entrega = parse_data_excel(linha[14])
            if data_envio and data_entrega and data_entrega < data_envio:
                relatorio.registrar_entrega_anterior_ao_envio(
                    item_pca, data_envio, data_entrega
                )

            grau_prioridade = self._resolver_fk(mapas_catalogo[GrauPrioridade], linha[10])
            classificacao = self._resolver_fk(mapas_catalogo[Classificacao], linha[11])
            if grau_prioridade is None and classificacao is None:
                relatorio.registrar_sem_prioridade_e_classificacao(item_pca)

            numeros_sei = parse_numeros_sei(linha[1])
            if len(numeros_sei) > 1:
                relatorio.registrar_multiplos_sei(item_pca, numeros_sei)
            numeros_sei_por_item[item_pca] = numeros_sei

            status_legado = parse_status(linha[16])
            if status_legado not in STATUS_LEGADO_VALIDOS:
                raise CommandError(
                    f"Processo {item_pca}: status '{linha[16]}' não é mais "
                    "suportado pelo sistema. Revise a linha na planilha "
                    "antes de importar."
                )

            tipo_resolvido = self._resolver_fk(
                mapas_catalogo[Tipo], linha[4],
                obrigatorio=True, item_pca=item_pca, campo="tipo de contratação",
            )
            estado_valor = (
                Estado.CANCELADO if status_legado == "cancelado" else Estado.ATIVO
            )
            situacao_valor = situacao_inicial(
                tipo_nome_normalizado=tipo_resolvido.nome_normalizado,
                data_assinatura_contrato=parse_data_excel(linha[35]),
                data_recebimento_gelic=data_entrega,
                prazo_entrega=parse_data_excel(linha[13]),
                prazo_vigente=mapa_prazo_vigente.get(item_pca),
                hoje=localdate(),
            )

            novos.append(
                Processo(
                    item_pca=item_pca,
                    exercicio=self.exercicio,
                    descricao_objeto=_texto(linha[2]) or "",
                    justificativa=_texto(linha[3]) or "",
                    tipo=tipo_resolvido,
                    categoria=self._resolver_fk(
                        mapas_catalogo[Categoria], linha[5],
                        obrigatorio=True, item_pca=item_pca, campo="categoria",
                    ),
                    unidade_organizacional=self._resolver_fk(
                        mapas_catalogo[Unidade], linha[6],
                        obrigatorio=True, item_pca=item_pca, campo="UO",
                    ),
                    valor_estimado=self._decimal_do_item(
                        linha[7], item_pca, "valor estimado"
                    ),
                    mes_previsto=mes_previsto,
                    data_inclusao_pca=parse_data_excel(linha[9]),
                    grau_prioridade=grau_prioridade,
                    classificacao=classificacao,
                    data_envio_gelic=data_envio,
                    prazo_entrega=parse_data_excel(linha[13]),
                    data_recebimento_gelic=data_entrega,
                    data_prevista_conclusao=parse_data_excel(linha[15]),
                    estado=estado_valor,
                    situacao=situacao_valor,
                    # Bloco de execução contratual — colunas 25-39,
                    # 0-6 preenchimentos reais hoje; a Fase 4 acrescenta
                    # telas, o schema já nasce completo.
                    # Fase 15: a coluna 24 ("Data Recebimento do
                    # Processo") fundiu-se em `data_recebimento_gelic`
                    # acima (zero preenchimentos reais em ambos os lados —
                    # nunca dado com conflito a arbitrar); o campo
                    # `data_recebimento_processo` saiu do modelo, então esta
                    # coluna deixa de ser lida aqui.
                    modalidade=self._resolver_fk(mapas_catalogo[Modalidade], linha[25]),
                    vigencia_inicio=parse_data_excel(linha[26]),
                    vigencia_fim=parse_data_excel(linha[27]),
                    numero_contratacao=_texto(linha[28]),
                    numero_arp=_texto(linha[29]),
                    instrumento_contratual=self._resolver_fk(
                        mapas_catalogo[InstrumentoContratual], linha[30]
                    ),
                    numero_instrumento_contratual=_texto(linha[31]),
                    valor_contratado=self._decimal_do_item(
                        linha[32], item_pca, "valor contratado"
                    ),
                    fornecedor_cnpj=_texto(linha[33]),
                    fornecedor_razao_social=_texto(linha[34]),
                    data_assinatura_contrato=parse_data_excel(linha[35]),
                    data_lancamento_spw=parse_data_excel(linha[36]),
                    data_lancamento_wordpress=parse_data_excel(linha[37]),
                    data_lancamento_dados_abertos=parse_data_excel(linha[38]),
                )
            )

        criados = bulk_create_with_history(
            novos,
            Processo,
            batch_size=200,
            default_user=usuario,
            default_change_reason=MOTIVO_HISTORICO,
        )
        # Postgres devolve PK preenchido via RETURNING — sem 2ª query.
        mapa_item_para_pk = {
            (self.exercicio.pk, item_pca): pk for item_pca, pk in existentes.items()
        }
        mapa_item_para_pk.update(
            {(self.exercicio.pk, p.item_pca): p.pk for p in criados}
        )

        sei_novos = [
            ProcessoSEI(processo_id=processo.pk, numero_sei=numero)
            for processo in criados
            for numero in numeros_sei_por_item.get(processo.item_pca, [])
        ]
        if sei_novos:
            # ProcessoSEI não tem HistoricalRecords (é detalhe de Processo,
            # ver models.py) — bulk_create comum é correto aqui.
            ProcessoSEI.objects.bulk_create(sei_novos)

        relatorio.registrar_processos_criados(len(criados))
        return mapa_item_para_pk

    # -- Acompanhamento (upsert por origem_hash) ----------------------

    def _reuniao_de(self, referencia_data, cache):
        """Uma `Reuniao` por data de referência distinta, criada sob demanda e
        memorizada na chamada. FECHADA de propósito: são reuniões que já
        aconteceram, e uma reunião aberta seria lida como "reunião corrente"
        pelo serviço de domínio."""
        if referencia_data not in cache:
            cache[referencia_data], _ = Reuniao.objects.get_or_create(
                data=referencia_data,
                defaults={
                    "situacao": SituacaoReuniao.FECHADA,
                    "exercicio": self.exercicio,
                },
            )
        return cache[referencia_data]

    def _importar_acompanhamentos(
        self, aba_acompanhamento, usuario, mapas_catalogo, mapa_item_para_pk, relatorio
    ):
        linhas = list(aba_acompanhamento.iter_rows(min_row=2, values_only=True))

        candidatos = []
        for linha in linhas:
            item_processo = linha[1]
            chave_processo = (self.exercicio.pk, item_processo)
            if item_processo is None or chave_processo not in mapa_item_para_pk:
                continue  # linha em branco, ou orfã de um processo inexistente
            referencia_data = parse_data_excel(linha[3])
            if referencia_data is None:
                continue  # defensivo — os 381 registros reais sempre têm data
            situacao_informada = _texto(linha[6]) or ""
            origem_hash = calcular_origem_hash(
                self.exercicio.ano, item_processo, referencia_data, situacao_informada
            )
            candidatos.append(
                (
                    origem_hash,
                    chave_processo,
                    referencia_data,
                    situacao_informada,
                    linha,
                )
            )

        hashes_candidatos = [c[0] for c in candidatos]
        hashes_existentes = set(
            Acompanhamento.objects.filter(
                origem_hash__in=hashes_candidatos
            ).values_list("origem_hash", flat=True)
        )

        novos = []
        ignorados = 0
        # Fase 17.1 — descoberto pelo round-trip de
        # `gerar_modelo_preenchido`: acompanhamentos criados pela UI
        # (`services.py::registrar_acompanhamento`/`alterar_estado`) usam um
        # hash salgado com UUID, sem relação com a chave natural
        # (ano+item+data+texto) — dois registros reais podem coexistir no
        # banco com essa chave natural idêntica. Sem este `set`, DUAS linhas
        # NOVAS do mesmo lote com o mesmo `origem_hash` recomputado
        # estourariam `UniqueViolation` no `bulk_create` (a checagem contra
        # `hashes_existentes`, sozinha, só cobre colisão com o que já está
        # no banco, nunca colisão dentro do próprio lote). (idempotência
        # por hash) se estende ao próprio lote: a segunda ocorrência do mesmo
        # hash é tratada como "já existe" e contabilizada como ignorada, não
        # como erro fatal.
        hashes_no_lote = set()
        # A migração `0003_reuniao_versao_otimista` faz o backfill das 7
        # reuniões da base já importada, mas uma instalação nova roda `migrate`
        # ANTES do `importar_pca` (e este projeto já perdeu o volume do banco
        # duas vezes, ver STATE.md). Sem associar a reunião aqui também, o
        # reimport deixaria os 381 acompanhamentos avulsos e `n_reunioes`
        #exibiria 0 para os 149 processos na tabela e no export.
        reunioes = {}
        for origem_hash, chave_processo, referencia_data, situacao_informada, linha in candidatos:
            if origem_hash in hashes_existentes or origem_hash in hashes_no_lote:
                ignorados += 1
                continue
            hashes_no_lote.add(origem_hash)

            situacao = self._resolver_fk(
                mapas_catalogo[SituacaoNormalizada], linha[7],
                obrigatorio=True,
                item_pca=chave_processo[1],
                campo="situação normalizada",
            )
            novos.append(
                Acompanhamento(
                    processo_id=mapa_item_para_pk[chave_processo],
                    referencia_data=referencia_data,
                    reuniao=self._reuniao_de(referencia_data, reunioes),
                    origem_hash=origem_hash,
                    evento=_texto(linha[4]) or "",
                    tipo_evento=TIPO_EVENTO_POR_ROTULO.get(_texto(linha[5]) or "", ""),
                    situacao_informada=situacao_informada,
                    situacao=situacao,
                    prazo_prometido=parse_data_excel(linha[8]),
                    data_evento_informada=parse_data_excel(linha[9]),
                    area_informada=_texto(linha[10]) or "",
                )
            )

        bulk_create_with_history(
            novos,
            Acompanhamento,
            batch_size=500,
            default_user=usuario,
            default_change_reason=MOTIVO_HISTORICO,
        )
        relatorio.registrar_acompanhamentos_criados(len(novos))
        relatorio.registrar_acompanhamentos_ignorados(ignorados)


def executar_import(caminho, usuario, exercicio, dry_run, escrever_stdout=None):
    """Núcleo do import — abre `caminho`, roda a importação inteira
    dentro de uma transação (com `set_rollback(True)` se `dry_run`) e devolve
    o `Relatorio` já preenchido. Levanta `CommandError` se o arquivo não
    abrir — mesmo tipo de exceção que `Command.handle` já levantava antes da
    extração, para que quem chama (CLI ou, no plano, a view do admin)
    trate de um jeito só.

    `relatorio.caminho_relatorio` fica setado com o `Path` que
    `Relatorio.emitir()` devolveu, para quem chama não precisar emitir um
    segundo `.md` só para saber onde o primeiro foi gravado.
    """
    try:
        workbook = openpyxl.load_workbook(caminho, data_only=True)
    except (FileNotFoundError, OSError, zipfile.BadZipFile, InvalidFileException) as exc:
        # QA de segurança 30/09/2026 (achado B3) — um `.xlsx` cujo conteúdo
        # não é um ZIP válido levanta `zipfile.BadZipFile` (ou
        # `InvalidFileException`, para outros formatos que a openpyxl
        # reconhece como inválidos) por dentro da própria `load_workbook`;
        # sem esta ampliação, a exceção escapava como 500. `views.py::
        # importar_view` já captura `CommandError` com `form.add_error`,
        # então nenhuma outra mudança é necessária nas views.
        raise CommandError(f"Não foi possível abrir '{caminho}': {exc}") from exc

    relatorio = Relatorio(arquivo_fonte=caminho, dry_run=dry_run)
    importador = ImportadorPca(exercicio)

    with transaction.atomic():
        # QA 30/09/2026 (dados M1) — planilha estruturalmente inválida (aba
        # faltando -> KeyError; cabeçalho trocado -> ValueError; colunas
        # apagadas -> IndexError; número onde se espera texto -> TypeError;
        # item duplicado/negativo/gigante -> IntegrityError/OverflowError/
        # ValueError) termina em CommandError amigável, nunca traceback
        # cru; a exceção ainda propaga de dentro do transaction.atomic(),
        # rollback automático garantido.
        try:
            importador.importar(workbook, usuario, relatorio)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            OverflowError,
            IntegrityError,
            ValidationError,
        ) as exc:
            raise CommandError(
                f"Planilha incompatível com o modelo de importação "
                f"({type(exc).__name__}: {exc}). Baixe o modelo atualizado e "
                "confira abas, cabeçalhos e colunas antes de reimportar."
            ) from exc
        caminho_relatorio = relatorio.emitir(escrever_stdout or (lambda texto: None))
        if dry_run:
            # Preserva o relatório já montado/gravado; não persiste nada.
            transaction.set_rollback(True)

    relatorio.caminho_relatorio = caminho_relatorio
    return relatorio
