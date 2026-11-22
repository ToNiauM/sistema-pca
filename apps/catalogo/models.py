from django.db import models
from django.db.models import F
from django.db.models.functions import Collate

from apps.catalogo.utils import normalizar_nome


class SituacaoExercicio(models.TextChoices):
    ABERTO = "aberto", "Aberto"
    FECHADO = "fechado", "Fechado"


class Exercicio(models.Model):
    """A yearly PCA identity and its read-only lifecycle state."""

    ano = models.PositiveSmallIntegerField("ano", unique=True)
    rotulo = models.CharField("rótulo", max_length=100)
    situacao = models.CharField(
        "situação",
        max_length=10,
        choices=SituacaoExercicio.choices,
        default=SituacaoExercicio.ABERTO,
    )

    class Meta:
        ordering = ["-ano"]
        verbose_name = "exercício"
        verbose_name_plural = "exercícios"

    def __str__(self):
        return self.rotulo


class IndiceReajuste(models.Model):
    """Fase 36 (spec §2.3) — catálogo de índices de reajuste,
    consumido por `apps.pca.projecao.fluxo` (camada "Reajuste
    projetado") e pelo formulário/detalhe de Processos.
    NÃO herda `DominioBase` — não tem `nome`/`nome_normalizado`, é uma
    tabela de fato (índice × ano), não vocabulário (mesmo raciocínio de
    `Exercicio` acima, fora do padrão `DominioBase`)."""

    IPCA = "IPCA"
    INPC = "INPC"
    IGP_M = "IGP-M"
    META_BC = "META_BC"
    CHOICES_INDICE = [
        (IPCA, "IPCA"),
        (INPC, "INPC"),
        (IGP_M, "IGP-M"),
        (META_BC, "Meta Bacen"),
    ]

    indice = models.CharField("índice", max_length=10, choices=CHOICES_INDICE)
    ano = models.PositiveSmallIntegerField("ano")
    percentual = models.DecimalField("percentual (%)", max_digits=6, decimal_places=2)

    class Meta:
        ordering = ["-ano", "indice"]
        verbose_name = "índice de reajuste"
        verbose_name_plural = "índices de reajuste"
        constraints = [
            models.UniqueConstraint(
                fields=["indice", "ano"],
                name="catalogo_indicereajuste_indice_ano_unico",
            ),
        ]

    def __str__(self):
        return f"{self.indice} {self.ano}: {self.percentual}%"


class DominioBase(models.Model):
    """Base das 8 tabelas de vocabulário. Cada uma carrega um
    `nome` editável no Admin e um `nome_normalizado` derivado, único, que é a
    chave natural do upsert idempotente do import."""

    nome = models.CharField("nome", max_length=255, unique=True)
    nome_normalizado = models.CharField(
        "nome normalizado",
        max_length=255,
        unique=True,
        db_index=True,
        editable=False,
    )

    class Meta:
        abstract = True
        ordering = [Collate(F("nome"), "ptbr")]

    def save(self, *args, **kwargs):
        self.nome_normalizado = normalizar_nome(self.nome)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class Unidade(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "unidade organizacional"
        verbose_name_plural = "unidades organizacionais"


class Categoria(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "categoria"
        verbose_name_plural = "categorias"


class Tipo(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "tipo de contratação"
        verbose_name_plural = "tipos de contratação"


class GrauPrioridade(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "grau de prioridade"
        verbose_name_plural = "graus de prioridade"


class Classificacao(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "classificação"
        verbose_name_plural = "classificações"


class Modalidade(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "modalidade"
        verbose_name_plural = "modalidades"


class InstrumentoContratual(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "instrumento contratual"
        verbose_name_plural = "instrumentos contratuais"


class SituacaoNormalizada(DominioBase):
    class Meta(DominioBase.Meta):
        verbose_name = "situação normalizada"
        verbose_name_plural = "situações normalizadas"
