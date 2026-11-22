import hashlib
import math
import secrets

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils import timezone


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

    def get_by_natural_key(self, email):
        # QA de segurança 30/09/2026 (periferia #8) — único ponto que
        # `ModelBackend.authenticate()` (e o Admin) consulta para resolver
        # o usuário a partir do e-mail digitado; sem isto, grafias
        # diferentes do mesmo e-mail falham o login. O axes continua
        # contando cada grafia como tentativa separada (T-41o-04,
        # comportamento aceito, não é bypass do bloqueio).
        return self.get(email__iexact=email)

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

    O histórico de auditoria não é declarado diretamente aqui no modelo — a
    documentação do django-simple-history exige o registro explícito via
    `simple_history.register(Usuario)` para modelos de usuário customizados
    (ver core/admin.py Armadilha 7 §4).
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
        """Avatar-letra do header e do menu do padrão DSGov (`user.iniciais`):
        duas iniciais do nome completo ou, sem nome, a primeira letra do
        e-mail (a versão do padrão DSGov usa `username`, que aqui é `None`)."""
        partes = self.get_full_name().split()
        if partes:
            return "".join(p[0] for p in partes[:2]).upper()
        return (self.email or "?")[0].upper()


class TokenApi(models.Model):
    """Token pessoal de API (Fase 42) — autentica as extensões SEI Pro
    (`POST /api/sei/coleta` e demais rotas do plano) como o usuário
    REAL que gerou o token, nunca o usuário técnico "Robô SEI". FK (não
    OneToOne) porque o histórico de tokens revogados permanece no banco —
    só o token ATIVO (`revogado_em is None`) é único por usuário, garantia
    de `gerar()` em código, nunca `unique=True` no banco (o histórico
    revogado quebraria uma constraint de unicidade por usuário).

    Só o hash SHA-256 do valor é persistido (`hash`, `unique=True`); o
    valor em claro nasce e morre dentro de `gerar()` — nenhum outro ponto
    do sistema (nem este modelo) tem acesso a ele depois."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tokens_api",
        verbose_name="usuário",
    )
    hash = models.CharField("hash sha256", max_length=64, unique=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    ultimo_uso_em = models.DateTimeField("último uso em", null=True, blank=True)
    revogado_em = models.DateTimeField("revogado em", null=True, blank=True)

    class Meta:
        verbose_name = "token de API"
        verbose_name_plural = "tokens de API"

    def __str__(self):
        estado = "ativo" if self.revogado_em is None else "revogado"
        return f"{self.usuario} — token {estado} (criado em {self.criado_em:%d/%m/%Y})"

    @staticmethod
    def _hash_de(valor_em_claro: str) -> str:
        return hashlib.sha256(valor_em_claro.encode("utf-8")).hexdigest()

    @classmethod
    def gerar(cls, usuario) -> tuple["TokenApi", str]:
        """Revoga qualquer token ATIVO do mesmo usuário e gera um novo —
        devolve o PAR (instância, valor em claro); só esta chamada tem
        acesso ao valor em claro, que nunca é gravado no banco."""
        agora = timezone.now()
        cls.objects.filter(usuario=usuario, revogado_em__isnull=True).update(
            revogado_em=agora
        )
        valor_em_claro = secrets.token_urlsafe(32)
        instancia = cls.objects.create(usuario=usuario, hash=cls._hash_de(valor_em_claro))
        return instancia, valor_em_claro

    @classmethod
    def autenticar(cls, valor_em_claro: str):
        """Devolve o usuário dono do token ATIVO que corresponde ao valor
        em claro recebido (e marca `ultimo_uso_em`), ou `None` quando o
        hash não corresponde a nenhum token ativo."""
        token = (
            cls.objects.filter(hash=cls._hash_de(valor_em_claro), revogado_em__isnull=True)
            .select_related("usuario")
            .first()
        )
        if token is None:
            return None
        token.ultimo_uso_em = timezone.now()
        token.save(update_fields=["ultimo_uso_em"])
        return token.usuario


class PreferenciaAparencia(models.Model):
    """Aparência da casca Tabler escolhida por cada usuário (claro/escuro, cor principal, tom de base,
    cantos) — acompanha a pessoa em qualquer navegador. Tabela própria, e não campos em `Usuario`, para que
    trocar de cor não entre no histórico de auditoria do usuário. Os valores são os atributos nativos do
    Tabler (`data-bs-theme-primary`/`-base`/`-radius`, `tabler-themes.css`); a casca DSGov ignora tudo isto."""

    TEMAS = ("auto", "claro", "escuro")
    CORES = ("blue", "azure", "indigo", "purple", "pink", "red", "orange", "yellow", "lime", "green", "teal", "cyan")
    BASES = ("slate", "gray", "zinc", "neutral", "stone")
    CANTOS = ("0", "0.5", "1", "1.5", "2")
    PADRAO = {"tema": "auto", "cor": "blue", "base": "slate", "cantos": "1"}

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="aparencia", verbose_name="usuário"
    )
    tema = models.CharField("claro/escuro", max_length=10, default=PADRAO["tema"])
    cor = models.CharField("cor principal", max_length=10, default=PADRAO["cor"])
    base = models.CharField("tom de base", max_length=10, default=PADRAO["base"])
    cantos = models.CharField("cantos", max_length=4, default=PADRAO["cantos"])
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "preferência de aparência"
        verbose_name_plural = "preferências de aparência"

    def __str__(self):
        return f"{self.usuario} — {self.tema}/{self.cor}/{self.base}/{self.cantos}"

    @classmethod
    def valores_de(cls, usuario) -> dict:
        """Preferências do usuário (ou o padrão, para anônimo ou quem nunca escolheu)."""
        if not getattr(usuario, "is_authenticated", False):
            return dict(cls.PADRAO)
        pref = cls.objects.filter(usuario=usuario).first()
        if pref is None:
            return dict(cls.PADRAO)
        return {"tema": pref.tema, "cor": pref.cor, "base": pref.base, "cantos": pref.cantos}

    @classmethod
    def validar(cls, dados) -> dict:
        """Só aceita valores das listas; o que vier fora é ignorado (fica o padrão/atual)."""
        permitidos = {"tema": cls.TEMAS, "cor": cls.CORES, "base": cls.BASES, "cantos": cls.CANTOS}
        return {chave: dados[chave] for chave, opcoes in permitidos.items() if dados.get(chave) in opcoes}


class PreferenciaLarguras(models.Model):
    """Larguras de coluna ajustadas pelo usuário nas tabelas da casca Tabler —
    gravadas na CONTA, não no navegador: o localStorage é separado por domínio, e o sistema responde
    em mais de um (pca.sistemascfc.org e pca.analisedados.online). `larguras` é
    {"<caminho>#<tabela>": {"<coluna>": px}}; a coluna é a `data-coluna` do <th> (ou o rótulo), para
    que a largura acompanhe a coluna mesmo quando o usuário escolhe outras colunas."""

    LARGURA_MINIMA = 40
    LARGURA_MAXIMA = 2000
    LIMITE_CHAVE = 200
    # QA de segurança 30/09/2026 (achado B2) — sem teto, 300 POSTs com
    # chaves de tabela distintas infla o JSON da conta sem limite nenhum
    # (lido a cada página). Só bloqueia a criação de uma TABELA NOVA
    # quando o teto já foi atingido — apagar coluna/tabela nunca conta
    # contra ele.
    LIMITE_TABELAS = 200

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="larguras_colunas", verbose_name="usuário"
    )
    larguras = models.JSONField("larguras", default=dict)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "preferência de larguras de coluna"
        verbose_name_plural = "preferências de larguras de coluna"

    def __str__(self):
        return f"{self.usuario} — {len(self.larguras)} tabela(s)"

    @classmethod
    def da_pagina(cls, usuario, caminho: str) -> dict:
        """Larguras das tabelas da página `caminho` ({"<caminho>#<tabela>": {...}}), ou {}."""
        if not getattr(usuario, "is_authenticated", False):
            return {}
        pref = cls.objects.filter(usuario=usuario).first()
        if pref is None:
            return {}
        prefixo = caminho + "#"
        return {chave: valor for chave, valor in pref.larguras.items() if chave.startswith(prefixo)}

    @classmethod
    def gravar(cls, usuario, tabela: str, coluna: str | None, largura) -> bool:
        """Grava (ou apaga, com `largura` None) a largura de uma coluna; `coluna` None apaga a tabela
        inteira. Recusa chaves longas e larguras fora de [LARGURA_MINIMA, LARGURA_MAXIMA]."""
        if not tabela or len(tabela) > cls.LIMITE_CHAVE or (coluna is not None and (not coluna or len(coluna) > cls.LIMITE_CHAVE)):
            return False
        if largura is not None:
            if (
                isinstance(largura, bool)
                or not isinstance(largura, (int, float))
                or not math.isfinite(largura)
            ):
                return False
            largura = int(round(largura))
            if not cls.LARGURA_MINIMA <= largura <= cls.LARGURA_MAXIMA:
                return False
        pref, _ = cls.objects.get_or_create(usuario=usuario)
        if (
            coluna is not None
            and largura is not None
            and tabela not in pref.larguras
            and len(pref.larguras) >= cls.LIMITE_TABELAS
        ):
            return False
        colunas = dict(pref.larguras.get(tabela, {}))
        if coluna is None:
            colunas = {}
        elif largura is None:
            colunas.pop(coluna, None)
        else:
            colunas[coluna] = largura
        if colunas:
            pref.larguras[tabela] = colunas
        else:
            pref.larguras.pop(tabela, None)
        pref.save(update_fields=["larguras", "atualizado_em"])
        return True
