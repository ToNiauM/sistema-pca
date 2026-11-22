"""Aplicação de `Proposta`s pelos serviços de domínio existentes (Fase 32).

Cliente de `apps/pca/services.py` — nunca escreve `Processo.situacao` direto
por conta própria (nunca um `setattr`/`update()`; toda escrita passa por
`registrar_acompanhamento`), nunca fala com o SEI (zero import de
`apps.pca.sei.coletor`). Consome `Proposta`s já calculadas por quem chama
`apps.pca.sei.regras.propor` (`sei_aplicar`/`sei_sincronizar`);
este módulo só GRAVA, pelos passos do §5 da spec. `aplicar_regras_automaticas`
decide a situação na esmagadora maioria dos casos (passo 3); o passo 3b é a
única exceção — decisão do usuário em 18/09/2026, "uma vez assinado, está
concluído": quando o instrumento de contratação está assinado pelo CFC E
pelo contratado, este módulo chama `registrar_acompanhamento(situacao_novo=
CONCLUIDO, ...)` direto, sobrepondo a guarda de `transicao_manual` (nunca
`aplicar_regras_automaticas`, que continua sem essa exceção).

`aplicar(propostas, simular=True)` calcula tudo e não grava absolutamente
nada — nem `Processo`, nem `Acompanhamento`, nem `data/sei/estado.json`, nem
o usuário técnico (M13: `_usuario_tecnico()` só é chamada
quando `simular=False`).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import transaction

from apps.catalogo.models import InstrumentoContratual, Modalidade
from apps.catalogo.utils import normalizar_nome
from apps.pca.models import Estado, Processo, Situacao, TipoEvento
from apps.pca.sei import execucoes
from apps.pca.regras_situacao import CONCLUSAO_BLOQUEADA
from apps.pca.services import (
    aplicar_regras_automaticas,
    atualizar_situacao_regra,
    exigencia_de,
    registrar_acompanhamento,
)

USUARIO_TECNICO_NOME = "Robô SEI"

# Campos de `Proposta.alteracoes` cujo valor não é gravável direto por
# `setattr` — carregam o rótulo canônico do catálogo (regras.py, Plano
# 32-01/33-02), e o campo do modelo é uma FK, não um `CharField`.
# `modalidade`: `_aplicar_campo` resolve por
# `get_or_create(nome=...)` contra os 7 registros JÁ EXISTENTES do
# catálogo — `regras.py` só produz um `rotulo_canonico` que já está em
# `_MODALIDADE_NORMALIZADO_PARA_ROTULO`, então `get_or_create` nunca cria
# um registro novo na prática (mesma garantia de `instrumento_contratual`).
_CAMPOS_FK_POR_ROTULO = {
    "instrumento_contratual": InstrumentoContratual,
    "modalidade": Modalidade,
}

_CAMPOS_GATILHO_TRANSICAO_MANUAL = {"data_assinatura_contrato", "data_recebimento_gelic"}

# Exceção decidida pelo usuário em 18/09/2026, após o teste do item 105:
# "uma vez assinado, está concluído" — sobrepõe a guarda de
# `transicao_manual` SÓ quando o instrumento de contratação está assinado
# por ambas as partes (ver §5 da spec e `aplicar()` abaixo).
OBSERVACAO_ASSINATURA_POR_AMBOS = (
    "Situação atualizada automaticamente para Concluído — instrumento "
    "assinado pelo CFC e pelo contratado no SEI (sobrepõe transição manual "
    "registrada em reunião)."
)

# Fase 42 — mesma frase, trocando a origem da confirmação: quando a
# chamada vem da extensão SEI Pro (`aplicar(origem="extensao")`), em vez do
# robô. Constante PARALELA — `OBSERVACAO_ASSINATURA_POR_AMBOS` acima nunca é
# editada (byte a byte igual ao texto já gravado em produção).
OBSERVACAO_ASSINATURA_POR_AMBOS_EXTENSAO = (
    "Situação atualizada automaticamente para Concluído — instrumento "
    "assinado pelo CFC e pelo contratado no SEI, pela extensão SEI Pro "
    "(sobrepõe transição manual registrada em reunião)."
)

# Mapa origem -> texto gravado no passo 3b (assinatura por ambas as
# partes) — só esta frase muda por `origem`; evidências (passo 4) e
# pendências (passo 6) são sempre as mesmas, independente de quem chamou.
_OBSERVACOES_ASSINATURA_POR_AMBOS = {
    "robo": OBSERVACAO_ASSINATURA_POR_AMBOS,
    "extensao": OBSERVACAO_ASSINATURA_POR_AMBOS_EXTENSAO,
}


def _usuario_tecnico():
    """`get_or_create` em runtime (nunca migração) — mesmo padrão
    do usuário de serviço do import (`core/migrations/0003_usuario_
    importacao.py`), adaptado: `is_active=False` + senha inutilizável, nunca
    consegue logar, só existe como autor de histórico. Só chamada
    na escrita real (`aplicar(simular=False)`, /M13) —
    `--simular` nunca toca a tabela de usuários."""
    Usuario = get_user_model()
    email = getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"
    usuario, _ = Usuario.objects.get_or_create(
        email=email,
        defaults={
            "is_active": False,
            "is_staff": False,
            "is_superuser": False,
            "first_name": USUARIO_TECNICO_NOME,
            "password": make_password(None),
        },
    )
    return usuario


def _aplicar_campo(processo, campo, valor):
    modelo_fk = _CAMPOS_FK_POR_ROTULO.get(campo)
    if modelo_fk is not None and valor is not None:
        # Achado dados M4 (QA 30/09/2026): `get_or_create(nome=valor)`
        # falha com `IntegrityError` quando o registro já existe com OUTRA
        # grafia mas o mesmo `nome_normalizado` (ex.: Admin edita "Dispensa
        # Com Disputa" para "DISPENSA COM DISPUTA") — `nome_normalizado` é
        # `unique=True`. Resolve primeiro por `nome_normalizado`; só cria
        # quando de fato não existe, preservando a grafia já cadastrada
        # (do Admin ou de uma proposta anterior) em vez de sobrescrevê-la.
        instancia = modelo_fk.objects.filter(
            nome_normalizado=normalizar_nome(valor)
        ).first()
        if instancia is None:
            instancia = modelo_fk.objects.create(nome=valor)
        setattr(processo, campo, instancia)
    else:
        setattr(processo, campo, valor)


def _normalizar_frase(texto):
    """`strip` + colapso de espaços — só o suficiente para comparar texto a
    texto sem falso-negativo por espaçamento."""
    return " ".join((texto or "").split())


def _frases_novas(processo, frases):
    """Diagnóstico: `regras.py` acrescenta a frase de
    assinatura a `evidencias` SEMPRE que existe instrumento vencedor (ela
    descreve ESTADO, não mudança); bastava outro campo mudar numa varredura
    seguinte para a frase antiga voltar à timeline. Devolve só as frases que
    ainda NÃO existem entre as observações automáticas já registradas do
    MESMO processo — comparação por CONTENÇÃO (não só igualdade exata),
    porque um `Acompanhamento` antigo pode ter gravado várias frases juntas
    (`" ".join(...)`, passo 4 abaixo) e uma frase repetida precisa ser
    reconhecida mesmo dentro desse texto combinado. UMA consulta por
    processo/proposta (`values_list` já materializado em lista), nunca uma
    consulta por frase; frases vazias ou repetidas dentro da própria lista
    nova também são descartadas."""
    textos_existentes = [
        _normalizar_frase(texto)
        for texto in processo.acompanhamentos.filter(
            tipo_evento=TipoEvento.AUTOMATICO
        ).values_list("situacao_informada", flat=True)
        if texto
    ]
    novas = []
    vistas = set()
    for frase in frases:
        chave = _normalizar_frase(frase)
        if not chave or chave in vistas:
            continue
        if any(chave in texto for texto in textos_existentes):
            continue
        vistas.add(chave)
        novas.append(frase)
    return novas


def aplicar(propostas, *, simular: bool = False, usuario=None, origem: str = "robo") -> dict:
    """Grava cada `Proposta` pelos serviços de `apps.pca.services` (§5).

    Fase 42 — `usuario=`/`origem=` são opcionais e 100%
    retrocompatíveis: nenhum chamador em produção
    (`sei_aplicar.py`/`sei_atender.py`/`sei_sincronizar.py`) passa os dois
    hoje, então o comportamento sem eles é IDÊNTICO a antes. Quando
    `simular=False` e `usuario` é passado (uma instância de `Usuario` real
    — o dono do token de API que chamou a extensão), ele substitui o
    usuário técnico como autor de `processo._history_user`, e `origem=
    "extensao"` troca o texto gravado no passo 3b (assinatura por ambas as
    partes) de `OBSERVACAO_ASSINATURA_POR_AMBOS` para
    `OBSERVACAO_ASSINATURA_POR_AMBOS_EXTENSAO` — nenhuma outra frase do
    módulo (evidências do passo 4, pendências do passo 6) muda por
    `origem`. `simular=True` continua gravando nada, mesmo com `usuario`
    passado (o kwarg é só ignorado nesse modo).

    Devolve o resumo consumido pelo plano para montar o JSON de
    execução do §6: `{"itens_alterados", "pendencias_novas",
    "eventos_gravados", "erros": [{"item", "mensagem"}], "alterados":
    [{"item", "campos"}], "pendencias": [{"item", "chave", "texto"}],
    "series": {"<exercicio>-<item_pca>": [...]}}` — `series` é a Fase 35; chave composta ano-item desde o Lote 6 do QA 30/09/2026
    (achado dados A3).
    """
    usuario_tecnico = None if simular else (usuario if usuario is not None else _usuario_tecnico())
    resumo = {
        "itens_alterados": 0,
        "pendencias_novas": 0,
        "eventos_gravados": 0,
        "erros": [],
        "alterados": [],
        "pendencias": [],
    }
    # (Fase 35): {"<exercicio>-<item_pca>": [...]}, montado a
    # partir de `Proposta.serie_valores` — só para itens com série não
    # vazia (chave ausente, não lista vazia). Nunca gravado no banco.
    resumo["series"] = {}
    estado = execucoes.carregar_estado_pendencias()
    estado_mudou = False

    for proposta in propostas:
        with transaction.atomic():
            processo = (
                Processo.objects.select_for_update()
                .filter(exercicio__ano=proposta.exercicio, item_pca=proposta.item_pca)
                .first()
            )
            if processo is None:
                resumo["erros"].append(
                    {"item": proposta.item_pca, "mensagem": "processo não encontrado"}
                )
                continue
            # /§4.4 — nunca toca item cancelado: nem alteracoes, nem
            # pendencias desta proposta são processadas.
            if processo.estado == Estado.CANCELADO:
                continue
            # Item sem nº SEI (A autuar / Não se aplica) nunca
            # é atualizado pela sincronização: não há de onde tirar
            # informação, e a sincronização não inventa — nem campos, nem
            # regra de situação, nem acompanhamento de pendência. O sinal é o
            # da própria coleta (`regras.propor`, passo 1: nenhum processo
            # coletado ⇒ pendência `sem_numero_sei`). Cadastrado o número,
            # volta a ser sincronizado na passada seguinte.
            if any(chave == "sem_numero_sei" for chave, _texto in proposta.pendencias):
                resumo["sem_numero_sei"] = resumo.get("sem_numero_sei", 0) + 1
                continue

            pendencias_da_proposta = list(proposta.pendencias)
            situacao_antes = processo.situacao
            eventos_antes = processo.acompanhamentos.count()

            # --- series: sempre preenchido, nos dois modos — só a
            # gravação no banco (abaixo) respeita `simular`, mesmo padrão de
            # `resumo["alterados"]`. Item cancelado nunca chega aqui (já
            # saiu no `continue` acima) — mesma semântica de
            # `alterados`/`pendencias`, cancelado nunca contribui pro resumo.
            if proposta.serie_valores:
                resumo["series"][
                    execucoes.chave_item(proposta.item_pca, proposta.exercicio)
                ] = proposta.serie_valores

            # --- passo 2: campos de alteracoes -------------------------
            if proposta.alteracoes:
                # `resumo["alterados"]` precisa listar os campos gravados
                # em AMBOS os modos — `sei_atender.py` lê
                # este resumo com `simular=False` para montar o JSON do
                # pedido atendido; só o `--simular` de `sei_aplicar` e o
                # `resumo["itens_alterados"]` distinguem os dois modos.
                resumo["alterados"].append(
                    {"item": proposta.item_pca, "campos": list(proposta.alteracoes.keys())}
                )
                if not simular:
                    processo._history_user = usuario_tecnico
                    for campo, (_antes, depois) in proposta.alteracoes.items():
                        _aplicar_campo(processo, campo, depois)
                    processo.save(update_fields=[*proposta.alteracoes.keys(), "atualizado_em"])

            # --- passo 3: aplicar_regras_automaticas, sempre ------------
            if not simular:
                aplicar_regras_automaticas(processo=processo, usuario=usuario_tecnico)
                # aplicar_regras_automaticas pode ter gravado um NOVO
                # Processo (via registrar_acompanhamento, outra instância) —
                # recarrega para que versao_cliente/situacao reflitam a
                # gravação mais recente antes do passo 4.
                processo.refresh_from_db()

            # --- passo 3b: exceção "assinado por ambos" (18/09/2026) ----
            # `aplicar_regras_automaticas` (passo 3) já teria concluído o
            # processo se não houvesse `transicao_manual` no histórico —
            # aqui FORÇAMOS a mesma conclusão quando o robô confirma que o
            # instrumento de contratação está assinado tanto pelo CFC
            # quanto pelo contratado, mesmo com a guarda ativa. Nunca em
            # `simular=True`. `processo.situacao != Situacao.CONCLUIDO`
            # torna este passo idempotente por construção: quando o passo 3
            # já concluiu (nenhuma transição manual bloqueando) ou uma
            # execução anterior já aplicou esta exceção, nada acontece de
            # novo — segunda aplicação continua produzindo zero eventos.
            # `estado == ATIVO` e `tipo.nome_normalizado != "vigente"`
            # preservam as guardas de cancelado e de vigente (já concluído
            # por natureza, sem depender de assinatura).
            assinado_conclui = (
                not simular
                and proposta.instrumento_assinado_por_ambos
                and processo.estado == Estado.ATIVO
                and processo.situacao != Situacao.CONCLUIDO
                and processo.tipo.nome_normalizado != "vigente"
                # "assinado por ambos" pode ser o contrato de
                # um ciclo passado: renovação no ano sem contrato/termo
                # aditivo do ano nunca conclui por aqui.
                and exigencia_de(processo)[0] != CONCLUSAO_BLOQUEADA
            )
            if assinado_conclui and processo.situacao_manual:
                # 29/09/2026 — trava manual (desmarcável só no Admin) vence até a assinatura: a
                # situação fica; o aviso do Início mostra que as regras concluiriam.
                atualizar_situacao_regra(processo, usuario_tecnico, alvo=Situacao.CONCLUIDO)
            elif assinado_conclui:
                processo = registrar_acompanhamento(
                    processo_id=processo.pk,
                    usuario=usuario_tecnico,
                    versao_cliente=processo.atualizado_em.isoformat(),
                    situacao_novo=Situacao.CONCLUIDO,
                    observacao=_OBSERVACOES_ASSINATURA_POR_AMBOS.get(
                        origem, OBSERVACAO_ASSINATURA_POR_AMBOS
                    ),
                    tipo_evento=TipoEvento.AUTOMATICO,
                    reuniao=None,
                    usar_reuniao_corrente=False,
                )

            # --- passo 4: evento de evidência ----------------------------
            if proposta.alteracoes:
                resumo["itens_alterados"] += 1
                if not simular:
                    # Filtra cada frase contra as
                    # observações automáticas já registradas no MESMO
                    # processo; sobrando zero frases novas, nada a
                    # comentar (o campo já foi gravado acima e já contou em
                    # `itens_alterados`, mas a linha repetida não nasce na
                    # timeline).
                    frases_novas = _frases_novas(processo, proposta.evidencias)
                    if frases_novas:
                        processo = registrar_acompanhamento(
                            processo_id=processo.pk,
                            usuario=usuario_tecnico,
                            versao_cliente=processo.atualizado_em.isoformat(),
                            observacao=" ".join(frases_novas),
                            tipo_evento=TipoEvento.AUTOMATICO,
                            reuniao=None,
                            usar_reuniao_corrente=False,
                            reafirmar_situacao=True,
                        )

                # --- passo 5: guarda de transicao_manual -----------------
                if (
                    _CAMPOS_GATILHO_TRANSICAO_MANUAL & proposta.alteracoes.keys()
                    and processo.situacao_manual
                    and processo.situacao == situacao_antes
                ):
                    pendencias_da_proposta.append(
                        (
                            "transicao_manual",
                            "Campos alterados; situação preservada por transição manual.",
                        )
                    )

            # --- passo 6: dedupe de pendências ---------------------------
            item_chave = execucoes.chave_item(proposta.item_pca, proposta.exercicio)
            chaves_existentes = set(estado.get(item_chave, []))
            chaves_da_proposta = {chave for chave, _texto in pendencias_da_proposta}

            for chave, texto in pendencias_da_proposta:
                resumo["pendencias"].append(
                    {"item": proposta.item_pca, "chave": chave, "texto": texto}
                )
                if chave in chaves_existentes:
                    continue
                frase_pendencia = f"Pendência SEI: {texto}"
                # Dedupe resistente a perda/zeragem de
                # `data/sei/estado.json`: mesmo sem a chave no arquivo, o
                # texto já registrado no processo é suficiente para não
                # regravar (o dedupe por arquivo acima continua sendo o
                # caminho normal, mais barato).
                if not _frases_novas(processo, [frase_pendencia]):
                    continue
                resumo["pendencias_novas"] += 1
                if not simular:
                    processo = registrar_acompanhamento(
                        processo_id=processo.pk,
                        usuario=usuario_tecnico,
                        versao_cliente=processo.atualizado_em.isoformat(),
                        observacao=frase_pendencia,
                        tipo_evento=TipoEvento.AUTOMATICO,
                        reuniao=None,
                        usar_reuniao_corrente=False,
                        reafirmar_situacao=True,
                    )

            # `eventos_gravados` conta TODOS os `Acompanhamento` novos deste
            # processo nesta proposta — inclusive o que `aplicar_regras_
            # automaticas` grava por conta própria quando muda `situacao`
            # (passo 3), não só os eventos que este módulo chama direto.
            if not simular:
                resumo["eventos_gravados"] += processo.acompanhamentos.count() - eventos_antes

            if not simular and chaves_da_proposta != chaves_existentes:
                if chaves_da_proposta:
                    estado[item_chave] = sorted(chaves_da_proposta)
                else:
                    estado.pop(item_chave, None)
                estado_mudou = True

    if not simular and estado_mudou:
        execucoes.gravar_estado_pendencias(estado)

    return resumo
