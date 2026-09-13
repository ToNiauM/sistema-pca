"""Gera a fixture pública anonimizada, reaproveitando
gerar_modelo_preenchido — mas populando o banco primeiro com 30
Processo/Acompanhamento inteiramente fictícios, em vez de ler dados reais.

Reexecutável/idempotente: sempre apaga e recria os Processo (em cascata,
Acompanhamento/ProcessoSEI) do exercício-alvo antes de recriá-los; os
catálogos de vocabulário usam get_or_create e nunca são apagados. Nunca lê
nem referencia nenhum dado real: nomes, objetos, justificativas, números
de processo SEI e valores são todos inventados por este módulo.

Uso: manage.py migrate && manage.py gerar_fixture_exemplo."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.importacao.modelo import gerar_modelo_preenchido
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    ProcessoSEI,
    TipoEvento,
)
from apps.pca.regras_situacao import situacao_inicial

CAMINHO_FIXTURE = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"
ANO_EXERCICIO_FIXTURE = 2026

# CNPJ fictício de 14 dígitos usado como prefixo dos números SEI sintéticos
CNPJ_FICTICIO_SEI = "12345678000199"

UNIDADES = [
    "Unidade de Compras",
    "Unidade de Tecnologia da Informação",
    "Unidade de Administração",
    "Unidade de Recursos Humanos",
    "Unidade de Infraestrutura",
]
TIPOS = ["Nova Contratação", "Renovação", "Vigente"]
CATEGORIAS = ["Serviços", "Solução de TIC", "Material"]
GRAUS_PRIORIDADE = ["Alta", "Média", "Baixa"]
CLASSIFICACOES = ["Padrão", "Estratégica", "Continuidade"]
MODALIDADES = ["Pregão Eletrônico", "Dispensa de Licitação", "Inexigibilidade de Licitação"]
INSTRUMENTOS = ["Contrato", "Ata de Registro de Preços", "Termo de Adesão"]
# "Sem informação"/"Em tramitação"/"Concluído" são rótulos exatos exigidos
# pelo modal "Registrar acompanhamento"; "Atrasado"/"Aguardando retorno"
# são só narrativa extra do import
SITUACOES_NORMALIZADAS = [
    "Sem informação", "Em tramitação", "Concluído", "Atrasado", "Aguardando retorno",
]

OBJETOS = [
    "Aquisição de material de escritório",
    "Contratação de serviço de manutenção predial",
    "Aquisição de licenças de software",
    "Contratação de serviço de limpeza e conservação",
    "Aquisição de equipamentos de informática",
    "Contratação de serviço de vigilância patrimonial",
    "Aquisição de mobiliário para escritório",
    "Contratação de serviço de telefonia móvel",
    "Aquisição de material de consumo para laboratório",
    "Contratação de serviço de desenvolvimento de sistema",
]
JUSTIFICATIVAS = [
    "Necessário para manter a continuidade das atividades administrativas.",
    "Demanda identificada no planejamento anual da unidade.",
    "Renovação de contrato vigente para evitar solução de continuidade.",
    "Atendimento a necessidade operacional identificada pela área técnica.",
    "Substituição de bens com vida útil esgotada.",
    "Ampliação da capacidade operacional da unidade demandante.",
    "Adequação a norma técnica ou legal aplicável.",
    "Modernização de processo interno de trabalho.",
    "Suporte à execução de projeto estratégico da instituição.",
    "Reposição de estoque mínimo de material de consumo.",
]

# fornecedores fictícios com CNPJ de checksum válido, usados só no bloco
# de execução contratual dos itens "concluídos"
FORNECEDORES = [
    ("11.122.233/0001-83", "Fornecedor Exemplo Um Ltda"),
    ("22.233.344/0001-83", "Fornecedor Exemplo Dois Ltda"),
    ("33.344.455/0001-83", "Fornecedor Exemplo Três Ltda"),
]

# cada tupla: (item_pca, tipo, categoria, unidade, estado, situacao_sei,
# data_recebimento_gelic, data_assinatura_contrato, prazo_entrega,
# numeros_sei_extra). situacao nunca é hardcoded aqui — é sempre derivada
# de situacao_inicial() mais abaixo
#
# datas deliberadamente fixas e distantes de "hoje": ATRASADO usa um prazo
# de 2024 (sempre vencido); NO_PRAZO não tem prazo nenhum (cai no fallback
# "sem prazo => no prazo") — os números ficam estáveis para sempre
_PRAZO_ATRASADO = date(2024, 1, 15)

# item 13 carrega de propósito uma anomalia "envio depois do recebimento"
# para a fixture continuar exercitando esse caminho do relatório de
# conferência.
# item_pca=1 é o "cobaia" convencional de vários testes, sempre mutado à
# vontade — por isso nunca pode ser Tipo=Vigente nem ter
# data_assinatura_contrato/data_recebimento_gelic, que travariam a
# situacao de volta via aplicar_regras_automaticas(). Por isso o conteúdo
# do item 1 e do item 24 é trocado em relação a uma primeira versão desta
# fixture; os números de item continuam sequenciais 1-30, só o conteúdo
# de cada um mudou de posição
ITENS = [
    # --- Bloco CONCLUÍDO (8 itens): Tipo=Vigente conclui por natureza, ou
    # data_assinatura_contrato preenchida. ---
    (1, "Nova Contratação", "Serviços", "Unidade de Recursos Humanos", Estado.ATIVO, "autuado", None, None, None, ()),
    (2, "Vigente", "Serviços", "Unidade de Tecnologia da Informação", Estado.ATIVO, "autuado", None, None, None, ()),
    (3, "Vigente", "Material", "Unidade de Administração", Estado.ATIVO, "a_autuar", None, None, None, ()),
    (4, "Vigente", "Solução de TIC", "Unidade de Recursos Humanos", Estado.ATIVO, "autuado", None, None, None, ()),
    (5, "Vigente", "Serviços", "Unidade de Infraestrutura", Estado.CANCELADO, "nao_se_aplica", None, None, None, ()),
    (6, "Nova Contratação", "Serviços", "Unidade de Compras", Estado.ATIVO, "autuado", None, date(2026, 4, 10), None, ()),
    (7, "Renovação", "Solução de TIC", "Unidade de Tecnologia da Informação", Estado.ATIVO, "autuado", None, date(2026, 5, 12), None, (2,)),
    (8, "Nova Contratação", "Serviços", "Unidade de Administração", Estado.CANCELADO, "a_autuar", None, date(2026, 3, 20), None, ()),
    # --- Bloco EM TRAMITAÇÃO (8 itens): data_recebimento_gelic preenchida,
    # sem assinatura, tipo != Vigente. ---
    (9, "Nova Contratação", "Serviços", "Unidade de Recursos Humanos", Estado.ATIVO, "autuado", date(2026, 6, 15), None, None, ()),
    (10, "Renovação", "Serviços", "Unidade de Infraestrutura", Estado.ATIVO, "autuado", date(2026, 6, 20), None, None, ()),
    (11, "Nova Contratação", "Solução de TIC", "Unidade de Compras", Estado.ATIVO, "a_autuar", date(2026, 7, 1), None, None, ()),
    (12, "Renovação", "Material", "Unidade de Tecnologia da Informação", Estado.ATIVO, "autuado", date(2026, 7, 10), None, None, ()),
    (13, "Nova Contratação", "Serviços", "Unidade de Administração", Estado.ATIVO, "autuado", date(2026, 5, 25), None, None, ()),
    (14, "Renovação", "Serviços", "Unidade de Recursos Humanos", Estado.ATIVO, "a_autuar", date(2026, 8, 5), None, None, ()),
    (15, "Nova Contratação", "Solução de TIC", "Unidade de Infraestrutura", Estado.ATIVO, "autuado", date(2026, 8, 15), None, None, ()),
    (16, "Renovação", "Serviços", "Unidade de Compras", Estado.CANCELADO, "nao_se_aplica", date(2026, 8, 20), None, None, ()),
    # --- Bloco ATRASADO (7 itens): sem evento gravado, prazo vencido. ---
    (17, "Nova Contratação", "Serviços", "Unidade de Tecnologia da Informação", Estado.ATIVO, "autuado", None, None, _PRAZO_ATRASADO, ()),
    (18, "Renovação", "Serviços", "Unidade de Administração", Estado.ATIVO, "autuado", None, None, _PRAZO_ATRASADO, ()),
    (19, "Nova Contratação", "Solução de TIC", "Unidade de Recursos Humanos", Estado.ATIVO, "a_autuar", None, None, _PRAZO_ATRASADO, ()),
    (20, "Renovação", "Serviços", "Unidade de Infraestrutura", Estado.ATIVO, "autuado", None, None, _PRAZO_ATRASADO, (2,)),
    (21, "Nova Contratação", "Material", "Unidade de Compras", Estado.ATIVO, "autuado", None, None, _PRAZO_ATRASADO, ()),
    (22, "Renovação", "Serviços", "Unidade de Tecnologia da Informação", Estado.ATIVO, "a_autuar", None, None, _PRAZO_ATRASADO, ()),
    (23, "Nova Contratação", "Serviços", "Unidade de Administração", Estado.CANCELADO, "nao_se_aplica", None, None, _PRAZO_ATRASADO, ()),
    # --- Bloco NO PRAZO (7 itens): sem evento gravado, sem prazo (fallback
    # "sem prazo => no prazo") — exceto o item 24, que é o antigo item 1
    # (Tipo=Vigente => sempre CONCLUÍDO): trocado de posição para que o
    # "cobaia" convencional dos testes nasça neutro. ---
    (24, "Vigente", "Serviços", "Unidade de Compras", Estado.ATIVO, "autuado", None, None, None, ()),
    (25, "Renovação", "Solução de TIC", "Unidade de Infraestrutura", Estado.ATIVO, "autuado", None, None, None, ()),
    (26, "Nova Contratação", "Serviços", "Unidade de Compras", Estado.ATIVO, "a_autuar", None, None, None, ()),
    (27, "Renovação", "Material", "Unidade de Tecnologia da Informação", Estado.ATIVO, "autuado", None, None, None, ()),
    (28, "Nova Contratação", "Serviços", "Unidade de Administração", Estado.ATIVO, "autuado", None, None, None, ()),
    (29, "Renovação", "Solução de TIC", "Unidade de Recursos Humanos", Estado.ATIVO, "a_autuar", None, None, None, ()),
    (30, "Nova Contratação", "Serviços", "Unidade de Infraestrutura", Estado.CANCELADO, "nao_se_aplica", None, None, None, ()),
]

# Item 13 é a anomalia "envio depois do recebimento" (ver comentário acima).
_DATA_ENVIO_ANOMALO = {13: date(2026, 6, 1)}

# Itens sem grau de prioridade NEM classificação — cobrem o aviso do
# relatório de conferência `registrar_sem_prioridade_e_classificacao`.
_ITENS_SEM_PRIORIDADE_E_CLASSIFICACAO = {13, 27}

# pool de datas de reunião compartilhado entre todos os itens; datas fixas
# mantêm o reimport determinístico. Itens de índice par (1-15) ganham 2
# acompanhamentos; ímpares (16-30) ganham 3
_DATAS_REUNIAO = [
    date(2026, 2, 16),
    date(2026, 3, 16),
    date(2026, 4, 20),
    date(2026, 5, 18),
    date(2026, 6, 15),
]


class Command(BaseCommand):
    help = (
        "Gera apps/pca/fixtures/modelo-controle-exemplo.xlsx a partir de 30 "
        "Processo/Acompanhamento inteiramente fictícios (PUB30-05) — nunca "
        "lê nem reaproveita nenhum dado do PCA real. Reexecutável: apaga e "
        "recria os dados do exercício-alvo antes de gerar o arquivo."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        exercicio = self._preparar_exercicio()
        mapas = self._preparar_catalogos()
        self._limpar_dados_anteriores(exercicio)

        processos_por_item = {}
        for tupla in ITENS:
            processo = self._criar_processo(exercicio, mapas, tupla)
            processos_por_item[processo.item_pca] = processo

        total_acompanhamentos = 0
        for item_pca, processo in processos_por_item.items():
            total_acompanhamentos += self._criar_acompanhamentos(
                exercicio, processo, mapas
            )

        self.stdout.write(
            f"Fixture: {len(processos_por_item)} processos, "
            f"{total_acompanhamentos} acompanhamentos, "
            f"{Unidade.objects.count()} unidades."
        )

        buffer: BytesIO = gerar_modelo_preenchido(exercicio)
        with open(CAMINHO_FIXTURE, "wb") as arquivo:
            arquivo.write(buffer.getvalue())

        self.stdout.write(self.style.SUCCESS(f"Gravado {CAMINHO_FIXTURE}"))

    # -- Preparação ---------------------------------------------------------

    def _preparar_exercicio(self):
        exercicio, _ = Exercicio.objects.get_or_create(
            ano=ANO_EXERCICIO_FIXTURE,
            defaults={"rotulo": f"PCA {ANO_EXERCICIO_FIXTURE}", "situacao": SituacaoExercicio.ABERTO},
        )
        return exercicio

    def _preparar_catalogos(self):
        def upsert_todos(modelo, nomes):
            return {nome: modelo.objects.get_or_create(nome=nome)[0] for nome in nomes}

        return {
            "unidade": upsert_todos(Unidade, UNIDADES),
            "tipo": upsert_todos(Tipo, TIPOS),
            "categoria": upsert_todos(Categoria, CATEGORIAS),
            "grau_prioridade": upsert_todos(GrauPrioridade, GRAUS_PRIORIDADE),
            "classificacao": upsert_todos(Classificacao, CLASSIFICACOES),
            "modalidade": upsert_todos(Modalidade, MODALIDADES),
            "instrumento": upsert_todos(InstrumentoContratual, INSTRUMENTOS),
            "situacao_normalizada": upsert_todos(SituacaoNormalizada, SITUACOES_NORMALIZADAS),
        }

    def _limpar_dados_anteriores(self, exercicio):
        """Apaga só os Processo deste exercício; Acompanhamento/ProcessoSEI
        seguem em cascata. Catálogos nunca são apagados."""
        Processo.objects.filter(exercicio=exercicio, item_pca__in=[t[0] for t in ITENS]).delete()

    # -- Processo -------------------------------------------------------

    def _criar_processo(self, exercicio, mapas, tupla):
        (
            item_pca, tipo_nome, categoria_nome, unidade_nome, estado,
            situacao_sei, data_recebimento_gelic, data_assinatura_contrato,
            prazo_entrega, sei_extra,
        ) = tupla

        tipo = mapas["tipo"][tipo_nome]
        indice = item_pca - 1
        sem_prioridade_e_classificacao = item_pca in _ITENS_SEM_PRIORIDADE_E_CLASSIFICACAO
        grau_prioridade = (
            None if sem_prioridade_e_classificacao
            else mapas["grau_prioridade"][GRAUS_PRIORIDADE[indice % len(GRAUS_PRIORIDADE)]]
        )
        classificacao = (
            None if sem_prioridade_e_classificacao
            else mapas["classificacao"][CLASSIFICACOES[indice % len(CLASSIFICACOES)]]
        )

        data_envio_gelic = _DATA_ENVIO_ANOMALO.get(item_pca)
        if data_envio_gelic is None and data_recebimento_gelic is not None:
            # envio normal, 3 semanas antes do recebimento, exceto na anomalia acima
            data_envio_gelic = data_recebimento_gelic - timedelta(days=21)

        situacao = situacao_inicial(
            tipo_nome_normalizado=tipo.nome_normalizado,
            data_assinatura_contrato=data_assinatura_contrato,
            data_recebimento_gelic=data_recebimento_gelic,
            prazo_entrega=prazo_entrega,
            prazo_vigente=None,
            # hoje só decide o bloco ATRASADO/NO PRAZO; o valor fixo abaixo
            # só existe para a função pura ter um argumento determinístico
            # na geração da fixture
            hoje=date(2026, 1, 1),
        )

        # bloco CONCLUÍDO inteiro (8 itens) — nunca por número de item fixo:
        # o mesmo resultado de situacao_inicial decide se o item ganha
        # bloco de contrato
        e_concluido_com_contrato = situacao == "concluido"
        fornecedor_cnpj = fornecedor_razao_social = None
        modalidade = instrumento = None
        vigencia_inicio = vigencia_fim = None
        numero_contratacao = numero_arp = numero_instrumento = None
        valor_contratado = None
        data_lancamento_spw = data_lancamento_wordpress = data_lancamento_dados_abertos = None
        if e_concluido_com_contrato:
            cnpj, razao_social = FORNECEDORES[indice % len(FORNECEDORES)]
            fornecedor_cnpj, fornecedor_razao_social = cnpj, razao_social
            modalidade = mapas["modalidade"][MODALIDADES[indice % len(MODALIDADES)]]
            instrumento = mapas["instrumento"][INSTRUMENTOS[indice % len(INSTRUMENTOS)]]
            vigencia_inicio = date(2026, 1, 1)
            vigencia_fim = date(2026, 12, 31)
            numero_contratacao = f"{item_pca:03d}/2026"
            numero_arp = f"ARP-{item_pca:03d}/2026" if item_pca % 2 == 0 else None
            numero_instrumento = f"INST-{item_pca:03d}/2026"
            valor_contratado = Decimal("15000.00") + Decimal(item_pca) * Decimal("3500.00")
            data_lancamento_spw = date(2026, 8, 1)
            data_lancamento_wordpress = date(2026, 8, 5)
            data_lancamento_dados_abertos = date(2026, 8, 10)

        processo = Processo.objects.create(
            item_pca=item_pca,
            exercicio=exercicio,
            descricao_objeto=OBJETOS[indice % len(OBJETOS)],
            justificativa=JUSTIFICATIVAS[indice % len(JUSTIFICATIVAS)],
            tipo=tipo,
            categoria=mapas["categoria"][categoria_nome],
            unidade_organizacional=mapas["unidade"][unidade_nome],
            valor_estimado=Decimal("15000.00") + Decimal(item_pca) * Decimal("3500.00"),
            # item 9 fica sem mês previsto de propósito, para o export
            # provar célula vazia de verdade, nunca o rótulo "Sem mês previsto"
            mes_previsto=None if item_pca == 9 else (indice % 12) + 1,
            # data_inclusao_pca só nos 6 últimos itens (25-30), para provar
            # que a ausência vira "—" explícito no detalhe, nunca célula em
            # branco silenciosa
            data_inclusao_pca=date(2026, 3, 9) if item_pca >= 25 else None,
            grau_prioridade=grau_prioridade,
            classificacao=classificacao,
            data_envio_gelic=data_envio_gelic,
            prazo_entrega=prazo_entrega,
            data_recebimento_gelic=data_recebimento_gelic,
            data_prevista_conclusao=None,
            estado=estado,
            situacao=situacao,
            modalidade=modalidade,
            vigencia_inicio=vigencia_inicio,
            vigencia_fim=vigencia_fim,
            numero_contratacao=numero_contratacao,
            numero_arp=numero_arp,
            instrumento_contratual=instrumento,
            numero_instrumento_contratual=numero_instrumento,
            valor_contratado=valor_contratado,
            fornecedor_cnpj=fornecedor_cnpj,
            fornecedor_razao_social=fornecedor_razao_social,
            data_assinatura_contrato=data_assinatura_contrato,
            data_lancamento_spw=data_lancamento_spw,
            data_lancamento_wordpress=data_lancamento_wordpress,
            data_lancamento_dados_abertos=data_lancamento_dados_abertos,
            situacao_sei=situacao_sei,
        )

        numeros_sei = [f"{CNPJ_FICTICIO_SEI}.{item_pca:06d}/2026-10"]
        for sufixo in sei_extra:
            numeros_sei.append(f"{CNPJ_FICTICIO_SEI}.{item_pca:06d}{sufixo}/2026-2{sufixo}")
        ProcessoSEI.objects.bulk_create(
            ProcessoSEI(processo=processo, numero_sei=numero) for numero in numeros_sei
        )
        return processo

    # -- Acompanhamento ---------------------------------------------------

    def _criar_acompanhamentos(self, exercicio, processo, mapas):
        item_pca = processo.item_pca
        if item_pca <= 15:
            datas = _DATAS_REUNIAO[0:2]
        else:
            datas = _DATAS_REUNIAO[2:5]

        criados = 0
        for ordem, referencia_data in enumerate(datas, start=1):
            situacao_nome = SITUACOES_NORMALIZADAS[(item_pca + ordem) % len(SITUACOES_NORMALIZADAS)]
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=referencia_data,
                origem_hash=(
                    f"fixture-exemplo-{exercicio.ano}-{item_pca}-{referencia_data.isoformat()}"
                ),
                evento=f"Acompanhamento nº {ordem} do item {item_pca} em reunião de rotina.",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
                situacao_informada=f"Situação informada em reunião: {situacao_nome.lower()}.",
                situacao=mapas["situacao_normalizada"][situacao_nome],
                prazo_prometido=None,
                data_evento_informada=None,
                area_informada="",
            )
            criados += 1
        return criados
