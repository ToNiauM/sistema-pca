"""Fluxo administrativo de exportar/importar o banco em XLSX (quick). Mesmo padrão de segurança de `apps/pca/importacao/views.py`
diretório privado, token opaco de 43 caracteres,
`hmac.compare_digest`, TTL de 15 minutos, rename pending→claimed — mas
reimplementado aqui com nomes próprios: `core/` não importa `apps.pca`."""

import hmac
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from django import forms
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone

from core import banco_xlsx


def _exigir_superuser(request):
    """Proteção local além do `admin_view` registrado pelo admin."""
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied


CHAVE_SESSAO_UPLOAD_PENDENTE = "core_banco_upload_pendente"
DIRETORIO_UPLOAD_PENDENTE = Path(tempfile.gettempdir()) / "pca-banco-admin"
TTL_UPLOAD_SEGUNDOS = 15 * 60
COMPRIMENTO_REFERENCIA = 43
EXTENSAO_PERMITIDA = ".xlsx"
TAMANHO_MAXIMO_MB = 20
TAMANHO_MAXIMO_BYTES = TAMANHO_MAXIMO_MB * 1024 * 1024
# A extensão permanece .xlsx porque o openpyxl valida o sufixo antes de abrir.
SUFIXO_PENDING = ".pending.xlsx"
SUFIXO_CLAIMED = ".claimed.xlsx"
_NOME_UPLOAD = re.compile(r"^[A-Za-z0-9_-]{43}\.(?:pending|claimed)\.xlsx$")


def _diretorio_uploads():
    """Namespace privado, sem aceitar localização fornecida pelo cliente."""
    DIRETORIO_UPLOAD_PENDENTE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DIRETORIO_UPLOAD_PENDENTE, 0o700)
    return DIRETORIO_UPLOAD_PENDENTE


def _referencia_valida(referencia):
    return isinstance(referencia, str) and bool(
        re.fullmatch(r"[A-Za-z0-9_-]{43}", referencia)
    )


def _caminho_upload(referencia, sufixo):
    """Deriva um caminho no namespace privado exclusivamente de token e estado."""
    if sufixo not in (SUFIXO_PENDING, SUFIXO_CLAIMED) or not _referencia_valida(referencia):
        raise ValueError("Referência de upload inválida.")
    return _diretorio_uploads() / f"{referencia}{sufixo}"


def _apagar_se_existir(caminho):
    try:
        caminho.unlink()
    except FileNotFoundError:
        pass


def limpar_uploads_pendentes_expirados(*, agora=None):
    """Remove somente pendências abandonadas; claimed pertence ao executor em curso."""
    instante = int(time.time()) if agora is None else int(agora)
    diretorio = _diretorio_uploads()
    for caminho in diretorio.iterdir():
        if not _NOME_UPLOAD.fullmatch(caminho.name) or not caminho.name.endswith(SUFIXO_PENDING):
            continue
        try:
            if not caminho.is_file() or caminho.stat().st_mtime > instante - TTL_UPLOAD_SEGUNDOS:
                continue
            caminho.unlink()
        except FileNotFoundError:
            continue


def _descartar_pendente_da_sessao(request):
    registro = request.session.pop(CHAVE_SESSAO_UPLOAD_PENDENTE, None)
    if isinstance(registro, dict) and _referencia_valida(registro.get("referencia")):
        _apagar_se_existir(_caminho_upload(registro["referencia"], SUFIXO_PENDING))


def _salvar_upload_pendente(arquivo):
    referencia = secrets.token_urlsafe(32)
    caminho = _caminho_upload(referencia, SUFIXO_PENDING)
    try:
        descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descritor, "wb") as destino:
            os.fchmod(destino.fileno(), 0o600)
            for bloco in arquivo.chunks():
                destino.write(bloco)
    except Exception:
        _apagar_se_existir(caminho)
        raise
    return referencia, caminho


def _registro_pendente_valido(request, referencia):
    registro = request.session.get(CHAVE_SESSAO_UPLOAD_PENDENTE)
    if not isinstance(registro, dict):
        return None
    referencia_registrada = registro.get("referencia")
    if not _referencia_valida(referencia_registrada) or not hmac.compare_digest(
        referencia, referencia_registrada
    ):
        return None
    if registro.get("superuser_pk") != request.user.pk:
        return None
    criado_em = registro.get("criado_em")
    if not isinstance(criado_em, int) or int(time.time()) - criado_em > TTL_UPLOAD_SEGUNDOS:
        _descartar_pendente_da_sessao(request)
        return None
    caminho = _caminho_upload(referencia, SUFIXO_PENDING)
    try:
        if not caminho.is_file():
            return None
    except OSError:
        return None
    return registro, caminho


def _redirecionar_confirmacao_invalida(request):
    messages.error(
        request, "Não foi possível confirmar a importação. Envie o arquivo novamente."
    )
    return redirect("admin:banco_importar")


class UploadBancoForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo .xlsx", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"})
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome_seguro = Path(arquivo.name).name
        if not nome_seguro.lower().endswith(EXTENSAO_PERMITIDA):
            raise forms.ValidationError("Envie um arquivo .xlsx.")
        if arquivo.size > TAMANHO_MAXIMO_BYTES:
            raise forms.ValidationError(
                f"O arquivo deve ter no máximo {TAMANHO_MAXIMO_MB} MB."
            )
        return arquivo


class ConfirmarBancoForm(forms.Form):
    """Confirma somente uma referência opaca; os metadados ficam no servidor."""

    referencia = forms.RegexField(
        regex=re.compile(r"^[A-Za-z0-9_-]{43}$"),
        max_length=43,
        min_length=43,
        widget=forms.HiddenInput,
    )


def exportar_view(request):
    _exigir_superuser(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    buffer = banco_xlsx.exportar_banco_xlsx()
    nome_arquivo = f"pca-banco-{timezone.localdate():%Y%m%d}.xlsx"
    resposta = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    resposta["X-Content-Type-Options"] = "nosniff"
    return resposta


def importar_view(request):
    _exigir_superuser(request)
    form = UploadBancoForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        limpar_uploads_pendentes_expirados()
        _descartar_pendente_da_sessao(request)
        caminho = None
        try:
            referencia, caminho = _salvar_upload_pendente(arquivo)
            dados = banco_xlsx.ler_planilha_banco(str(caminho))
            relatorio = banco_xlsx.calcular_relatorio(dados)
        except Exception as exc:  # arquivo corrompido/formato inesperado
            if caminho is not None:
                _apagar_se_existir(caminho)
            form.add_error(None, f"Não foi possível ler o arquivo: {exc}")
        else:
            request.session[CHAVE_SESSAO_UPLOAD_PENDENTE] = {
                "referencia": referencia,
                "arquivo_nome": Path(arquivo.name).name,
                "superuser_pk": request.user.pk,
                "criado_em": int(time.time()),
            }
            confirmar_form = None
            if not relatorio.tem_erros:
                confirmar_form = ConfirmarBancoForm(initial={"referencia": referencia})
            return render(
                request,
                "admin/banco/relatorio.html",
                {"relatorio": relatorio, "confirmar_form": confirmar_form},
            )

    return render(request, "admin/banco/exportar_importar.html", {"form": form})


def confirmar_view(request):
    _exigir_superuser(request)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    form = ConfirmarBancoForm(request.POST)
    if not form.is_valid():
        return _redirecionar_confirmacao_invalida(request)

    referencia = form.cleaned_data["referencia"]
    pendente = _registro_pendente_valido(request, referencia)
    if pendente is None:
        return _redirecionar_confirmacao_invalida(request)

    _registro, caminho_pendente = pendente
    caminho_claimed = _caminho_upload(referencia, SUFIXO_CLAIMED)
    try:
        os.replace(caminho_pendente, caminho_claimed)
    except FileNotFoundError:
        return _redirecionar_confirmacao_invalida(request)
    request.session.pop(CHAVE_SESSAO_UPLOAD_PENDENTE, None)

    try:
        # Relê e recalcula agora — defesa contra o banco ter mudado entre o
        # passo 2 (relatório) e este passo 3.
        dados = banco_xlsx.ler_planilha_banco(str(caminho_claimed))
        relatorio = banco_xlsx.calcular_relatorio(dados)
        if relatorio.tem_erros:
            messages.error(
                request,
                "O banco mudou desde a conferência e o arquivo agora tem "
                "erros. Nada foi gravado — confira e envie novamente.",
            )
            return redirect("admin:banco_importar")

        try:
            banco_xlsx.fazer_backup_sqlite()
        except Exception as exc:
            messages.error(
                request, f"Backup do banco falhou — nada foi gravado: {exc}"
            )
            return redirect("admin:banco_importar")

        with transaction.atomic():
            resultado = banco_xlsx.aplicar_relatorio(dados, request.user)

        total_criados = 0
        total_atualizados = 0
        for modelo, contagem in resultado.items():
            criados = contagem["criados"]
            atualizados = contagem["atualizados"]
            total_criados += criados
            total_atualizados += atualizados
            if criados or atualizados:
                LogEntry.objects.log_action(
                    user_id=request.user.pk,
                    content_type_id=ContentType.objects.get_for_model(modelo).pk,
                    object_id="",
                    object_repr=str(modelo._meta.verbose_name_plural),
                    action_flag=CHANGE,
                    change_message=(
                        f"Importação XLSX do banco: {criados} criado(s), "
                        f"{atualizados} atualizado(s)"
                    ),
                )

        messages.success(
            request,
            f"Importação concluída: {total_criados} linha(s) criada(s), "
            f"{total_atualizados} linha(s) atualizada(s).",
        )
        return redirect("admin:banco_importar")
    finally:
        _apagar_se_existir(caminho_claimed)
