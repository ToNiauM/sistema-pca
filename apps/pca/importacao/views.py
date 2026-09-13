"""Fluxo administrativo de upload, conferência e confirmação da importação."""

import hmac
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from apps.pca.importacao.executor import USUARIO_PADRAO, executar_import
from apps.pca.importacao.forms import (
    TAMANHO_MAXIMO_BYTES,
    ConfirmarImportacaoForm,
    UploadPlanilhaForm,
    _nome_arquivo_seguro,
    _validar_nome_e_tamanho,
)
from apps.pca.importacao.modelo import NOME_ARQUIVO_MODELO, gerar_modelo_importacao
from apps.pca.importacao.models import EventoImportacao


def _usuario_importador():
    """Import não recebe a autoria de quem clicou na tela."""
    return get_user_model().objects.get(email=USUARIO_PADRAO)


def _exigir_superuser(request):
    """Proteção local além do admin_view registrado pelo admin."""
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied


CHAVE_SESSAO_UPLOAD_PENDENTE = "pca_importacao_upload_pendente"
DIRETORIO_UPLOAD_PENDENTE = Path(tempfile.gettempdir()) / "pca-importacao-admin"
TTL_UPLOAD_SEGUNDOS = 15 * 60
COMPRIMENTO_REFERENCIA = 43
# A extensão permanece .xlsx porque o openpyxl valida o sufixo antes de abrir.
SUFIXO_PENDING = ".pending.xlsx"
SUFIXO_CLAIMED = ".claimed.xlsx"
_NOME_UPLOAD = re.compile(r"^[A-Za-z0-9_-]{43}\.(?:pending|claimed)\.xlsx$")


def _diretorio_uploads():
    """Retorna o namespace privado, sem aceitar localização fornecida pelo cliente."""
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
    try:
        _validar_nome_e_tamanho(registro["arquivo_nome"], 0)
        exercicio_pk = int(registro["exercicio_pk"])
    except (KeyError, TypeError, ValueError):
        return None
    exercicio = UploadPlanilhaForm.base_fields["exercicio"].queryset.filter(pk=exercicio_pk).first()
    if exercicio is None:
        return None
    caminho = _caminho_upload(referencia, SUFIXO_PENDING)
    try:
        if not caminho.is_file() or caminho.stat().st_size > TAMANHO_MAXIMO_BYTES:
            return None
    except OSError:
        return None
    return registro, exercicio, caminho


def _redirecionar_confirmacao_invalida(request):
    messages.error(request, "Não foi possível confirmar a importação. Envie a planilha novamente.")
    return redirect("admin:pca_eventoimportacao_importar")


def baixar_modelo_view(request):
    """Disponibiliza o contrato XLSX ao superuser sem criar evento de importação."""
    _exigir_superuser(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    buffer = gerar_modelo_importacao()
    resposta = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resposta["Content-Disposition"] = f'attachment; filename="{NOME_ARQUIVO_MODELO}"'
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Length"] = str(buffer.getbuffer().nbytes)
    return resposta


def importar_view(request):
    _exigir_superuser(request)
    form = UploadPlanilhaForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        exercicio = form.cleaned_data["exercicio"]
        limpar_uploads_pendentes_expirados()
        _descartar_pendente_da_sessao(request)
        caminho = None
        try:
            referencia, caminho = _salvar_upload_pendente(arquivo)
            relatorio = executar_import(
                str(caminho), _usuario_importador(), exercicio, dry_run=True
            )
        except CommandError as exc:
            if caminho is not None:
                _apagar_se_existir(caminho)
            form.add_error(None, str(exc))
        except Exception:
            if caminho is not None:
                _apagar_se_existir(caminho)
            raise
        else:
            request.session[CHAVE_SESSAO_UPLOAD_PENDENTE] = {
                "referencia": referencia,
                "arquivo_nome": _nome_arquivo_seguro(arquivo.name),
                "exercicio_pk": exercicio.pk,
                "superuser_pk": request.user.pk,
                "criado_em": int(time.time()),
            }
            confirmar_form = ConfirmarImportacaoForm(
                initial={"referencia": referencia}
            )
            return render(
                request,
                "admin/importacao/importar.html",
                {"form": form, "confirmar_form": confirmar_form, "relatorio": relatorio.formatar()},
            )

    return render(request, "admin/importacao/importar.html", {"form": form})


def confirmar_view(request):
    _exigir_superuser(request)
    if request.method != "POST":
        return redirect("admin:pca_eventoimportacao_importar")

    form = ConfirmarImportacaoForm(request.POST)
    if not form.is_valid():
        return _redirecionar_confirmacao_invalida(request)

    referencia = form.cleaned_data["referencia"]
    pendente = _registro_pendente_valido(request, referencia)
    if pendente is None:
        return _redirecionar_confirmacao_invalida(request)

    registro, exercicio, caminho_pendente = pendente
    caminho_claimed = _caminho_upload(referencia, SUFIXO_CLAIMED)
    try:
        os.replace(caminho_pendente, caminho_claimed)
    except FileNotFoundError:
        return _redirecionar_confirmacao_invalida(request)
    request.session.pop(CHAVE_SESSAO_UPLOAD_PENDENTE, None)

    try:
        relatorio = executar_import(
            str(caminho_claimed), _usuario_importador(), exercicio, dry_run=False
        )
    except CommandError as exc:
        messages.error(request, str(exc))
        return redirect("admin:pca_eventoimportacao_importar")
    else:
        EventoImportacao.objects.create(
            disparado_por=request.user,
            arquivo_nome=registro["arquivo_nome"],
            exercicio=exercicio,
            processos_criados=relatorio.processos_criados,
            acompanhamentos_criados=relatorio.acompanhamentos_criados,
            relatorio_caminho=str(relatorio.caminho_relatorio),
        )
        messages.success(
            request,
            "Importação concluída: "
            f"{relatorio.processos_criados} processos e "
            f"{relatorio.acompanhamentos_criados} acompanhamentos criados.",
        )
        return redirect("admin:pca_eventoimportacao_changelist")
    finally:
        _apagar_se_existir(caminho_claimed)
