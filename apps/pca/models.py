from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
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
# descoberta do Django: sem este import, EventoImportacao fica de fora de makemigrations
from .managers import ManagerAuditado
from .querysets import ProcessoQuerySet
from .validators import validar_digitos_cnpj, validar_formato_cnpj


class Estado(models.TextChoices):
    """Primeiro dos 3 eixos do modelo de domínio. HistoricalProcesso.status
    permanece fisicamente intacto no banco (trilha de auditoria imutável)."""

    ATIVO = "ativo", "Ativo"
    CANCELADO = "cancelado", "Cancelado"


class Situacao(models.TextChoices):
    """Terceiro eixo do modelo de domínio (o segundo é tipo, FK intocada)."""

    NO_PRAZO = "no_prazo", "No prazo"
    ATRASADO = "atrasado", "Atrasado"
    EM_TRAMITACAO = "em_tramitacao", "Em tramitação"
    CONCLUIDO = "concluido", "Concluído"


class SituacaoSei(models.TextChoices):
    AUTUADO = "autuado", "Autuado"
    A_AUTUAR = "a_autuar", "A autuar"
    NAO_SE_APLICA = "nao_se_aplica", "Não se aplica"


class TipoEvento(models.TextChoices):
    REUNIAO_ACOMPANHAMENTO = "reuniao_acompanhamento", "Reunião de acompanhamento"
    GESTAO_RISCOS = "gestao_riscos", "Gestão de Riscos"
    # evento gravado por aplicar_regras_automaticas, nunca por uma tela
    AUTOMATICO = "automatico", "Automático"


class SituacaoReuniao(models.TextChoices):
    ABERTA = "aberta", "Aberta"
    FECHADA = "fechada", "Fechada"


class Reuniao(models.Model):
    """A reunião mensal é entidade no banco, não estado de sessão. O
    mínimo é data, quem conduziu e aberta/fechada.

    A reunião ABERTA é a "reunião corrente" que carimba referencia_data nos
    acompanhamentos nascidos na tela; sem nenhuma aberta, o serviço usa
    localdate() e grava normalmente."""

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
            # FK NOT NULL e campo obrigatório falham sozinhos em clean_fields()
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
    """Um item do PCA (uma linha de Planilha1). Chave natural item_pca,
    FKs para o vocabulário de apps.catalogo.

    As 7 colunas marcadas com * (Data da Última Reunião, Situação na Última
    Reunião, Prazo Prometido Vigente, Nº de Reuniões, Nº de Compromissos
    Assumidos, Situação do Prazo, Dias em Atraso) não viram campos: são
    derivadas do histórico de Acompanhamento e recalculadas via Subquery."""

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
    # prazo previsto de Planejamento, próprio e opcional. Distinto de
    # data_recebimento_gelic logo abaixo, que é o fato consumado
    prazo_entrega = models.DateField(
        "Data prevista para entrega", null=True, blank=True
    )
    # renomeado de data_entrega_delic; campo fundido com o extinto
    # data_recebimento_processo (zero preenchimentos)
    data_recebimento_gelic = models.DateField(
        "Data de Recebimento do Processo no Gelic", null=True, blank=True
    )
    data_prevista_conclusao = models.DateField(
        "Data prevista/conclusão da contratação", null=True, blank=True
    )
    # campos do modelo de 3 eixos (estado/situacao abaixo; o terceiro é
    # tipo, FK acima, intocada). O default= abaixo não é decisão de
    # negócio — é escolha técnica para que fixtures de teste que criam
    # Processo(...) sem passar estado=/situacao= continuem válidas
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices,
        default=Estado.ATIVO,
    )
    situacao = models.CharField(
        "situação", max_length=20, choices=Situacao.choices,
        default=Situacao.NO_PRAZO,
    )
    # justificativa_alteracao_email/justificativa_alteracao_prazo saíram
    # do schema; a justificativa de mudança de prazo agora pertence a cada
    # promessa (Acompanhamento.evento), nunca ao Processo

    # --- bloco de execução contratual (colunas 25-39): já nasce no schema,
    # inteiramente nullable
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

    # --- Situação no SEI (coluna 40) ---
    situacao_sei = models.CharField(
        "Situação do SEI", max_length=15,
        choices=SituacaoSei.choices, blank=True, default="",
    )

    # --- controle otimista de concorrência ---
    # token de versão comparado pelo serviço de domínio antes de gravar:
    # dois editores na mesma reunião, o segundo recebe ConflitoDeEdicao.
    # auto_now=True só dispara em save(); todo save(update_fields=[...])
    # precisa incluir "atualizado_em", ou o token não avança
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    # ManagerAuditado.from_queryset(ProcessoQuerySet) preserva o bloqueio
    # de .update() e adiciona .para_listagem() como método encadeável
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
    """Um registro de reunião/evento sobre um Processo. origem_hash é a
    chave natural do re-import, e nasce aqui, não no comando de import."""

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
    # nullable de propósito: uma correção avulsa (sem reunião corrente
    # declarada) grava normalmente, sem reunião associada. Acompanhamento
    # sem reunião contribui zero para n_reunioes
    reuniao = models.ForeignKey(
        Reuniao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acompanhamentos",
        verbose_name="reunião",
    )
    # só True quando registrar_acompanhamento grava com situacao_novo
    # explícito numa chamada não-automática; materializa por escrita a
    # distinção entre "transição manual de situação" e "fato gatilho reafirmado"
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
            # suporte ao desempate determinístico do "último acompanhamento"
            models.Index(
                fields=["processo", "-referencia_data", "-id"],
                name="acomp_ultimo_idx",
            ),
        ]

    def __str__(self):
        return f"{self.processo_id} @ {self.referencia_data}"


class ProcessoSEI(models.Model):
    """Nº SEI é relação 1:N — a célula da planilha carrega 0, 1 ou vários
    números. Nunca um campo de texto em Processo. Sem histórico próprio."""

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


class RascunhoVirada(models.Model):
    """Composição persistente e retomável do próximo PCA anual. O
    exercício de destino deliberadamente não é uma FK: uma virada anual só
    fica visível depois que confirmar_virada grava todos os processos
    selecionados."""

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
    """Uma linha de origem revisada num rascunho de virada."""

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
