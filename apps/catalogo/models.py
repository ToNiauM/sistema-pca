from django.db import models

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


class DominioBase(models.Model):
    """Base das tabelas de vocabulário: `nome` editável no Admin e `nome_normalizado` derivado, usado como chave do upsert do import."""

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
        ordering = ["nome"]

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
