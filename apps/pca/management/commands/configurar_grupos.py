"""Comando idempotente que garante `view_acompanhamento`
(permissão automática do Django para o model `Acompanhamento`) no grupo
`editor` — SEM migração. Os grupos `editor`/`visualizador` já existem desde
a migration 0004 na maioria dos ambientes, mas este comando não presume
isso: `get_or_create` também aqui, para valer em todo ambiente.

`.permissions.add()` (M2M) já é idempotente — rodar 2x não duplica nem
falha. NÃO toca/limpa as permissões de `visualizador` — este comando só
GARANTE o que `editor` precisa ter.
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Garante view_acompanhamento no grupo editor (acompanhamentos e "
        "prazos visíveis só para editor) — idempotente, sem migração."
    )

    def handle(self, *args, **options):
        grupo_editor, _ = Group.objects.get_or_create(name="editor")
        Group.objects.get_or_create(name="visualizador")

        permissao = Permission.objects.get(
            codename="view_acompanhamento", content_type__app_label="pca"
        )
        grupo_editor.permissions.add(permissao)

        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'editor' configurado — {grupo_editor.permissions.count()} "
            "permissão(ões)."
        ))
