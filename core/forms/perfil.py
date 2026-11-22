"""Formulário da área "Meu perfil": só o que o usuário pode
editar sobre si mesmo (nome e sobrenome). E-mail é o identificador de login
e só muda pelo Admin; senha tem fluxo próprio (`core:trocar_senha`).
Sem foto: exigiria campo novo + migração + volume de mídia (regra "sem migração
em produção", 10/09/2026) — o avatar-letra do padrão DSGov cobre a identificação."""

from django import forms

from core.models import Usuario


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ("first_name", "last_name")
        labels = {"first_name": "Nome", "last_name": "Sobrenome"}
