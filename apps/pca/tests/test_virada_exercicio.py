from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoExercicio,
    Tipo,
    Unidade,
)
from apps.pca.models import Processo, RascunhoItemVirada, RascunhoVirada, Situacao
from apps.pca.services import (
    DestinoJaExiste,
    NenhumItemSelecionado,
    confirmar_virada,
)


class TestViradaExercicio(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="gestor-virada@example.com", password="senha-segura"
        )
        self.origem, _ = Exercicio.objects.update_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.FECHADO},
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")
        self.grau = GrauPrioridade.objects.create(nome="Alta")
        self.classificacao = Classificacao.objects.create(nome="Prioritário")
        self.modalidade = Modalidade.objects.create(nome="Pregão")
        self.instrumento = InstrumentoContratual.objects.create(nome="Contrato")

    def processo(self, item, *, situacao=Situacao.NO_PRAZO, descricao=None):
        return Processo.objects.create(
            item_pca=item,
            exercicio=self.origem,
            descricao_objeto=descricao or f"Objeto {item}",
            justificativa="Justificativa do planejamento",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            valor_estimado=Decimal("100.00") + item,
            mes_previsto=3,
            data_inclusao_pca=date(2026, 1, 10),
            grau_prioridade=self.grau,
            classificacao=self.classificacao,
            data_envio_gelic=date(2026, 2, 1),
            data_recebimento_gelic=date(2026, 3, 1),
            data_prevista_conclusao=date(2026, 4, 1),
            # prazo_entrega é o dado de Planejamento copiado pela virada;
            # data_recebimento_gelic acima é fato consumado do exercício
            # de origem e nunca migra.
            prazo_entrega=date(2026, 5, 20),
            situacao=situacao,
        )

    def rascunho(self, *processos):
        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.origem,
            ano_destino=2027,
            criado_por=self.usuario,
        )
        RascunhoItemVirada.objects.bulk_create(
            [
                RascunhoItemVirada(
                    rascunho=rascunho,
                    processo_origem=processo,
                    ordem=processo.item_pca,
                    selecionado=True,
                    valor_estimado_editado=processo.valor_estimado,
                    mes_previsto_editado=processo.mes_previsto,
                )
                for processo in processos
            ]
        )
        return rascunho

    def test_draft_is_durable_and_pending_pair_is_unique_across_pages(self):
        processos = [self.processo(i) for i in range(1, 27)]
        rascunho = self.rascunho(*processos)

        page_two = list(rascunho.itens.order_by("ordem")[25:])
        page_two[0].selecionado = False
        page_two[0].valor_estimado_editado = Decimal("987.65")
        page_two[0].mes_previsto_editado = 12
        page_two[0].save(update_fields=[
            "selecionado", "valor_estimado_editado", "mes_previsto_editado",
        ])

        self.assertEqual(rascunho.itens.filter(selecionado=True).count(), 25)
        self.assertEqual(
            rascunho.itens.get(ordem=26).valor_estimado_editado,
            Decimal("987.65"),
        )
        with self.assertRaises(IntegrityError):
            RascunhoVirada.objects.create(
                exercicio_origem=self.origem,
                ano_destino=2027,
                criado_por=self.usuario,
            )

    def test_confirmation_creates_stable_sequence_and_audited_copies(self):
        concluido = self.processo(1, situacao=Situacao.CONCLUIDO)
        normal = self.processo(2, situacao=Situacao.EM_TRAMITACAO)
        vigente = self.processo(3, situacao=Situacao.CONCLUIDO)
        vigente.modalidade = self.modalidade
        vigente.vigencia_inicio = date(2026, 6, 1)
        vigente.vigencia_fim = date(2027, 5, 31)
        vigente.numero_contratacao = "12/2026"
        vigente.numero_arp = "ARP-7"
        vigente.instrumento_contratual = self.instrumento
        vigente.numero_instrumento_contratual = "CT-9"
        vigente.valor_contratado = Decimal("1234.56")
        vigente.fornecedor_cnpj = "04.252.011/0001-10"
        vigente.fornecedor_razao_social = "Fornecedor Ltda"
        vigente.data_assinatura_contrato = date(2026, 6, 2)
        vigente.data_lancamento_spw = date(2026, 6, 3)
        vigente.data_lancamento_wordpress = date(2026, 6, 4)
        vigente.data_lancamento_dados_abertos = date(2026, 6, 5)
        vigente.save()
        rascunho = self.rascunho(vigente, concluido, normal)

        destino = confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)

        copies = list(Processo.objects.filter(exercicio=destino).order_by("item_pca"))
        self.assertEqual([p.item_pca for p in copies], [1, 2, 3])
        self.assertEqual([p.origem_id for p in copies], [concluido.pk, normal.pk, vigente.pk])
        self.assertEqual(copies[1].situacao, Situacao.NO_PRAZO)
        self.assertEqual(copies[2].situacao, Situacao.CONCLUIDO)
        self.assertEqual(copies[2].valor_contratado, vigente.valor_contratado)
        self.assertEqual(copies[2].data_lancamento_spw, vigente.data_lancamento_spw)
        self.assertEqual(copies[2].data_lancamento_wordpress, vigente.data_lancamento_wordpress)
        self.assertEqual(copies[2].data_lancamento_dados_abertos, vigente.data_lancamento_dados_abertos)
        self.assertIsNone(copies[1].data_envio_gelic)
        self.assertIsNone(copies[1].data_prevista_conclusao)
        self.assertEqual(
            copies[1].history.filter(
                history_user=self.usuario,
                history_change_reason="Virada 2026/2027",
            ).count(),
            1,
        )
        self.assertEqual(
            copies[0].history.filter(
                history_user=self.usuario,
                history_change_reason="Virada 2026/2027",
            ).count(),
            1,
        )
        self.assertIsNotNone(RascunhoVirada.objects.get(pk=rascunho.pk).confirmado_em)
        self.assertGreaterEqual(timezone.now(), rascunho.criado_em)

    def test_a_renovar_copia_como_vigente_preservando_execucao_contratual(self):
        # O valor `a_renovar` saiu do enum `Status`; o que a Renovação
        # com contrato assinado equivale hoje é `situacao=CONCLUIDO`
        # (mesma regra de `situacao_por_eventos` para Nova Contratação e
        # Renovação). O teste preserva a regressão: um processo concluído
        # (execução contratual preenchida) na origem tem que chegar
        # concluído no destino, com a execução preservada — nunca
        # resetar para NO_PRAZO.
        a_renovar = self.processo(3, situacao=Situacao.CONCLUIDO)
        a_renovar.modalidade = self.modalidade
        a_renovar.vigencia_inicio = date(2026, 1, 1)
        a_renovar.vigencia_fim = date(2026, 12, 31)
        a_renovar.numero_contratacao = "13/2026"
        a_renovar.instrumento_contratual = self.instrumento
        a_renovar.valor_contratado = Decimal("2345.67")
        a_renovar.fornecedor_cnpj = "04.252.011/0001-10"
        a_renovar.fornecedor_razao_social = "Fornecedor A Renovar Ltda"
        a_renovar.data_assinatura_contrato = date(2026, 1, 2)
        a_renovar.save()
        rascunho = self.rascunho(a_renovar)

        destino = confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)

        copia = Processo.objects.get(exercicio=destino, origem=a_renovar)
        self.assertEqual(copia.situacao, Situacao.CONCLUIDO)
        self.assertEqual(copia.valor_contratado, a_renovar.valor_contratado)
        self.assertEqual(copia.vigencia_fim, a_renovar.vigencia_fim)
        self.assertEqual(copia.fornecedor_razao_social, a_renovar.fornecedor_razao_social)

    def test_virada_copia_prazo_planejado_e_nao_carrega_fatos_processuais(self):
        # A virada copia o dado de Planejamento (`prazo_entrega`), nunca
        # os fatos processuais do exercício de origem
        # (`data_recebimento_gelic`, `data_envio_gelic`,
        # `data_prevista_conclusao`), que ficam explicitamente zerados no
        # destino.
        origem = self.processo(1)
        rascunho = self.rascunho(origem)

        destino = confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)

        copia = Processo.objects.get(exercicio=destino, origem=origem)
        self.assertEqual(copia.prazo_entrega, origem.prazo_entrega)
        self.assertIsNotNone(copia.prazo_entrega)
        self.assertIsNone(copia.data_recebimento_gelic)
        self.assertIsNone(copia.data_envio_gelic)
        self.assertIsNone(copia.data_prevista_conclusao)

    def test_empty_selection_and_failure_roll_back_destination(self):
        processo = self.processo(1)
        rascunho = self.rascunho(processo)
        RascunhoItemVirada.objects.filter(rascunho=rascunho).update(selecionado=False)
        with self.assertRaises(NenhumItemSelecionado):
            confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)
        self.assertFalse(Exercicio.objects.filter(ano=2027).exists())

        RascunhoItemVirada.objects.filter(rascunho=rascunho).update(selecionado=True)
        with patch("apps.pca.services.bulk_create_with_history", side_effect=RuntimeError("falha")):
            with self.assertRaises(RuntimeError):
                confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)
        self.assertFalse(Exercicio.objects.filter(ano=2027).exists())
        self.assertFalse(Processo.objects.filter(exercicio__ano=2027).exists())

    def test_existing_destination_and_repeated_confirmation_are_controlled(self):
        processo = self.processo(1)
        rascunho = self.rascunho(processo)
        Exercicio.objects.create(ano=2027, rotulo="PCA 2027")
        with self.assertRaises(DestinoJaExiste):
            confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)
        Exercicio.objects.filter(ano=2027).delete()

        confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)
        with self.assertRaises(DestinoJaExiste):
            confirmar_virada(rascunho_id=rascunho.pk, usuario=self.usuario)


class TestViradaEndpoints(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            email="manager-endpoint@example.com", password="senha-segura"
        )
        self.editor = get_user_model().objects.create_user(
            email="editor-endpoint@example.com", password="senha-segura"
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="gerir_exercicio")
        )
        self.origem, _ = Exercicio.objects.update_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO},
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")
        for item in range(1, 27):
            Processo.objects.create(
                item_pca=item,
                exercicio=self.origem,
                descricao_objeto=f"Objeto {item}",
                justificativa="Planejamento",
                tipo=self.tipo,
                categoria=self.categoria,
                unidade_organizacional=self.unidade,
                valor_estimado=Decimal("100.00"),
                mes_previsto=3,
            )
        self.client = Client()

    def test_editor_is_denied_every_turnover_mutation_and_sees_no_control(self):
        # Rotas do wizard de 3 etapas: `virada`/`virada_ajustar`/
        # `virada_revisar`/`virada_confirmar_descarte`.
        self.client.force_login(self.editor)
        urls = (
            reverse("pca:virada", args=[2027]),
            reverse("pca:virada_ajustar", args=[2027]),
            reverse("pca:virada_revisar", args=[2027]),
            reverse("pca:virada_confirmar_descarte", args=[2027]),
            reverse("pca:virada_descartar", args=[2027]),
            reverse("pca:virada_confirmacao", args=[2027]),
            reverse("pca:virada_confirmar", args=[2027]),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url).status_code, 403)
        resposta = self.client.get(reverse("raiz"))
        self.assertNotContains(resposta, "Gerenciar exercícios")

    def test_manager_get_is_paginated(self):
        self.client.force_login(self.manager)
        pagina = self.client.get(reverse("pca:virada", args=[2027]))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "0 de 26 itens selecionados")
        self.assertContains(pagina, 'aria-label="Selecionar item 1"')
        self.assertNotContains(pagina, 'aria-label="Selecionar item 26"')
        self.assertContains(
            self.client.get(reverse("pca:virada", args=[2027]) + "?pagina=2"),
            "Objeto 26",
        )

    def test_selecionar_marca_pagina_inteira_e_avancar_persiste_e_redireciona(self):
        # Um único POST cobre a página inteira: `item_pagina` (hidden,
        # todos os ids renderizados) versus `selecionados` (só os
        # marcados) marca/desmarca em lote. `acao=avancar` persiste e
        # redireciona para a etapa 2.
        self.client.force_login(self.manager)
        pagina1 = self.client.get(reverse("pca:virada", args=[2027]))
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.assertEqual(pagina1.context["pagina"].paginator.count, 26)

        resposta = self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1", "2"],
                "acao": "avancar",
            },
        )
        self.assertRedirects(
            resposta, reverse("pca:virada_ajustar", args=[2027])
        )
        selecionados = set(
            RascunhoItemVirada.objects.filter(
                rascunho__ano_destino=2027, selecionado=True
            ).values_list("processo_origem__item_pca", flat=True)
        )
        self.assertEqual(selecionados, {1, 2})

    def test_selecionar_aplicar_mantem_na_etapa_1_e_permite_desmarcar(self):
        self.client.force_login(self.manager)
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1"],
                "acao": "aplicar",
            },
        )
        item = RascunhoItemVirada.objects.get(
            rascunho__ano_destino=2027, processo_origem__item_pca=1
        )
        self.assertTrue(item.selecionado)

        resposta = self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": [],
                "acao": "aplicar",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.selecionado)

    def test_ajustar_lista_so_selecionados_e_editar_atualiza_mes_e_valor(self):
        self.client.force_login(self.manager)
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1"],
                "acao": "aplicar",
            },
        )

        ajustar = self.client.get(reverse("pca:virada_ajustar", args=[2027]))
        self.assertContains(ajustar, "Objeto 1", count=1)
        self.assertNotContains(ajustar, "Objeto 2")

        resposta = self.client.post(
            reverse("pca:virada_item_editar", args=[2027, 1]),
            {"mes_previsto_editado": "5", "valor_estimado_editado": "987,65"},
        )
        self.assertRedirects(
            resposta, reverse("pca:virada_ajustar", args=[2027])
        )
        item = RascunhoItemVirada.objects.get(
            rascunho__ano_destino=2027, processo_origem__item_pca=1
        )
        self.assertEqual(item.mes_previsto_editado, 5)
        self.assertEqual(item.valor_estimado_editado, Decimal("987.65"))

    def test_item_editar_com_valor_invalido_devolve_200_com_erro(self):
        self.client.force_login(self.manager)
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1"],
                "acao": "aplicar",
            },
        )
        resposta = self.client.post(
            reverse("pca:virada_item_editar", args=[2027, 1]),
            {"mes_previsto_editado": "", "valor_estimado_editado": "não é número"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Informe um valor monetário válido.")

    def test_ajustar_avancar_e_post_e_leva_a_revisar(self):
        self.client.force_login(self.manager)
        resposta = self.client.post(reverse("pca:virada_ajustar", args=[2027]))
        self.assertRedirects(resposta, reverse("pca:virada_revisar", args=[2027]))

    def test_revisar_mostra_totais_e_concluir_confirma_a_virada(self):
        self.client.force_login(self.manager)
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1", "2"],
                "acao": "aplicar",
            },
        )

        revisar = self.client.get(reverse("pca:virada_revisar", args=[2027]))
        self.assertEqual(revisar.status_code, 200)
        self.assertContains(revisar, "Objeto 1")
        self.assertContains(revisar, "Objeto 2")
        self.assertEqual(revisar.context["total_selecionados"], 2)

        # Rota histórica: continua resolvendo, redirecionando para a etapa 3.
        confirmacao = self.client.get(reverse("pca:virada_confirmacao", args=[2027]))
        self.assertRedirects(confirmacao, reverse("pca:virada_revisar", args=[2027]))

        resposta = self.client.post(reverse("pca:virada_confirmar", args=[2027]))
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Exercicio.objects.filter(ano=2027).exists())
        self.assertEqual(
            Processo.objects.filter(exercicio__ano=2027).count(), 2
        )

    def test_confirmar_descarte_pagina_e_post_real_zera_selecao(self):
        self.client.force_login(self.manager)
        ids_pagina1 = [str(n) for n in range(1, 26)]
        self.client.post(
            reverse("pca:virada", args=[2027]),
            {
                "pagina": "1",
                "item_pagina": ids_pagina1,
                "selecionados": ["1"],
                "acao": "aplicar",
            },
        )
        pagina_confirmar = self.client.get(
            reverse("pca:virada_confirmar_descarte", args=[2027])
        )
        self.assertEqual(pagina_confirmar.status_code, 200)
        self.assertContains(pagina_confirmar, "br-message warning")
        self.assertContains(pagina_confirmar, "Descartar rascunho")

        resposta = self.client.post(reverse("pca:virada_descartar", args=[2027]))
        self.assertRedirects(resposta, reverse("pca:virada", args=[2027]))
        self.assertEqual(
            RascunhoItemVirada.objects.filter(
                rascunho__ano_destino=2027, selecionado=True
            ).count(),
            0,
        )
