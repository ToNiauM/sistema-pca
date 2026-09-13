from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Lotação", {"fields": ("unidade",)}),)
    list_display = ("username", "first_name", "last_name", "email", "unidade", "is_active", "is_staff")
