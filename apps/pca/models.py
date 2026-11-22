import datetime as _datetime
import decimal
import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.functional import Promise
from simple_history.models import HistoricalRecords

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
    Exercicio,
)

from .importacao.models import EventoImportacao  # noqa: F401 — gancho de
# descoberta do Django (07-02): sem este import, EventoImportacao não é
# reconhecido como modelo da app apps.pca e fica de fora de makemigrations.
from .managers import ManagerAuditado
from .querysets import ProcessoQuerySet
from .validators import validar_digitos_cnpj, validar_formato_cnpj


class Estado(models.TextChoices):
    """Fase 17 — primeiro dos 3 eixos do modelo de domínio.
    Substitui, junto com `Situacao` abaixo, o extinto enum `Status` de 6
    valores — removido do domínio vivo pelo plano ("qualquer
    outra coisa não existirá mais"). `HistoricalProcesso.status` permanece
    fisicamente intacto no banco via `SeparateDatabaseAndState` na migração
    0024 (trilha de auditoria imutável, mesmo precedente da Fase 5,
    ver STATE.md "Phase 05-01")."""

    ATIVO = "ativo", "Ativo"
    CANCELADO = "cancelado", "Cancelado"


class Situacao(models.TextChoices):
    """Fase 17 — terceiro eixo (o segundo é `tipo`, FK existente,
    intocada). Substitui o enum `Status` de 6 valores, removido do domínio
    vivo pelo plano (ver `Estado` acima)."""

    NO_PRAZO = "no_prazo", "No prazo"
    ATRASADO = "atrasado", "Atrasado"
    EM_TRAMITACAO = "em_tramitacao", "Em tramitação"
    CONCLUIDO = "concluido", "Concluído"


class RegimeExecucao(models.TextChoices):
    """Fase 36 — regime de execução do item, base da distribuição
    temporal do fluxo de caixa (`apps.pca.projecao.fluxo`):
    `continuado` distribui o valor mês a mês pela vigência; `unico` lança
    100% na entrega. `null` (sem valor) é presumido pela heurística de
    `regras_situacao.regime_presumido_migracao`/`regime_presumido_projecao`
    — nunca gravado como string vazia."""

    CONTINUADO = "continuado", "Continuado"
    UNICO = "unico", "Execução única"


class TipoEventoFinanceiro(models.TextChoices):
    """Fase 36 /spec §2.2 — tipo do instrumento que originou o
    evento financeiro."""

    CONTRATO = "contrato", "Contrato"
    ADITIVO = "aditivo", "Aditivo"
    APOSTILAMENTO = "apostilamento", "Apostilamento"
    MANUAL = "manual", "Manual"


class NaturezaEventoFinanceiro(models.TextChoices):
    """Fase 36 /spec §2.2 — só preenchida quando `tipo ==
    "apostilamento"` (mesmo contrato de `Proposta.serie_valores`, Fase 35)."""

    INICIAL = "inicial", "Inicial"
    REAJUSTE = "reajuste", "Reajuste"
    REPACTUACAO = "repactuacao", "Repactuação"
    ACRESCIMO = "acrescimo", "Acréscimo"
    SUPRESSAO = "supressao", "Supressão"
    PRORROGACAO = "prorrogacao", "Prorrogação"


class PeriodicidadeEventoFinanceiro(models.TextChoices):
    """Fase 36 /spec §2.2."""

    MENSAL = "mensal", "Mensal"
    ANUAL = "anual", "Anual"
    GLOBAL = "global", "Global"


class OrigemEventoFinanceiro(models.TextChoices):
    """Fase 36 — `robo` vem de `eventos_financeiros.sincronizar`
    (nunca alterado/apagado depois de criado); `manual` é lançado por quem
    tem `pca.editar_pca`/pelo Admin e nunca é sobrescrito pelo robô."""

    ROBO = "robo", "Robô SEI"
    MANUAL = "manual", "Manual"


class TipoEvento(models.TextChoices):
    REUNIAO_ACOMPANHAMENTO = "reuniao_acompanhamento", "Reunião de acompanhamento"
    GESTAO_RISCOS = "gestao_riscos", "Gestão de Riscos"
    # Fase 15 — evento gravado por `aplicar_regras_automaticas`, nunca
    # por uma tela: distingue na timeline o que o sistema derivou dos dados
    # do que a equipe declarou em reunião.
    AUTOMATICO = "automatico", "Automático"


class SituacaoReuniao(models.TextChoices):
    ABERTA = "aberta", "Aberta"
    FECHADA = "fechada", "Fechada"


class Reuniao(models.Model):
    """A reunião mensal é entidade no banco, não estado de sessão.

    Paga três coisas: vira consulta por reunião em vez de comparação de
    datas soltas, `n_reunioes` volta a poder contar reuniões, e a ata de
    cada reunião passa a existir como objeto. O mínimo do MVP é data, quem
    conduziu e aberta/fechada — pauta, participantes e exportação de ata são
    capacidade nova, adiadas (Deferred da Fase 3).

    A reunião ABERTA é a "reunião corrente" que carimba `referencia_data` nos
    acompanhamentos nascidos na tela; sem nenhuma aberta, o serviço usa
    `localdate()` e grava normalmente — o modo reunião nunca é pedágio.
    """

    data = models.DateField("data da reunião")
    exercicio = models.ForeignKey(
        Exercicio,
        on_delete=models.PROTECT,
        related_name="reunioes",
        verbose_name="exercício",
    )
    condutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reunioes_conduzidas",
        verbose_name="condutor",
    )
    situacao = models.CharField(
        "situação",
        max_length=10,
        choices=SituacaoReuniao.choices,
        default=SituacaoReuniao.ABERTA,
    )

    class Meta:
        ordering = ["-data"]
        verbose_name = "reunião"
        verbose_name_plural = "reuniões"
        constraints = [
            models.UniqueConstraint(
                fields=["data"],
                name="pca_reuniao_data_unica",
            ),
            models.UniqueConstraint(
                fields=["situacao"],
                condition=models.Q(situacao=SituacaoReuniao.ABERTA),
                name="pca_reuniao_aberta_unica",
            ),
        ]

    def clean(self):
        super().clean()
        if self.exercicio_id is None or self.data is None:
            # FK NOT NULL e campo obrigatório falham sozinhos em clean_fields();
            # nada a validar aqui sem os dois valores.
            return
        ano = self.exercicio.ano
        if self.data.year not in (ano, ano + 1):
            raise ValidationError(
                {
                    "data": (
                        f"A data da reunião ({self.data:%d/%m/%Y}) não pertence "
                        f"ao exercício {ano}."
                    )
                }
            )

    def __str__(self):
        return f"Reunião de {self.data:%d/%m/%Y}"


class OrigemRelatorio(models.TextChoices):
    """De onde veio a versão congelada do relatório da reunião."""

    FECHAMENTO = "fechamento", "Fechamento da reunião"
    RECONSTRUCAO = "reconstrucao", "Reconstituído do histórico"


class RelatorioImutavel(Exception):
    """Uma versão congelada do relatório não pode ser alterada nem apagada."""


def _serializar_dado(valor):
    """`default=` do JSON canônico: só o que é inequívoco (Decimal e datas viram texto; texto preguiçoso vira str)."""
    if isinstance(valor, decimal.Decimal):
        return str(valor)
    if isinstance(valor, (_datetime.date, _datetime.datetime)):
        return valor.isoformat()
    if isinstance(valor, Promise):
        return str(valor)
    raise TypeError(f"Valor não serializável nos fatos do relatório: {type(valor).__name__}")


def json_canonico(dados):
    """Forma canônica dos fatos (chaves ordenadas, sem espaços, UTF-8 sem escape): é ela que leva o sha256."""
    return json.dumps(dados, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_serializar_dado)


def hash_dos_dados(dados):
    return hashlib.sha256(json_canonico(dados).encode("utf-8")).hexdigest()


class RelatorioCongeladoQuerySet(models.QuerySet):
    """`update()` e `delete()` em lote recusam: a imutabilidade vale também para o queryset."""

    def update(self, **kwargs):
        raise RelatorioImutavel("Relatório congelado não pode ser alterado.")

    def delete(self):
        raise RelatorioImutavel("Relatório congelado não pode ser apagado.")


class RelatorioCongelado(models.Model):
    """O "Relatório da reunião" guardado como um commit.

    Congela os FATOS (`apurar_relatorio`: linhas, somas, contagens, datas, textos de linha), não a página:
    a tela renderiza esses fatos com o template e a apresentação ATUAIS (`apresentar_relatorio`). Cada
    fechamento da reunião (ou reconstituição do histórico) grava uma versão n+1, com o sha256 do JSON
    canônico dos fatos. A linha nunca muda: `save()` de linha existente, `delete()`, `queryset.update()` e
    `queryset.delete()` levantam `RelatorioImutavel`, e o Admin é só leitura. Sem `HistoricalRecords`: a
    própria linha é o registro. `criado_por` é PROTECT (SET_NULL alteraria a linha congelada).
    """

    reuniao = models.ForeignKey(
        Reuniao,
        on_delete=models.PROTECT,
        related_name="relatorios_congelados",
        verbose_name="reunião",
    )
    versao = models.PositiveIntegerField("versão")
    de = models.DateField("período de")
    ate = models.DateField("período até")
    corte = models.DateTimeField("corte dos dados")
    dados = models.JSONField("fatos do relatório")
    hash = models.CharField("hash sha256", max_length=64)
    origem = models.CharField("origem", max_length=20, choices=OrigemRelatorio.choices)
    observacao = models.TextField("observação", blank=True)
    criado_em = models.DateTimeField("congelado em", auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="relatorios_congelados",
        verbose_name="congelado por",
    )

    objects = RelatorioCongeladoQuerySet.as_manager()

    class Meta:
        ordering = ["reuniao", "-versao"]
        verbose_name = "relatório congelado"
        verbose_name_plural = "relatórios congelados"
        constraints = [
            models.UniqueConstraint(
                fields=["reuniao", "versao"],
                name="pca_relatorio_congelado_versao_unica",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RelatorioImutavel("Relatório congelado não pode ser alterado.")
        # Ida e volta pelo JSON: o que fica em `dados` é exatamente o que o banco devolverá, e o hash cobre isso.
        self.dados = json.loads(json_canonico(self.dados))
        self.hash = hash_dos_dados(self.dados)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RelatorioImutavel("Relatório congelado não pode ser apagado.")

    @property
    def hash_curto(self):
        return self.hash[:7]

    @property
    def integro(self):
        """True quando o hash recalculado sobre os fatos guardados confere com o gravado."""
        return hash_dos_dados(self.dados) == self.hash

    def __str__(self):
        return f"{self.reuniao} — versão {self.versao}"


class ProcessoAlocador(models.Model):
    """Linha singleton que serializa a alocação da chave natural do PCA."""

    chave = models.PositiveSmallIntegerField(
        "chave do alocador", unique=True, default=1, editable=False
    )

    class Meta:
        verbose_name = "alocador de processo"
        verbose_name_plural = "alocadores de processo"

    def __str__(self):
        return "Alocador de item PCA"


class Processo(models.Model):
    """Um item do PCA (uma linha de `Planilha1`). Chave natural `item_pca`
    (1–149), FKs para o vocabulário de `apps.catalogo` (pca importa de
    catalogo, nunca o inverso).

    As 7 colunas de `Planilha1` marcadas com `*` (Data da Última Reunião,
    Situação na Última Reunião, Prazo Prometido Vigente, Nº de Reuniões, Nº de
    Compromissos Assumidos, Situação do Prazo, Dias em Atraso) NÃO viram
    campos: são derivadas do histórico de Acompanhamento e recalculadas via
    Subquery no queryset base de 01-05 (12) — nunca lidas de célula
    gravada.
    """

    # --- Identidade e planejamento (colunas 1–16, 24) ---
    item_pca = models.PositiveIntegerField(
        "item PCA", db_index=True
    )
    exercicio = models.ForeignKey(
        Exercicio,
        on_delete=models.PROTECT,
        related_name="processos",
        verbose_name="exercício",
    )
    origem = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derivados",
        verbose_name="processo de origem",
    )
    descricao_objeto = models.TextField("Descrição do objeto")
    justificativa = models.TextField("Justificativa", blank=True, default="")
    tipo = models.ForeignKey(
        Tipo, on_delete=models.PROTECT, related_name="processos",
        verbose_name="Tipo de contratação",
    )
    categoria = models.ForeignKey(
        Categoria, on_delete=models.PROTECT, related_name="processos",
        verbose_name="Categoria",
    )
    unidade_organizacional = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name="processos",
        verbose_name="Unidade organizacional (UO)",
    )
    valor_estimado = models.DecimalField(
        "Valor estimado (R$)", max_digits=14, decimal_places=2,
        null=True, blank=True,
    )
    mes_previsto = models.IntegerField(
        "Mês previsto (PCA)", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    data_inclusao_pca = models.DateField(
        "Data de inclusão no PCA", null=True, blank=True
    )
    grau_prioridade = models.ForeignKey(
        GrauPrioridade, on_delete=models.PROTECT, related_name="processos",
        null=True, blank=True, verbose_name="Grau de prioridade",
    )
    classificacao = models.ForeignKey(
        Classificacao, on_delete=models.PROTECT, related_name="processos",
        null=True, blank=True, verbose_name="Classificação",
    )
    data_envio_gelic = models.DateField(
        "Data envio ao Gelic", null=True, blank=True
    )
    # Fase 11 — prazo previsto de Planejamento, próprio e
    # opcional. Nome único em campo/coluna de planilha/rótulo de tela: "Data
    # prevista para entrega". Distinto de `data_recebimento_gelic` logo
    # abaixo, que é o fato consumado (quando a entrega realmente aconteceu)
    # — os dois nunca se confundem de novo depois.
    prazo_entrega = models.DateField(
        "Data prevista para entrega", null=True, blank=True
    )
    # Fase 15 — renomeado de `data_entrega_delic`; campo fundido
    # com o extinto `data_recebimento_processo` (zero preenchimentos). Os dados existentes sobrevivem sob o novo nome via
    # RenameField na migração 0019.
    data_recebimento_gelic = models.DateField(
        "Data de Recebimento do Processo no Gelic", null=True, blank=True
    )
    data_prevista_conclusao = models.DateField(
        "Data prevista/conclusão da contratação", null=True, blank=True
    )
    # Fase 17 — campos do modelo de 3 eixos (`estado`/`situacao`
    # abaixo; o terceiro é `tipo`, FK acima, intocada). `models.py` declara o
    # estado FINAL (NOT NULL, mesmo padrão do campo `exercicio` na Fase
    # 5/ nullable só na migração intermediária, nunca no model fonte);
    # a migração 0023 nasceu com AddField nullable, rodou o backfill via
    # `situacao_inicial` sobre os 154 processos reais, e só então fechou
    # para NOT NULL com AlterField — "nullable → backfill → finalização". O
    # extinto campo `status`/enum `Status` (6 valores, Fase 15) foi
    # removido do domínio vivo por esta migração — `RemoveField` real em
    # `processo`, `SeparateDatabaseAndState` em `historicalprocesso` (coluna física preservada, só sai do mapeamento ORM). O `default=`
    # abaixo NÃO é decisão de negócio — é escolha técnica para que fixtures
    # de teste que criam `Processo(...)` sem passar `estado=`/`situacao=`
    # continuem construindo objetos válidos mesmo sem `null=True` (o default
    # do Django preenche o campo omitido no `__init__`).
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices,
        default=Estado.ATIVO,
    )
    situacao = models.CharField(
        "situação", max_length=20, choices=Situacao.choices,
        default=Situacao.NO_PRAZO,
    )
    # 29/09/2026 (decisão do usuário) — trava explícita da situação. Liga sozinho quando alguém muda a
    # situação manualmente; enquanto ligado, nenhuma regra automática (rotina, sincronização com o SEI,
    # correção de leitura para Atrasado) mexe na situação — só se desmarca no Admin, e aí a situação é
    # recalculada na hora. `situacao_regra` guarda o que as regras aplicariam quando divergem da
    # escolha manual (vazio = concordam), para o aviso do Início.
    situacao_manual = models.BooleanField(
        "situação manual", default=False,
        help_text=(
            "Ligado: vale a situação escolhida manualmente e as regras automáticas não a alteram. "
            "Desmarque para voltar ao automático — a situação é recalculada ao salvar."
        ),
    )
    situacao_regra = models.CharField(
        "situação pelas regras automáticas", max_length=20, choices=Situacao.choices,
        blank=True, default="",
        help_text="Com a situação manual ligada: o que as regras aplicariam, quando diferente da escolha manual.",
    )
    # Fase 11 — `justificativa_alteracao_email`
    # (booleano) e `justificativa_alteracao_prazo` (texto solto, quick) saíram do schema pela migração 0015. Todo texto não vazio
    # foi transferido para `Acompanhamento.evento` da promessa mais recente
    # antes da remoção física, com snapshot `HistoricalAcompanhamento`
    # auditado — a justificativa de mudança de prazo agora pertence a cada
    # promessa, nunca ao Processo.

    # --- Bloco de execução contratual (colunas 25–39) — já nasce no
    # schema, inteiramente nullable, não lido por nenhuma tela até a Fase 4.
    # `data_recebimento_processo` (zero preenchimentos) saiu na Fase 15,
    # fundido em `data_recebimento_gelic` acima.
    modalidade = models.ForeignKey(
        Modalidade, on_delete=models.PROTECT, related_name="processos",
        null=True, blank=True, verbose_name="Modalidade",
    )
    vigencia_inicio = models.DateField("Vigência início", null=True, blank=True)
    vigencia_fim = models.DateField("Vigência fim", null=True, blank=True)
    numero_contratacao = models.CharField(
        "Nº da contratação", max_length=50, null=True, blank=True
    )
    numero_arp = models.CharField(
        "Nº da ARP", max_length=50, null=True, blank=True
    )
    instrumento_contratual = models.ForeignKey(
        InstrumentoContratual, on_delete=models.PROTECT,
        related_name="processos", null=True, blank=True,
        verbose_name="Instrumento contratual",
    )
    numero_instrumento_contratual = models.CharField(
        "Nº do instrumento contratual", max_length=50, null=True, blank=True
    )
    valor_contratado = models.DecimalField(
        "Valor contratado (R$)", max_digits=14, decimal_places=2,
        null=True, blank=True,
    )
    fornecedor_cnpj = models.CharField(
        "CNPJ", max_length=18, null=True, blank=True,
        validators=[validar_formato_cnpj, validar_digitos_cnpj],
    )
    fornecedor_razao_social = models.CharField(
        "Razão social", max_length=255, null=True, blank=True
    )
    data_assinatura_contrato = models.DateField(
        "Data assinatura do contrato", null=True, blank=True
    )
    data_lancamento_spw = models.DateField(
        "Data lançamento SPW", null=True, blank=True
    )
    data_lancamento_wordpress = models.DateField(
        "Data lançamento WordPress", null=True, blank=True
    )
    data_lancamento_dados_abertos = models.DateField(
        "Data lançamento Dados Abertos", null=True, blank=True
    )

    # --- Fase 36 (spec §2.1) — base de dados do fluxo de caixa
    # projetado (`apps.pca.projecao.fluxo`). Os 3 campos são
    # nullable/default, o import da planilha os ignora, e a migração 0027
    # preenche `regime_execucao` pela heurística de vigência só
    # quando o campo ainda está `null` — nunca sobrescreve um valor já
    # gravado à mão/pelo robô. Coerência entre `valor_mensal` × meses e
    # `valor_contratado` (divergência > 5%) é SINALIZADA na ficha do
    # processo (`_aviso_coerencia_valor_mensal`, `views_processo.py`, Task
    # 2 deste plano), nunca validada/bloqueada aqui no model.
    regime_execucao = models.CharField(
        "Regime de execução", max_length=10,
        choices=RegimeExecucao.choices, null=True, blank=True,
    )
    renovacao_prevista = models.BooleanField("Renovação prevista", default=True)
    valor_mensal = models.DecimalField(
        "Valor mensal (R$)", max_digits=14, decimal_places=2,
        null=True, blank=True,
    )

    # "Situação do SEI" (Autuado/A autuar/Não se aplica)
    # saiu: era redundante com o nº SEI. "Sem processo SEI" é derivado da
    # ausência de `numeros_sei` (filtro `sem_processo_sei`, card do Início,
    # Assistente); item sem número nunca é tocado pela sincronização.

    # --- Unidade atual no SEI --- gravado SÓ pelo robô
    # (`apps.pca.sei.regras.unidade_atual`, `propor()` passo 7b), derivado
    # do histórico de andamento já coletado — nunca uma nova consulta ao
    # SEI. Somente leitura na ficha e no Admin.
    unidade_sei_atual = models.CharField(
        "Unidade atual (SEI)", max_length=80, blank=True, default="",
    )
    unidade_sei_atual_desde = models.DateTimeField(
        "Na unidade desde", blank=True, null=True,
    )

    # --- Controle otimista de concorrência ---
    # Token de versão comparado pelo serviço de domínio antes de gravar
    # (Pitfall 4): dois editores na mesma reunião, o segundo recebe
    # `ConflitoDeEdicao` em vez de sobrescrever em silêncio. `auto_now=True`
    # só dispara em `save()` — nunca em `bulk_create`/`update()` —, o que
    # preserva a semântica de "versão da última escrita via save()".
    # Atenção: todo `save(update_fields=[...])` precisa incluir
    # "atualizado_em", ou o token não avança.
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    # /12 — ManagerAuditado.from_queryset(ProcessoQuerySet)
    # preserva o bloqueio de .update() e adiciona
    # .para_listagem() como método encadeável, sem duplicar o Manager.
    objects = ManagerAuditado.from_queryset(ProcessoQuerySet)()
    history = HistoricalRecords()

    class Meta:
        ordering = ["exercicio", "item_pca"]
        verbose_name = "processo"
        verbose_name_plural = "processos"
        permissions = [
            (
                "editar_pca",
                "Pode editar processos e registrar acompanhamento",
            ),
            (
                "gerir_exercicio",
                "Pode criar, abrir e fechar exercícios do PCA",
            ),
            (
                "ver_analises",
                "Pode ver as análises estratégicas (fluxo de caixa, "
                "estatísticas e prazos)",
            ),
            (
                "instruir_contratacao",
                "Pode vincular nº SEI e editar a ficha da contratação "
                "(grupo demandante)",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["exercicio", "item_pca"],
                name="pca_processo_exercicio_item_unico",
            ),
        ]

    def __str__(self):
        return f"{self.item_pca} — {self.descricao_objeto[:60]}"


class Acompanhamento(models.Model):
    """Um registro de reunião/evento sobre um Processo (uma linha da aba
    `Acompanhamento`). `origem_hash` é a chave natural do re-import e
    nasce aqui, não no comando de import."""

    processo = models.ForeignKey(
        Processo, on_delete=models.CASCADE, related_name="acompanhamentos"
    )
    referencia_data = models.DateField("data da reunião")
    origem_hash = models.CharField(
        "origem (hash)", max_length=64, unique=True, db_index=True
    )
    evento = models.TextField("evento", blank=True, default="")
    tipo_evento = models.CharField(
        "tipo de evento", max_length=30, choices=TipoEvento.choices
    )
    situacao_informada = models.TextField(
        "situação informada (original)", blank=True, default=""
    )
    situacao = models.ForeignKey(
        SituacaoNormalizada, on_delete=models.PROTECT,
        related_name="acompanhamentos", verbose_name="situação normalizada",
    )
    prazo_prometido = models.DateField(
        "prazo prometido", null=True, blank=True
    )
    data_evento_informada = models.DateField(
        "data do evento informada", null=True, blank=True
    )
    area_informada = models.CharField(
        "área informada", max_length=255, blank=True, default=""
    )
    # Nullable de propósito: a correção avulsa numa terça-feira
    # qualquer (sem reunião corrente declarada) grava normalmente, com
    # `referencia_data = localdate()` e sem reunião associada. Acompanhamento
    # sem reunião contribui zero para `n_reunioes`, que é a leitura
    # correta: "este item nunca foi discutido em reunião".
    reuniao = models.ForeignKey(
        Reuniao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acompanhamentos",
        verbose_name="reunião",
    )
    # Fase 17 — gap-closure do GAP 1: só
    # `True` quando `registrar_acompanhamento` grava com `situacao_novo`
    # explícito numa chamada NÃO-automática (o caso real de
    # `confirmar_transicao_view`, o modal de transição) — nunca pelo import
    # (`importacao/executor.py` instancia `Acompanhamento` direto, campo
    # nasce `False` pelo default) nem por promessa de prazo isolada
    # (`registrar_promessa_view` só passa `prazo_prometido`,
    # `situacao_novo=None`). Materializa por escrita a distinção entre
    # "transição manual de situação" e "fato gatilho reafirmado" que a
    # guarda ampla do plano inferia (errado) do `tipo_evento` genérico.
    transicao_manual = models.BooleanField(
        "transição manual de situação", default=False
    )

    objects = ManagerAuditado()
    history = HistoricalRecords()

    class Meta:
        ordering = ["processo", "-referencia_data", "-id"]
        verbose_name = "acompanhamento"
        verbose_name_plural = "acompanhamentos"
        indexes = [
            # Suporte ao desempate determinístico do "último acompanhamento"
            # consumido pelo queryset base de 01-05.
            models.Index(
                fields=["processo", "-referencia_data", "-id"],
                name="acomp_ultimo_idx",
            ),
        ]

    def __str__(self):
        return f"{self.processo_id} @ {self.referencia_data}"


class ProcessoSEI(models.Model):
    """Nº SEI é relação 1:N — a célula da planilha carrega 0, 1 ou
    vários números (item 37 tem três, item 72 tem dois). Nunca um campo de
    texto em Processo. Sem histórico próprio: é detalhe de Processo."""

    processo = models.ForeignKey(
        Processo, on_delete=models.CASCADE, related_name="numeros_sei"
    )
    numero_sei = models.CharField("nº do processo SEI", max_length=50)

    class Meta:
        verbose_name = "nº SEI"
        verbose_name_plural = "nºs SEI"
        unique_together = ("processo", "numero_sei")

    def __str__(self):
        return self.numero_sei


class FichaContratacao(models.Model):
    """(V-5 do documento interno de desenho): JSON livre da extensão, versionado
    por ela; o PCA só guarda, limita tamanho e versiona — controle
    otimista (`GET`/`PUT /api/sei/ficha`). O conteúdo de `dados` é opaco ao
    PCA, nunca interpretado/executado/renderizado em template."""

    processo = models.OneToOneField(
        Processo,
        on_delete=models.CASCADE,
        related_name="ficha_contratacao",
        verbose_name="processo",
    )
    versao = models.PositiveIntegerField("versão", default=1)
    dados = models.JSONField("dados", default=dict)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fichas_contratacao_atualizadas",
        verbose_name="atualizado por",
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "ficha da contratação"
        verbose_name_plural = "fichas da contratação"

    def __str__(self):
        return f"Ficha {self.processo.item_pca}/{self.processo.exercicio.ano} (v{self.versao})"


class EventoFinanceiro(models.Model):
    """Fase 36 (spec §2.2) — a "linha de valor" de um
    Processo: cada evento é um instrumento (contrato/aditivo/apostilamento)
    ou lançamento manual que muda o valor global vigente. Ordenada por
    `data`, o último evento define o global vigente; `apps.pca.projecao.
    fluxo` lê a série quando existe e cai para
    `valor_contratado`/`valor_mensal` do `Processo` quando vazia.

    Gravado por `apps/pca/servicos/eventos_financeiros.py::sincronizar`
    (origem `robo`, chave de idempotência `(processo, protocolo_sei)`) ou à
    mão pelo Admin (origem `manual`) — o serviço NUNCA altera nem apaga um
    evento existente, `manual` ou `robo`. Única exceção: o comando
    de correção pontual `sei_corrigir_eventos` (debug
    robo-valor-contratado-item64, 20/10/2026), só com `--aplicar`, só em
    eventos `robo`, instância a instância com motivo no histórico. Sem history próprio
    além de `simple_history` (a trilha de quem editou/apagou pelo Admin já
    é a exceção documentada em convenções do projeto/LGPD)."""

    processo = models.ForeignKey(
        Processo, on_delete=models.CASCADE, related_name="eventos_financeiros",
    )
    # `serie_valores` (Fase 35) pode trazer `data=None` quando
    # `_parse_data_hora` falha em ler a assinatura — nunca bloquear a
    # criação do evento por isso.
    data = models.DateField("data", null=True, blank=True)
    tipo = models.CharField(
        "tipo", max_length=15, choices=TipoEventoFinanceiro.choices,
    )
    # Só apostilamento qualifica (spec §2, contrato de `Proposta.
    # serie_valores`: `natureza` só é preenchida quando `tipo ==
    # "apostilamento"`).
    natureza = models.CharField(
        "natureza", max_length=15, choices=NaturezaEventoFinanceiro.choices,
        null=True, blank=True,
    )
    # Global vigente APÓS o evento (spec §2.2) — não o valor da parcela.
    valor = models.DecimalField("valor (R$)", max_digits=14, decimal_places=2)
    valor_mensal = models.DecimalField(
        "valor mensal (R$)", max_digits=14, decimal_places=2,
        null=True, blank=True,
    )
    periodicidade = models.CharField(
        "periodicidade", max_length=10,
        choices=PeriodicidadeEventoFinanceiro.choices, null=True, blank=True,
    )
    protocolo_sei = models.CharField(
        "protocolo SEI", max_length=20, null=True, blank=True,
    )
    origem = models.CharField(
        "origem", max_length=10, choices=OrigemEventoFinanceiro.choices,
    )
    observacao = models.TextField("observação", blank=True, default="")
    # Fase 37 (spec §2.1/§8) — identificador da cadeia de
    # contrato à qual este evento pertence: nº da contratação extraído pelo
    # robô (Fase 33, "nº da contratação") ou, na ausência dele, o protocolo
    # SEI do documento-base. Eventos com `instrumento` igual formam UM
    # contrato (`apps.pca.projecao.fluxo`); vazio (`""`) é a
    # cadeia "principal" — comportamento de hoje, dados vêm do `Processo`.
    # Eventos gravados antes desta migração ficam vazios, sem regressão.
    instrumento = models.CharField(
        "instrumento", max_length=60, blank=True, default="",
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ["data", "id"]
        verbose_name = "evento financeiro"
        verbose_name_plural = "eventos financeiros"
        constraints = [
            models.UniqueConstraint(
                fields=["processo", "protocolo_sei"],
                condition=Q(protocolo_sei__isnull=False),
                name="pca_eventofinanceiro_processo_protocolo_unico",
            ),
        ]

    def __str__(self):
        return f"{self.processo_id} — {self.tipo} {self.data}"


class CenarioFluxo(models.Model):
    """Fase 37 (spec §3.2/§8) — um cenário de simulação salvo do
    fluxo de caixa: `ajustes` serializa `apps.pca.projecao.simulacao.Ajustes`
    (`simulacao.para_json`/`de_json`); esta migração só cria a
    tabela — nenhuma view/ação ainda usa este modelo."""

    exercicio = models.ForeignKey(
        Exercicio, on_delete=models.CASCADE, related_name="cenarios_fluxo",
        verbose_name="exercício",
    )
    nome = models.CharField("nome", max_length=100)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="cenarios_fluxo", verbose_name="autor",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    ajustes = models.JSONField("ajustes", default=dict)
    descricao = models.TextField("descrição", blank=True, default="")

    history = HistoricalRecords()

    class Meta:
        ordering = ["-atualizado_em"]
        verbose_name = "cenário de fluxo de caixa"
        verbose_name_plural = "cenários de fluxo de caixa"
        constraints = [
            models.UniqueConstraint(
                fields=["exercicio", "nome"],
                name="pca_cenariofluxo_exercicio_nome_unico",
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.exercicio})"


class RascunhoVirada(models.Model):
    """Persistent, resumable composition of the next annual PCA.

    The destination exercise deliberately is not a foreign key: an annual
    destination becomes visible only after ``confirmar_virada`` commits all
    selected processes.
    """

    exercicio_origem = models.ForeignKey(
        Exercicio,
        on_delete=models.PROTECT,
        related_name="rascunhos_virada_origem",
        verbose_name="exercício de origem",
    )
    ano_destino = models.PositiveSmallIntegerField("ano de destino")
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rascunhos_virada_criados",
        verbose_name="criado por",
    )
    confirmado_em = models.DateTimeField("confirmado em", null=True, blank=True)
    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rascunhos_virada_confirmados",
        verbose_name="confirmado por",
    )

    class Meta:
        verbose_name = "rascunho de virada"
        verbose_name_plural = "rascunhos de virada"
        constraints = [
            models.UniqueConstraint(
                fields=["exercicio_origem", "ano_destino"],
                condition=models.Q(confirmado_em__isnull=True),
                name="pca_virada_pendente_origem_destino_unica",
            ),
        ]


class RascunhoItemVirada(models.Model):
    """One reviewed source line in a turnover draft."""

    rascunho = models.ForeignKey(
        RascunhoVirada,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="rascunho",
    )
    processo_origem = models.ForeignKey(
        Processo,
        on_delete=models.CASCADE,
        related_name="itens_rascunho_virada",
        verbose_name="processo de origem",
    )
    ordem = models.PositiveIntegerField("ordem")
    selecionado = models.BooleanField("selecionado", default=False)
    valor_estimado_editado = models.DecimalField(
        "valor estimado revisado", max_digits=14, decimal_places=2,
        null=True, blank=True,
    )
    mes_previsto_editado = models.PositiveSmallIntegerField(
        "mês previsto revisado", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )

    class Meta:
        ordering = ["ordem", "processo_origem_id"]
        verbose_name = "item do rascunho de virada"
        verbose_name_plural = "itens do rascunho de virada"
        constraints = [
            models.UniqueConstraint(
                fields=["rascunho", "processo_origem"],
                name="pca_virada_item_origem_unico",
            ),
            models.UniqueConstraint(
                fields=["rascunho", "ordem"],
                name="pca_virada_item_ordem_unica",
            ),
        ]


class PreferenciaColunas(models.Model):
    """Colunas da tela Processos escolhidas por cada usuário
    — gravadas na CONTA, não só na sessão: acompanham a pessoa depois do
    logout e em qualquer navegador, até ela escolher outras ou restaurar o
    padrão (que apaga a linha, para que uma mudança futura do padrão chegue
    a ela). Sem `history`: preferência de tela não é dado auditado."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferencia_colunas",
        verbose_name="usuário",
    )
    colunas = models.JSONField("colunas", default=list)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "preferência de colunas"
        verbose_name_plural = "preferências de colunas"

    def __str__(self):
        return f"{self.usuario} — {len(self.colunas)} coluna(s)"
