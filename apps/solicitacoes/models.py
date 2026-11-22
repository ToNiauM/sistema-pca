from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.timezone import now
from simple_history.models import HistoricalRecords

from apps.catalogo.models import Exercicio, Unidade
from apps.pca.models import Processo

from .regras import (
    Alcada,
    Campo,
    EstadoParte,
    EstadoSolicitacao,
    TipoSolicitacao,
)


class VinculoUnidade(models.Model):
    """"unidades do usuário": muitos para muitos entre usuário e unidade
    organizacional, mantido no Admin. Quem pede só pede nos itens das suas unidades."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculos_unidade",
        verbose_name="usuário",
    )
    unidade = models.ForeignKey(
        Unidade,
        on_delete=models.CASCADE,
        related_name="vinculos_usuario",
        verbose_name="unidade organizacional",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "vínculo usuário-unidade"
        verbose_name_plural = "vínculos usuário-unidade"
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "unidade"], name="solicitacoes_vinculo_usuario_unidade_unico"
            ),
        ]

    def __str__(self):
        return f"{self.usuario} — {self.unidade}"


class Solicitacao(models.Model):
    """Uma solicitação por item, com uma ou mais partes. Inclusão de item novo
    é uma solicitação sem item (`processo` nulo até a aprovação, quando passa a apontar
    o item criado). Numeração "N/AAAA" por ano civil da criação."""

    numero = models.PositiveIntegerField("número")
    ano = models.PositiveSmallIntegerField("ano")
    exercicio = models.ForeignKey(
        Exercicio, on_delete=models.PROTECT, related_name="solicitacoes",
        verbose_name="exercício",
    )
    processo = models.ForeignKey(
        Processo, on_delete=models.PROTECT, null=True, blank=True,
        related_name="solicitacoes", verbose_name="item do PCA",
    )
    unidade = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name="solicitacoes",
        verbose_name="unidade organizacional",
    )
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="solicitacoes_feitas", verbose_name="solicitante",
    )
    tipo = models.CharField("tipo", max_length=15, choices=TipoSolicitacao.choices)
    estado = models.CharField(
        "estado", max_length=10, choices=EstadoSolicitacao.choices,
        default=EstadoSolicitacao.PENDENTE,
    )
    justificativa = models.TextField("justificativa")
    numero_sei = models.CharField("nº SEI", max_length=50, blank=True, default="")
    # Só na inclusão: o que a unidade informou, para criar o item na aprovação.
    dados_inclusao = models.JSONField("dados da inclusão", null=True, blank=True)
    criada_em = models.DateTimeField("criada em", default=now)
    encerrada_em = models.DateTimeField("encerrada em", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-criada_em", "-id"]
        verbose_name = "solicitação"
        verbose_name_plural = "solicitações"
        permissions = [
            ("solicitar", "Pode solicitar alterações nos itens das suas unidades"),
            ("decidir_equipe", "Pode decidir solicitações de prazo e mês (equipe do PCA)"),
            (
                "decidir_diretoria",
                "Pode decidir solicitações de inclusão, cancelamento, valor e objeto (diretoria)",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["ano", "numero"], name="solicitacoes_numero_por_ano_unico"),
        ]

    @property
    def codigo(self) -> str:
        return f"{self.numero}/{self.ano}"

    def __str__(self):
        return f"Solicitação {self.codigo}"


class ParteSolicitacao(models.Model):
    """Um campo pedido, decidido pela sua alçada, quando a alçada quiser.
    `valor_atual`/`valor_pedido`/`valor_concedido` são texto estável (`regras.para_texto`).
    `processo` repete o item da solicitação para que "uma parte pendente por campo por
    item" seja garantida pelo banco."""

    solicitacao = models.ForeignKey(
        Solicitacao, on_delete=models.CASCADE, related_name="partes",
        verbose_name="solicitação",
    )
    processo = models.ForeignKey(
        Processo, on_delete=models.PROTECT, null=True, blank=True,
        related_name="partes_solicitacao", verbose_name="item do PCA",
    )
    campo = models.CharField("campo", max_length=20, choices=Campo.choices)
    alcada = models.CharField("alçada", max_length=10, choices=Alcada.choices)
    valor_atual = models.TextField("valor atual", blank=True, default="")
    valor_pedido = models.TextField("valor pedido", blank=True, default="")
    estado = models.CharField(
        "estado", max_length=15, choices=EstadoParte.choices, default=EstadoParte.PENDENTE
    )
    valor_concedido = models.TextField("valor concedido", blank=True, default="")
    motivo = models.TextField("motivo", blank=True, default="")
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="partes_decididas", verbose_name="decidido por",
    )
    decidido_em = models.DateTimeField("decidido em", null=True, blank=True)
    fora_do_exercicio = models.BooleanField("fora do exercício", default=False)

    history = HistoricalRecords()

    class Meta:
        ordering = ["solicitacao", "id"]
        verbose_name = "parte da solicitação"
        verbose_name_plural = "partes da solicitação"
        constraints = [
            models.UniqueConstraint(
                fields=["solicitacao", "campo"], name="solicitacoes_parte_campo_unico"
            ),
            models.UniqueConstraint(
                fields=["processo", "campo"],
                condition=Q(estado=EstadoParte.PENDENTE),
                name="solicitacoes_parte_pendente_por_item_campo",
            ),
        ]
        indexes = [
            models.Index(fields=["estado", "alcada"], name="solic_parte_fila_idx"),
        ]

    def __str__(self):
        return f"{self.solicitacao} — {self.get_campo_display()}"
