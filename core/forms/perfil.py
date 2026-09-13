"""Formulário da área "Meu perfil": só o que o usuário pode editar sobre si
mesmo (nome e sobrenome). E-mail é o identificador de login e só muda pelo
Admin; senha tem fluxo próprio (`core:trocar_senha`). Sem foto: o
avatar-letra da skill cobre a identificação."""

from django import forms

from core.models import Usuario


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ("first_name", "last_name")
        labels = {"first_name": "Nome", "last_name": "Sobrenome"}
