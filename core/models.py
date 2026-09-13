from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UsuarioManager(BaseUserManager):
    """Gerente customizado: `UserManager` padrão exige `username`, que este
    modelo não tem — `create_user`/`create_superuser` passam a receber
    `email` como primeiro argumento posicional."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser precisa ter is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser precisa ter is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class Usuario(AbstractUser):
    """Usuário customizado com e-mail como identificador de login.

    O histórico de auditoria não é declarado diretamente aqui no modelo — o
    django-simple-history exige o registro explícito via
    `simple_history.register(Usuario)` para modelos de usuário
    customizados (ver core/admin.py).
    """

    username = None
    email = models.EmailField("e-mail", unique=True)
    senha_temporaria = models.BooleanField(
        "exige troca de senha no próximo acesso", default=False
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UsuarioManager()

    def __str__(self):
        return self.email

    @property
    def iniciais(self) -> str:
        """Avatar-letra do header e do menu da skill dsgov (`user.iniciais`):
        duas iniciais do nome completo ou, sem nome, a primeira letra do
        e-mail (a versão da skill usa `username`, que aqui é `None`)."""
        partes = self.get_full_name().split()
        if partes:
            return "".join(p[0] for p in partes[:2]).upper()
        return (self.email or "?")[0].upper()
