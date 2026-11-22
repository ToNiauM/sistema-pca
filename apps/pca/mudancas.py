"""Proposta automática de texto para o campo Observação do modal "Registrar
acompanhamento", a partir das mudanças que o editor fez
no item desde o último Acompanhamento registrado.

Módulo de domínio puro no sentido do contrato deste app: nenhuma view, nada
de template, sem nada da camada de apresentação web — só ORM de leitura
(`Processo.history`, `Processo.acompanhamentos`) e formatação. A mesma
ideia de `apps/pca/sei/regras.py` (l. 424-470: "campo: valor (antes: X)"),
levada ao editor humano com um formato de frase diferente — natural,
terminada em ponto, reaproveitando os MESMOS filtros de apresentação que a
tela já usa (`core.templatetags.dsgov.moeda`/`data_br`,
`apps.pca.filtros.NOMES_MES`), nunca uma segunda formatação solta.

`propor_texto` NUNCA grava nada — só lê. Quem chama decide o que fazer com
o texto (só `initial` do formulário no GET do modal, nunca sozinho no
banco).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from apps.pca.filtros import NOMES_MES
from core.templatetags.dsgov import data_br, moeda


@dataclass(frozen=True)
class _Campo:
    nome: str
    rotulo: str
    tipo: str  # "moeda" | "data" | "mes" | "fk" | "texto" | "generico"
    genero: str = "m"  # "m" | "f" — só usado por "definido"/"removido"
    texto_generico: str = ""


# Ordem institucional da frase final: planejamento -> funil -> execução
# contratual -> objeto/justificativa (grp). `justificativa`
# entra aqui como TEXTO LONGO com frase genérica — o padrão de escrita do
# próprio campo (help_text do form) já cobre o "porquê" de verdade;
# esta lista só sinaliza QUE o campo mudou.
CAMPOS_PROPOSTA = [
    _Campo("valor_estimado", "Valor estimado", "moeda"),
    _Campo("valor_contratado", "Valor contratado", "moeda"),
    _Campo("mes_previsto", "Mês previsto", "mes"),
    _Campo("prazo_entrega", "Prazo inicial", "data"),
    _Campo("data_prevista_conclusao", "Data prevista de conclusão", "data", genero="f"),
    _Campo("data_envio_gelic", "Data de envio ao Gelic", "data", genero="f"),
    _Campo("data_recebimento_gelic", "Data de recebimento no Gelic", "data", genero="f"),
    _Campo("data_assinatura_contrato", "Data de assinatura do contrato", "data", genero="f"),
    _Campo("vigencia_inicio", "Vigência início", "data", genero="f"),
    _Campo("vigencia_fim", "Vigência fim", "data", genero="f"),
    _Campo("unidade_organizacional", "Unidade organizacional", "fk", genero="f"),
    _Campo("tipo", "Tipo de contratação", "fk"),
    _Campo("modalidade", "Modalidade", "fk", genero="f"),
    _Campo("categoria", "Categoria", "fk", genero="f"),
    _Campo("instrumento_contratual", "Instrumento contratual", "fk"),
    _Campo("fornecedor_razao_social", "Fornecedor", "texto"),
    _Campo("numero_instrumento_contratual", "Nº do instrumento contratual", "texto"),
    _Campo("descricao_objeto", "objeto", "generico", texto_generico="Objeto atualizado."),
    _Campo(
        "justificativa",
        "justificativa do item",
        "generico",
        texto_generico="Justificativa do item atualizada.",
    ),
]

_ORDEM_CAMPOS = [campo.nome for campo in CAMPOS_PROPOSTA]
_POR_NOME = {campo.nome: campo for campo in CAMPOS_PROPOSTA}


def _formatar(tipo: str, valor) -> str:
    if tipo == "moeda":
        return moeda(valor)
    if tipo == "data":
        return data_br(valor)
    if tipo == "mes":
        nome = NOMES_MES.get(int(valor)) if valor else None
        return nome.lower() if nome else "—"
    if tipo == "fk":
        return getattr(valor, "nome", None) or str(valor)
    return str(valor)


def frase(campo: str, antes, depois) -> str | None:
    """Uma frase institucional para a mudança de `campo`, ou `None` quando
    o campo está fora de `CAMPOS_PROPOSTA` ou `antes == depois` (sem
    mudança de fato)."""
    meta = _POR_NOME.get(campo)
    if meta is None or antes == depois:
        return None
    if meta.tipo == "generico":
        return meta.texto_generico
    sufixo = "a" if meta.genero == "f" else "o"
    if depois in (None, ""):
        return f"{meta.rotulo} removid{sufixo}."
    valor_depois = _formatar(meta.tipo, depois)
    if antes in (None, ""):
        return f"{meta.rotulo} definid{sufixo} como {valor_depois}."
    valor_antes = _formatar(meta.tipo, antes)
    return f"{meta.rotulo} alterad{sufixo} de {valor_antes} para {valor_depois}."


def _e_usuario_tecnico(versao) -> bool:
    usuario = versao.history_user
    if usuario is None:
        return False
    email_tecnico = getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"
    return usuario.email == email_tecnico


def propor_texto(processo, *, ate: datetime | None = None) -> str:
    """Frases juntas por espaço, na ordem de `CAMPOS_PROPOSTA`, cobrindo as
    mudanças no item desde o último Acompanhamento registrado (sem
    Acompanhamento algum: desde a primeira versão do histórico).

    Descarta versões cujo autor é o usuário técnico do robô SEI
    (`settings.SEI_USUARIO_TECNICO_EMAIL`) — o robô já formata suas
    próprias frases em `apps/pca/sei/regras.py`, esta proposta não repete.
    Consolida três edições do mesmo campo numa frase só: o "antes" é o
    valor na última versão ANTES do corte (o Acompanhamento mais recente,
    ou a primeira versão do item quando não há nenhum), o "depois" é o
    valor na última versão elegível encontrada. Sem mudança elegível,
    devolve string vazia — nunca `None`.
    """
    ultimo_acompanhamento = processo.acompanhamentos.first()
    corte = None
    if ultimo_acompanhamento is not None:
        criacao = ultimo_acompanhamento.history.order_by("history_date", "history_id").first()
        corte = criacao.history_date if criacao is not None else None

    versoes = list(
        processo.history.select_related("history_user").order_by(
            "history_date", "history_id"
        )
    )
    if ate is not None:
        versoes = [versao for versao in versoes if versao.history_date <= ate]
    if not versoes:
        return ""

    if corte is not None:
        anteriores = [versao for versao in versoes if versao.history_date <= corte]
        posteriores = [versao for versao in versoes if versao.history_date > corte]
        if not anteriores:
            return ""
        linha_base = anteriores[-1]
    else:
        linha_base = versoes[0]
        posteriores = versoes[1:]

    elegiveis = [versao for versao in posteriores if not _e_usuario_tecnico(versao)]
    if not elegiveis:
        return ""
    linha_final = elegiveis[-1]

    frases = []
    for campo in _ORDEM_CAMPOS:
        # Snapshot antigo de FK (unidade/tipo/categoria/modalidade/
        # instrumento_contratual) pode apontar para uma linha de catálogo já
        # excluída (fusão/depuração de vocabulário): `getattr` dispara a
        # consulta e levanta `DoesNotExist` em vez de devolver `None`. Acha-
        # do real: 11 dos 155 itens do banco de dev quebravam o GET do modal
        # inteiro por causa disso. Degrada pulando só a frase deste campo —
        # nunca 500 o modal por causa de uma referência morta num campo que
        # nem mudou de verdade.
        try:
            antes = getattr(linha_base, campo)
            depois = getattr(linha_final, campo)
        except ObjectDoesNotExist:
            continue
        texto = frase(campo, antes, depois)
        if texto:
            frases.append(texto)
    return " ".join(frases)
