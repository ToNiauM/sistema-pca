from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuário do sistema. Estende o padrão do Django para permitir campos futuros sem migração dolorosa."""

    unidade = models.CharField("unidade", max_length=120, blank=True)

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def iniciais(self) -> str:
        partes = (self.get_full_name() or self.username).split()
        return "".join(p[0] for p in partes[:2]).upper()
