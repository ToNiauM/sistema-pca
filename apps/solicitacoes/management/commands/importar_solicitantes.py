"""Importa a planilha de solicitantes das unidades (Fase 43).

Colunas: nome, e-mail e unidades (várias separadas por ";"). Cada linha vira um usuário do grupo
`solicitante` com os vínculos usuário↔unidade. Usuário novo recebe senha provisória aleatória e
`senha_temporaria=True` (a troca no 1º acesso já existe); usuário que já existe NUNCA tem a senha tocada —
só ganha o grupo, o nome da planilha e os vínculos que faltam (nada é removido: quem sai de uma unidade
é tirado no Admin).

Tudo ou nada: a planilha inteira é conferida antes de gravar; qualquer erro (e-mail inválido ou repetido,
unidade que não existe) é listado e NADA é criado. `--dry-run` confere e conta, sem gravar. As senhas
provisórias vão SÓ para o arquivo de `--saida` (CSV, permissão 600, fora da árvore do projeto, nunca
sobrescreve outro arquivo); não aparecem no terminal nem em log. Rodar de novo com a mesma planilha não
muda nada e não gera senha.
"""

from __future__ import annotations

import csv
import io
import os
import re
import secrets
from pathlib import Path
from zipfile import BadZipFile

import openpyxl
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from openpyxl.utils.exceptions import InvalidFileException

from apps.catalogo.models import Unidade
from apps.catalogo.utils import normalizar_nome
from apps.solicitacoes.models import VinculoUnidade

GRUPO = "solicitante"
# Sem 0/O/1/l/I: a senha é digitada por gente a partir do arquivo entregue.
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
TAMANHO_SENHA = 16
COLUNAS = {"nome": {"nome"}, "email": {"email"}, "unidades": {"unidades", "unidade"}}
SEPARADOR_UNIDADES = re.compile(r"[;\n]")


def _chave_coluna(texto) -> str:
    return re.sub(r"[\s_\-.]+", "", normalizar_nome(str(texto or "")))


def _celula(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _ler_xlsx(caminho: Path) -> list[list[str]]:
    try:
        pasta = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, KeyError) as erro:
        raise CommandError(f"Não consegui abrir a planilha {caminho}: {erro}") from erro
    try:
        return [[_celula(c) for c in linha] for linha in pasta.worksheets[0].iter_rows(values_only=True)]
    finally:
        pasta.close()


def _ler_csv(caminho: Path) -> list[list[str]]:
    try:
        bruto = caminho.read_bytes()
    except OSError as erro:
        raise CommandError(f"Não consegui abrir a planilha {caminho}: {erro}") from erro
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delimitador = max((",", ";", "\t"), key=lambda d: (primeira.count(d), d == ","))
    return [[_celula(c) for c in linha] for linha in csv.reader(io.StringIO(texto), delimiter=delimitador)]


def ler_linhas(caminho: Path) -> list[tuple[int, str, str, list[str]]]:
    """`[(número da linha na planilha, nome, e-mail, [unidades])]`, sem as linhas em branco."""
    sufixo = caminho.suffix.lower()
    if sufixo not in (".xlsx", ".xlsm", ".csv", ".txt"):
        raise CommandError("Formato não suportado: use .xlsx ou .csv.")
    grade = _ler_xlsx(caminho) if sufixo in (".xlsx", ".xlsm") else _ler_csv(caminho)
    if not grade:
        raise CommandError("A planilha está vazia.")
    cabecalho = [_chave_coluna(c) for c in grade[0]]
    indice = {}
    for campo, nomes in COLUNAS.items():
        achadas = [i for i, c in enumerate(cabecalho) if c in nomes]
        if not achadas:
            raise CommandError(f"Falta a coluna '{campo if campo != 'email' else 'e-mail'}' no cabeçalho da planilha.")
        indice[campo] = achadas[0]
    linhas = []
    for numero, linha in enumerate(grade[1:], start=2):
        if not any(linha):
            continue
        celulas = linha + [""] * (len(cabecalho) - len(linha))
        # CSV com ";" como delimitador parte "A;B" em várias células: se "unidades" é a última coluna,
        # tudo o que vem dali em diante é unidade.
        if indice["unidades"] == len(cabecalho) - 1:
            bruto_unidades = ";".join(c for c in celulas[indice["unidades"]:] if c)
        else:
            bruto_unidades = celulas[indice["unidades"]]
        unidades = []
        for texto in SEPARADOR_UNIDADES.split(bruto_unidades):
            texto = " ".join(texto.split())
            if texto and normalizar_nome(texto) not in {normalizar_nome(u) for u in unidades}:
                unidades.append(texto)
        linhas.append((numero, " ".join(celulas[indice["nome"]].split()), celulas[indice["email"]].lower(), unidades))
    if not linhas:
        raise CommandError("A planilha não tem nenhuma linha de solicitante.")
    return linhas


def conferir(linhas) -> tuple[list[dict], list[str]]:
    """Valida tudo antes de gravar. Devolve `(registros, erros)`; com erro, nada deve ser gravado."""
    por_nome = {u.nome_normalizado: u for u in Unidade.objects.all()}
    registros, erros, vistos = [], [], {}
    for numero, nome, email, textos in linhas:
        try:
            validate_email(email)
        except ValidationError:
            erros.append(f"Linha {numero}: e-mail inválido ({email or 'vazio'}).")
            email = ""
        if email:
            if email in vistos:
                erros.append(f"Linha {numero}: e-mail repetido ({email}; já na linha {vistos[email]}).")
            else:
                vistos[email] = numero
        if not nome:
            erros.append(f"Linha {numero}: falta o nome.")
        if not textos:
            erros.append(f"Linha {numero}: falta ao menos uma unidade.")
        unidades = []
        for texto in textos:
            unidade = por_nome.get(normalizar_nome(texto))
            if unidade is None:
                erros.append(f"Linha {numero}: a unidade '{texto}' não existe no cadastro.")
            else:
                unidades.append(unidade)
        registros.append({"linha": numero, "nome": nome, "email": email, "unidades": unidades})
    return registros, erros


def _nomes(nome: str) -> tuple[str, str]:
    primeiro, _, resto = nome.partition(" ")
    return primeiro[:150], resto[:150]


def _gerar_senha(usuario) -> str:
    for _ in range(20):
        senha = "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_SENHA))
        try:
            validate_password(senha, usuario)
        except ValidationError:
            continue
        return senha
    raise CommandError("Não consegui gerar uma senha provisória válida.")


class Command(BaseCommand):
    help = (
        "Importa solicitantes (nome, e-mail, unidades separadas por ';') de uma planilha .xlsx/.csv: cria ou "
        "atualiza usuários do grupo 'solicitante' e os vínculos com as unidades. Senhas provisórias só no "
        "arquivo de --saida (permissão 600)."
    )

    def add_arguments(self, parser):
        parser.add_argument("planilha", help="caminho da planilha .xlsx ou .csv")
        parser.add_argument("--saida", help="CSV (permissão 600, fora do projeto) com as senhas provisórias dos usuários novos")
        parser.add_argument("--dry-run", action="store_true", help="confere e conta, sem gravar nada")

    def handle(self, *args, **opcoes):
        dry_run = opcoes["dry_run"]
        caminho = Path(opcoes["planilha"])
        saida = Path(opcoes["saida"]) if opcoes["saida"] else None

        registros, erros = conferir(ler_linhas(caminho))
        if erros:
            raise CommandError(
                "Nada foi gravado. Corrija a planilha:\n" + "\n".join(f"  - {e}" for e in erros)
            )
        grupo = Group.objects.filter(name=GRUPO).first()
        if grupo is None:
            raise CommandError(f"O grupo '{GRUPO}' não existe: rode `migrate`.")

        Usuario = get_user_model()
        plano = []
        for registro in registros:
            usuario = Usuario.objects.filter(email__iexact=registro["email"]).first()
            if usuario is None:
                acao = "criar"
            else:
                primeiro, resto = _nomes(registro["nome"])
                ja_tem = set(
                    VinculoUnidade.objects.filter(usuario=usuario).values_list("unidade_id", flat=True)
                )
                muda = (
                    not usuario.groups.filter(pk=grupo.pk).exists()
                    or (usuario.first_name, usuario.last_name) != (primeiro, resto)
                    or any(u.pk not in ja_tem for u in registro["unidades"])
                )
                acao = "atualizar" if muda else "sem mudança"
            plano.append((registro, usuario, acao))

        novos = sum(1 for _, _, acao in plano if acao == "criar")
        # O arquivo das senhas só é exigido (e só é conferido) quando há senha a entregar: rodar de novo a
        # mesma linha de comando, sem ninguém novo, não esbarra no arquivo da primeira vez.
        if novos and not dry_run:
            if saida is None:
                raise CommandError("Há usuários a criar: informe --saida com o arquivo das senhas provisórias.")
            self._conferir_saida(saida)

        for registro, usuario, acao in plano:
            aviso = " (usuário inativo: não reativado)" if usuario is not None and not usuario.is_active else ""
            unidades = "; ".join(u.nome for u in registro["unidades"])
            self.stdout.write(f"Linha {registro['linha']}: {acao} — {registro['email']} [{unidades}]{aviso}")

        if dry_run:
            self._resumo(plano, "Simulação (--dry-run): nada foi gravado. ")
            return

        gravou_saida = False
        try:
            with transaction.atomic():
                credenciais = self._gravar(plano, grupo)
                if credenciais:
                    self._escrever_saida(saida, credenciais)
                    gravou_saida = True
        except Exception:
            if gravou_saida:
                saida.unlink(missing_ok=True)
            raise
        self._resumo(plano, "")
        if credenciais:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(credenciais)} senha(s) provisória(s) gravada(s) em {saida} (permissão 600). "
                    "Entregue a cada pessoa e apague o arquivo; a troca é exigida no 1º acesso."
                )
            )

    # -- apoio ---------------------------------------------------------------------------

    def _conferir_saida(self, saida: Path):
        resolvido = saida.resolve()
        if resolvido.is_relative_to(Path(settings.BASE_DIR).resolve()):
            raise CommandError(
                "Grave o arquivo das senhas FORA da árvore do projeto (ex.: /tmp/solicitantes-senhas.csv)."
            )
        if not resolvido.parent.is_dir():
            raise CommandError(f"O diretório {resolvido.parent} não existe.")
        if resolvido.exists() or saida.is_symlink():
            raise CommandError(f"{saida} já existe: o comando não sobrescreve arquivo de senhas.")

    def _gravar(self, plano, grupo) -> list[tuple[str, str, str, str]]:
        Usuario = get_user_model()
        credenciais = []
        for registro, usuario, acao in plano:
            if acao == "sem mudança":
                continue
            primeiro, resto = _nomes(registro["nome"])
            if usuario is None:
                provisorio = Usuario(email=registro["email"], first_name=primeiro, last_name=resto)
                senha = _gerar_senha(provisorio)
                usuario = Usuario.objects.create_user(
                    email=registro["email"], password=senha, first_name=primeiro, last_name=resto,
                    senha_temporaria=True,
                )
                credenciais.append(
                    (registro["nome"], usuario.email, senha, "; ".join(u.nome for u in registro["unidades"]))
                )
            elif (usuario.first_name, usuario.last_name) != (primeiro, resto):
                usuario.first_name, usuario.last_name = primeiro, resto
                usuario.save(update_fields=["first_name", "last_name"])
            usuario.groups.add(grupo)
            for unidade in registro["unidades"]:
                VinculoUnidade.objects.get_or_create(usuario=usuario, unidade=unidade)
        return credenciais

    def _escrever_saida(self, saida: Path, credenciais):
        try:
            descritor = os.open(saida, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as erro:
            raise CommandError(f"Não consegui criar {saida}: {erro}") from erro
        try:
            with os.fdopen(descritor, "w", encoding="utf-8", newline="") as arquivo:
                escritor = csv.writer(arquivo)
                escritor.writerow(["nome", "e-mail", "senha provisória", "unidades"])
                escritor.writerows(credenciais)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.chmod(saida, 0o600)
        except Exception as erro:
            saida.unlink(missing_ok=True)
            raise CommandError(f"Não consegui gravar {saida}: {erro}") from erro

    def _resumo(self, plano, prefixo: str):
        contagem = {"criar": 0, "atualizar": 0, "sem mudança": 0}
        for _, _, acao in plano:
            contagem[acao] += 1
        verbo = "a criar" if prefixo else "criado(s)"
        verbo_atualizar = "a atualizar" if prefixo else "atualizado(s)"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefixo}{contagem['criar']} {verbo}, {contagem['atualizar']} {verbo_atualizar}, "
                f"{contagem['sem mudança']} sem mudança."
            )
        )
