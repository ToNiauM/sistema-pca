"""Registro de quem disparou uma importação pela tela do admin, quando,
qual arquivo, qual exercício de destino e qual foi o resultado. O histórico
do processo continua assinado por USUARIO_PADRAO; este é um segundo rastro
de "quem apertou o botão"."""

from django.conf import settings
from django.db import models


class EventoImportacao(models.Model):
    disparado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="eventos_importacao",
        verbose_name="disparado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    arquivo_nome = models.CharField("nome do arquivo", max_length=255)
    exercicio = models.ForeignKey(
        "catalogo.Exercicio",
        on_delete=models.PROTECT,
        related_name="eventos_importacao",
        verbose_name="exercício",
    )
    processos_criados = models.PositiveIntegerField("processos criados", default=0)
    acompanhamentos_criados = models.PositiveIntegerField(
        "acompanhamentos criados", default=0
    )
    relatorio_caminho = models.CharField(
        "caminho do relatório", max_length=500, blank=True, default=""
    )

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "evento de importação"
        verbose_name_plural = "eventos de importação"

    def __str__(self):
        return f"{self.arquivo_nome} — {self.criado_em:%d/%m/%Y %H:%M}"
