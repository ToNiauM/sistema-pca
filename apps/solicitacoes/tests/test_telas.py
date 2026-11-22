"""Telas das Solicitações (Fase 43) — nas duas cascas.

Tudo por `django.test.Client` (`force_login`, `HTTP_X_FORWARDED_PROTO="https"`, POST real, PRG): permissões
(solicitante só pede na sua unidade; visualizador não vê "Para avaliar"; cada alçada decide só a sua), o fluxo
completo (pedir → decidir → desistir), a fila, o menu, o contador do Início e a ficha do item. A mesma bateria
roda com a casca DSGov (padrão) e com a Tabler (`override_settings` como em `core/tests/test_casca_tabler.py`).
"""

from datetime import date, timedelta
from html.parser import HTMLParser

from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils.timezone import now

from apps.pca.models import Processo
from apps.solicitacoes.models import ParteSolicitacao, Solicitacao
from apps.solicitacoes.regras import Campo, EstadoParte, EstadoSolicitacao
from core.tests.test_casca_tabler import CASCA_TABLER

from .base import CenarioBase

HTTPS = {"HTTP_X_FORWARDED_PROTO": "https"}


class _Estrutura(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.primarios = 0

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "h1":
            self.h1 += 1
        if tag in ("a", "button") and (
            ("br-button" in classes and "primary" in classes) or "btn-primary" in classes
        ):
            self.primarios += 1


class TelasMixin:
    """Os testes; as duas classes concretas abaixo só escolhem a casca."""

    casca = "dsgov"

    # --- utilidades ---------------------------------------------------------------------

    def get(self, usuario, url, **extra):
        self.client.force_login(usuario)
        return self.client.get(url, **HTTPS, **extra)

    def post(self, usuario, url, dados=None):
        self.client.force_login(usuario)
        return self.client.post(url, dados or {}, **HTTPS)

    def html(self, resposta):
        return resposta.content.decode()

    def mensagens(self, resposta):
        return [str(m) for m in get_messages(resposta.wsgi_request)]

    def pedir(self, usuario=None, item=None, **campos):
        dados = {"justificativa": "Motivo do pedido.", **campos}
        item = item or self.item
        url = f"{reverse('solicitacoes:nova')}?processo={item.exercicio.ano}/{item.item_pca}"
        return self.post(usuario or self.solicitante, url, dados), url

    def criar(self, **campos):
        resposta, _ = self.pedir(**campos)
        self.assertEqual(resposta.status_code, 302, self.html(resposta)[-3000:] if resposta.status_code == 200 else "")
        return Solicitacao.objects.order_by("-id").first()

    def parte(self, solicitacao, campo):
        return solicitacao.partes.get(campo=campo)

    def url_decidir(self, solicitacao, parte):
        return reverse("solicitacoes:decidir", args=[solicitacao.ano, solicitacao.numero, parte.pk])

    def url_detalhe(self, solicitacao):
        return reverse("solicitacoes:detalhe", args=[solicitacao.ano, solicitacao.numero])

    def confere_casca(self, html):
        if self.casca == "tabler":
            self.assertIn("tabler/vendor/tabler.min.css", html)
            self.assertNotIn("dsgov", html.lower())
        else:
            self.assertIn("dsgov", html.lower())
            self.assertNotIn("tabler/vendor/tabler.min.css", html)

    # --- acesso -------------------------------------------------------------------------

    def test_anonimo_vai_para_o_login(self):
        for nome in ("nova", "minhas", "avaliar"):
            resposta = self.client.get(reverse(f"solicitacoes:{nome}"), **HTTPS)
            self.assertEqual(resposta.status_code, 302, nome)
            self.assertIn("login", resposta["Location"], nome)

    def test_visualizador_nao_ve_nada_de_solicitacoes(self):
        for nome in ("nova", "minhas", "avaliar"):
            self.assertEqual(self.get(self.visualizador, reverse(f"solicitacoes:{nome}")).status_code, 403, nome)
        inicio = self.html(self.get(self.visualizador, reverse("core:inicio")))
        self.assertNotIn("Para avaliar", inicio)
        self.assertNotIn("Nova solicitação", inicio)

    def test_solicitante_pede_mas_nao_avalia(self):
        self.assertEqual(self.get(self.solicitante, reverse("solicitacoes:nova")).status_code, 200)
        self.assertEqual(self.get(self.solicitante, reverse("solicitacoes:minhas")).status_code, 200)
        self.assertEqual(self.get(self.solicitante, reverse("solicitacoes:avaliar")).status_code, 403)

    def test_equipe_avalia_mas_nao_pede(self):
        self.assertEqual(self.get(self.equipe, reverse("solicitacoes:avaliar")).status_code, 200)
        self.assertEqual(self.get(self.equipe, reverse("solicitacoes:minhas")).status_code, 200)
        self.assertEqual(self.get(self.equipe, reverse("solicitacoes:nova")).status_code, 403)

    def test_item_de_outra_unidade_e_item_inexistente(self):
        outro = self.novo_item(40, unidade=self.outra_unidade)
        url = f"{reverse('solicitacoes:nova')}?processo={outro.exercicio.ano}/{outro.item_pca}"
        self.assertEqual(self.get(self.solicitante, url).status_code, 403)
        self.assertEqual(self.get(self.solicitante, f"{reverse('solicitacoes:nova')}?processo={self.ano}/9999").status_code, 404)
        self.assertEqual(self.get(self.solicitante, f"{reverse('solicitacoes:nova')}?processo=abc").status_code, 404)

    def test_usuario_sem_vinculo_recebe_aviso(self):
        resposta = self.get(self.sem_vinculo, reverse("solicitacoes:nova"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("não está vinculado a nenhuma unidade", self.html(resposta))

    # --- nova solicitação ---------------------------------------------------------------

    def test_passo_1_lista_so_os_itens_das_unidades_do_usuario(self):
        self.novo_item(41, unidade=self.outra_unidade, descricao_objeto="Objeto exclusivo da outra unidade")
        html = self.html(self.get(self.solicitante, reverse("solicitacoes:nova")))
        self.confere_casca(html)
        self.assertIn(f"{self.ano}/{self.item.item_pca}", html)
        self.assertIn("Objeto do item 1", html)
        self.assertNotIn("Objeto exclusivo da outra unidade", html)

    def test_passo_2_mostra_resumo_linhas_e_quem_decide(self):
        url = f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item.item_pca}"
        html = self.html(self.get(self.solicitante, url))
        self.confere_casca(html)
        self.assertIn("Objeto do item 1", html)
        for texto in ("Novo prazo de entrega", "Novo mês previsto", "Novo valor estimado", "Novo objeto",
                      "Pedir o cancelamento do item", "Justificativa", "Equipe do PCA", "Diretoria"):
            self.assertIn(texto, html, texto)
        self.assertIn("15/12/", html)  # o prazo de hoje

    def test_item_em_tramitacao_nao_oferece_prazo_nem_mes(self):
        url = f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item_tramitacao.item_pca}"
        html = self.html(self.get(self.solicitante, url))
        self.assertNotIn("Novo prazo de entrega", html)
        self.assertNotIn("Novo mês previsto", html)
        self.assertIn("Novo valor estimado", html)

    def test_pedido_de_prazo_e_valor_vira_duas_partes_e_prg(self):
        resposta, _ = self.pedir(prazo_entrega="2027-01-10", valor_estimado="2.000,50")
        solicitacao = Solicitacao.objects.get()
        self.assertRedirects(resposta, self.url_detalhe(solicitacao), fetch_redirect_response=False)
        self.assertEqual(solicitacao.solicitante, self.solicitante)
        self.assertEqual(solicitacao.unidade, self.unidade)
        partes = {p.campo: p for p in solicitacao.partes.all()}
        self.assertEqual(set(partes), {Campo.PRAZO_ENTREGA, Campo.VALOR_ESTIMADO})
        self.assertEqual(partes[Campo.PRAZO_ENTREGA].alcada, "equipe")
        self.assertEqual(partes[Campo.VALOR_ESTIMADO].alcada, "diretoria")
        self.assertEqual(partes[Campo.VALOR_ESTIMADO].valor_pedido, "2000.50")
        self.assertTrue(partes[Campo.PRAZO_ENTREGA].fora_do_exercicio)
        self.assertTrue(any("enviada" in m for m in self.mensagens(resposta)))
        self.assertEqual(self.get(self.solicitante, self.url_detalhe(solicitacao)).status_code, 200)

    def test_cancelamento_e_exclusivo(self):
        resposta, _ = self.pedir(cancelamento="on", prazo_entrega="2027-01-10")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("pedido sozinho", self.html(resposta))
        self.assertFalse(Solicitacao.objects.exists())
        solicitacao = self.criar(cancelamento="on")
        self.assertEqual(solicitacao.tipo, "cancelamento")
        self.assertEqual([p.campo for p in solicitacao.partes.all()], [Campo.CANCELAMENTO])

    def test_pedido_vazio_ou_sem_justificativa_nao_grava(self):
        resposta, _ = self.pedir()
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Preencha ao menos um campo", self.html(resposta))
        resposta, _ = self.pedir(prazo_entrega="2027-01-10", justificativa="")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Informe a justificativa", self.html(resposta))
        self.assertFalse(Solicitacao.objects.exists())

    def test_pedido_igual_ao_atual_e_repetido_voltam_com_erro(self):
        resposta, _ = self.pedir(valor_estimado="1.000,00")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("igual ao atual", self.html(resposta))
        self.criar(mes_previsto="9")
        url = f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item.item_pca}"
        html = self.html(self.get(self.solicitante, url))
        self.assertIn("Já há pedido em análise para", html)
        self.assertNotIn("Novo mês previsto", html)
        self.assertIn("Novo prazo de entrega", html)

    def test_item_concluido_nao_aceita_pedido_e_explica(self):
        concluido = self.novo_item(51, situacao="concluido")
        url = f"{reverse('solicitacoes:nova')}?processo={self.ano}/{concluido.item_pca}"
        html = self.html(self.get(self.solicitante, url))
        self.assertIn("Este item não aceita pedidos", html)
        self.assertIn("O item está concluído", html)
        self.assertNotIn("Novo valor estimado", html)
        # E o POST direto também não grava nada.
        resposta = self.post(self.solicitante, url, {"justificativa": "J", "valor_estimado": "2.000,00"})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Solicitacao.objects.exists())

    def test_cancelamento_em_analise_bloqueia_o_item(self):
        self.criar(cancelamento="on")
        url = f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item.item_pca}"
        html = self.html(self.get(self.solicitante, url))
        self.assertIn("pedido de cancelamento em análise", html)
        self.assertNotIn("Novo prazo de entrega", html)

    def test_solicitante_nao_pede_em_item_de_outra_unidade(self):
        outro = self.novo_item(42, unidade=self.outra_unidade)
        resposta, _ = self.pedir(item=outro, prazo_entrega="2027-01-10")
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Solicitacao.objects.exists())

    def test_inclusao_de_item_novo(self):
        url = f"{reverse('solicitacoes:nova')}?tipo=inclusao"
        html = self.html(self.get(self.solicitante, url))
        self.confere_casca(html)
        for texto in ("Objeto", "Tipo", "Categoria", "Valor estimado", "Mês previsto", "Prazo de entrega", "Justificativa"):
            self.assertIn(texto, html, texto)
        dados = {
            "unidade": str(self.unidade.pk), "descricao_objeto": "Contratação de serviço novo",
            "tipo": str(self.tipo_nova.pk), "categoria": str(self.categoria.pk),
            "valor_estimado": "10.000,00", "mes_previsto": "8", "prazo_entrega": "",
            "justificativa": "Demanda nova da unidade.", "numero_sei": "00000.000001/2026-11",
        }
        resposta = self.post(self.solicitante, url, dados)
        solicitacao = Solicitacao.objects.get()
        self.assertRedirects(resposta, self.url_detalhe(solicitacao), fetch_redirect_response=False)
        self.assertEqual(solicitacao.tipo, "inclusao")
        self.assertIsNone(solicitacao.processo)
        self.assertEqual(solicitacao.dados_inclusao["valor_estimado"], "10000.00")
        # O item só nasce na aprovação.
        self.assertFalse(Processo.objects.filter(descricao_objeto="Contratação de serviço novo").exists())
        # Unidade que não é do solicitante: opção inválida.
        dados["unidade"] = str(self.outra_unidade.pk)
        resposta = self.post(self.solicitante, url, dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Solicitacao.objects.count(), 1)

    def test_inclusao_com_tipo_vigente_e_recusada(self):
        url = f"{reverse('solicitacoes:nova')}?tipo=inclusao"
        dados = {
            "unidade": str(self.unidade.pk), "descricao_objeto": "X", "tipo": str(self.tipo_vigente.pk),
            "categoria": str(self.categoria.pk), "valor_estimado": "10,00", "mes_previsto": "8",
            "justificativa": "J",
        }
        self.assertEqual(self.post(self.solicitante, url, dados).status_code, 200)
        self.assertFalse(Solicitacao.objects.exists())

    # --- detalhe e visibilidade -----------------------------------------------------------

    def test_visibilidade_do_detalhe(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10")
        url = self.url_detalhe(solicitacao)
        for quem in (self.solicitante, self.colega, self.equipe, self.diretoria, self.admin):
            self.assertEqual(self.get(quem, url).status_code, 200, quem.email)
        for quem in (self.solicitante_b, self.sem_vinculo, self.visualizador):
            self.assertEqual(self.get(quem, url).status_code, 404, quem.email)

    def test_detalhe_mostra_decisao_so_nas_partes_da_alcada(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        prazo, valor = self.parte(solicitacao, Campo.PRAZO_ENTREGA), self.parte(solicitacao, Campo.VALOR_ESTIMADO)
        url = self.url_detalhe(solicitacao)
        equipe = self.html(self.get(self.equipe, url))
        self.confere_casca(equipe)
        self.assertIn(self.url_decidir(solicitacao, prazo), equipe)
        self.assertNotIn(self.url_decidir(solicitacao, valor), equipe)
        self.assertIn("Aguardando diretoria", equipe)
        diretoria = self.html(self.get(self.diretoria, url))
        self.assertIn(self.url_decidir(solicitacao, valor), diretoria)
        self.assertNotIn(self.url_decidir(solicitacao, prazo), diretoria)
        ambos = self.html(self.get(self.ambos, url))
        self.assertIn(self.url_decidir(solicitacao, prazo), ambos)
        self.assertIn(self.url_decidir(solicitacao, valor), ambos)
        # A unidade só lê.
        unidade = self.html(self.get(self.solicitante, url))
        self.assertNotIn("/decidir", unidade)
        self.assertIn("Aguardando equipe do pca", unidade)
        self.assertIn("Aguardando diretoria", unidade)

    # --- decisão --------------------------------------------------------------------------

    def test_equipe_aprova_o_prazo_e_vale_na_hora(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        prazo = self.parte(solicitacao, Campo.PRAZO_ENTREGA)
        resposta = self.post(self.equipe, self.url_decidir(solicitacao, prazo), {f"parte{prazo.pk}-decisao": "aprovar"})
        self.assertRedirects(resposta, self.url_detalhe(solicitacao), fetch_redirect_response=False)
        prazo.refresh_from_db()
        self.assertEqual(prazo.estado, EstadoParte.APROVADA)
        self.assertEqual(prazo.decidido_por, self.equipe)
        item = Processo.objects.para_listagem().get(pk=self.item.pk)
        self.assertEqual(item.prazo_efetivo, date(2027, 1, 10))
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.PENDENTE)  # a parte do valor segue pendente
        self.assertTrue(any("decisão registrada" in m for m in self.mensagens(resposta)))

    def test_cada_um_decide_so_a_sua_alcada(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        prazo, valor = self.parte(solicitacao, Campo.PRAZO_ENTREGA), self.parte(solicitacao, Campo.VALOR_ESTIMADO)
        self.assertEqual(
            self.post(self.diretoria, self.url_decidir(solicitacao, prazo), {f"parte{prazo.pk}-decisao": "aprovar"}).status_code, 403
        )
        self.assertEqual(
            self.post(self.equipe, self.url_decidir(solicitacao, valor), {f"parte{valor.pk}-decisao": "aprovar"}).status_code, 403
        )
        self.assertEqual(
            self.post(self.solicitante, self.url_decidir(solicitacao, prazo), {f"parte{prazo.pk}-decisao": "aprovar"}).status_code, 403
        )
        self.assertEqual(
            self.post(self.solicitante_b, self.url_decidir(solicitacao, prazo), {f"parte{prazo.pk}-decisao": "aprovar"}).status_code, 404
        )
        self.assertEqual(
            ParteSolicitacao.objects.filter(estado=EstadoParte.PENDENTE).count(), 2
        )
        # Quem está nos dois decide tudo; a solicitação fecha com a última parte.
        for parte in (prazo, valor):
            self.post(self.ambos, self.url_decidir(solicitacao, parte), {f"parte{parte.pk}-decisao": "aprovar"})
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)
        self.item.refresh_from_db()
        self.assertEqual(str(self.item.valor_estimado), "2000.00")

    def test_ajuste_e_recusa_exigem_motivo(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10")
        prazo = self.parte(solicitacao, Campo.PRAZO_ENTREGA)
        url, p = self.url_decidir(solicitacao, prazo), f"parte{prazo.pk}-"
        resposta = self.post(self.equipe, url, {p + "decisao": "ajuste", p + "valor_ajuste": "2026-12-20"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Informe o motivo", self.html(resposta))
        resposta = self.post(self.equipe, url, {p + "decisao": "recusar"})
        self.assertIn("Informe o motivo", self.html(resposta))
        resposta = self.post(self.equipe, url, {p + "decisao": "ajuste", p + "motivo": "Sem data."})
        self.assertEqual(resposta.status_code, 200)
        prazo.refresh_from_db()
        self.assertEqual(prazo.estado, EstadoParte.PENDENTE)
        resposta = self.post(
            self.equipe, url, {p + "decisao": "ajuste", p + "valor_ajuste": "2026-12-20", p + "motivo": "Só até 20/12."}
        )
        self.assertEqual(resposta.status_code, 302)
        prazo.refresh_from_db()
        self.assertEqual(prazo.estado, EstadoParte.APROVADA_AJUSTE)
        self.assertEqual(prazo.valor_concedido, "2026-12-20")
        self.assertEqual(prazo.motivo, "Só até 20/12.")
        item = Processo.objects.para_listagem().get(pk=self.item.pk)
        self.assertEqual(item.prazo_efetivo, date(2026, 12, 20))
        # A unidade vê o motivo e o concedido.
        html = self.html(self.get(self.solicitante, self.url_detalhe(solicitacao)))
        self.assertIn("Só até 20/12.", html)
        self.assertIn("20/12/2026", html)

    def test_recusa_nao_altera_o_item(self):
        solicitacao = self.criar(valor_estimado="2.000,00")
        valor = self.parte(solicitacao, Campo.VALOR_ESTIMADO)
        resposta = self.post(
            self.diretoria, self.url_decidir(solicitacao, valor),
            {f"parte{valor.pk}-decisao": "recusar", f"parte{valor.pk}-motivo": "Sem dotação."},
        )
        self.assertEqual(resposta.status_code, 302)
        valor.refresh_from_db()
        self.assertEqual(valor.estado, EstadoParte.RECUSADA)
        self.item.refresh_from_db()
        self.assertEqual(str(self.item.valor_estimado), "1000.00")
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)

    def test_decidir_so_aceita_post_e_parte_ja_decidida_avisa(self):
        solicitacao = self.criar(mes_previsto="9")
        parte = self.parte(solicitacao, Campo.MES_PREVISTO)
        self.assertEqual(self.get(self.equipe, self.url_decidir(solicitacao, parte)).status_code, 405)
        corpo = {f"parte{parte.pk}-decisao": "aprovar"}
        self.post(self.equipe, self.url_decidir(solicitacao, parte), corpo)
        resposta = self.post(self.equipe, self.url_decidir(solicitacao, parte), corpo)
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(any("já foi decidida" in m for m in self.mensagens(resposta)))
        self.item.refresh_from_db()
        self.assertEqual(self.item.mes_previsto, 9)

    def test_aprovar_cancelamento_cancela_o_item(self):
        solicitacao = self.criar(cancelamento="on")
        parte = self.parte(solicitacao, Campo.CANCELAMENTO)
        self.post(self.diretoria, self.url_decidir(solicitacao, parte), {f"parte{parte.pk}-decisao": "aprovar"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.estado, "cancelado")

    def test_aprovar_inclusao_cria_o_item_com_o_proximo_numero(self):
        url = f"{reverse('solicitacoes:nova')}?tipo=inclusao"
        self.post(self.solicitante, url, {
            "unidade": str(self.unidade.pk), "descricao_objeto": "Serviço novo", "tipo": str(self.tipo_nova.pk),
            "categoria": str(self.categoria.pk), "valor_estimado": "5.000,00", "mes_previsto": "7",
            "justificativa": "Preciso.",
        })
        solicitacao = Solicitacao.objects.get()
        parte = self.parte(solicitacao, Campo.INCLUSAO)
        self.post(self.diretoria, self.url_decidir(solicitacao, parte), {f"parte{parte.pk}-decisao": "aprovar"})
        solicitacao.refresh_from_db()
        self.assertIsNotNone(solicitacao.processo)
        self.assertEqual(solicitacao.processo.item_pca, 4)
        self.assertEqual(solicitacao.processo.unidade_organizacional, self.unidade)
        self.assertEqual(str(solicitacao.processo.valor_estimado), "5000.00")

    # --- desistir -------------------------------------------------------------------------

    def test_a_unidade_desiste_e_so_por_post(self):
        solicitacao = self.criar(mes_previsto="9")
        url = reverse("solicitacoes:desistir", args=[solicitacao.ano, solicitacao.numero])
        self.assertEqual(self.get(self.solicitante, url).status_code, 405)
        self.assertEqual(self.post(self.solicitante_b, url).status_code, 404)
        self.assertEqual(self.post(self.equipe, url).status_code, 403)
        resposta = self.post(self.colega, url)
        self.assertRedirects(resposta, self.url_detalhe(solicitacao), fetch_redirect_response=False)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.DESISTIDA)
        self.assertEqual(self.parte(solicitacao, Campo.MES_PREVISTO).estado, EstadoParte.DESISTIDA)
        # Já encerrada: avisa, não quebra.
        self.assertTrue(any("já foi encerrada" in m for m in self.mensagens(self.post(self.solicitante, url))))
        # E pode pedir de novo.
        self.assertEqual(self.pedir(mes_previsto="10")[0].status_code, 302)

    def test_minhas_mostra_desistir_so_nas_pendentes_da_unidade(self):
        pendente = self.criar(mes_previsto="9")
        decidida = self.criar(prazo_entrega="2027-01-10")
        parte = self.parte(decidida, Campo.PRAZO_ENTREGA)
        self.post(self.equipe, self.url_decidir(decidida, parte), {f"parte{parte.pk}-decisao": "aprovar"})
        html = self.html(self.get(self.solicitante, reverse("solicitacoes:minhas")))
        self.confere_casca(html)
        self.assertIn(reverse("solicitacoes:desistir", args=[pendente.ano, pendente.numero]), html)
        self.assertNotIn(reverse("solicitacoes:desistir", args=[decidida.ano, decidida.numero]), html)
        self.assertIn(pendente.codigo, html)
        self.assertIn("Aprovada", html)
        # A outra unidade não vê nada.
        outra = self.html(self.get(self.solicitante_b, reverse("solicitacoes:minhas")))
        self.assertNotIn(pendente.codigo + "</a>", outra)
        self.assertNotIn(reverse("solicitacoes:detalhe", args=[pendente.ano, pendente.numero]), outra)
        # Equipe vê todas, sem botão de desistir.
        todas = self.html(self.get(self.equipe, reverse("solicitacoes:minhas")))
        self.assertIn(reverse("solicitacoes:detalhe", args=[pendente.ano, pendente.numero]), todas)
        self.assertNotIn("/desistir", todas)

    # --- fila "Para avaliar" --------------------------------------------------------------

    def test_fila_so_traz_a_alcada_de_quem_olha(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        equipe = self.get(self.equipe, reverse("solicitacoes:avaliar"))
        self.assertEqual([linha["campo"] for linha in equipe.context["linhas"]], [Campo.PRAZO_ENTREGA])
        diretoria = self.get(self.diretoria, reverse("solicitacoes:avaliar"))
        self.assertEqual([linha["campo"] for linha in diretoria.context["linhas"]], [Campo.VALOR_ESTIMADO])
        ambos = self.get(self.ambos, reverse("solicitacoes:avaliar"))
        self.assertEqual(len(ambos.context["linhas"]), 2)
        html = self.html(equipe)
        self.confere_casca(html)
        self.assertIn(solicitacao.codigo, html)
        self.assertIn("#parte-", html)
        self.assertIn("Fora do exercício", html)

    def test_fila_poe_as_paradas_no_topo_e_destacadas(self):
        recente = self.criar(mes_previsto="9")
        antiga = self.criar(item=self.item_atrasado, valor_estimado="3.000,00", prazo_entrega="2027-02-01")
        Solicitacao.objects.filter(pk=antiga.pk).update(criada_em=now() - timedelta(days=30))
        resposta = self.get(self.ambos, reverse("solicitacoes:avaliar"))
        linhas = resposta.context["linhas"]
        self.assertEqual(len(linhas), 3)
        self.assertTrue(linhas[0]["parada"] and linhas[1]["parada"])
        self.assertFalse(linhas[2]["parada"])
        self.assertEqual(linhas[2]["codigo"], recente.codigo)
        self.assertEqual(resposta.context["paradas"], 2)
        self.assertEqual(resposta.context["pendentes"], 3)
        html = self.html(resposta)
        self.assertIn("Parada", html)
        # Mais antigas primeiro dentro de cada grupo.
        self.assertLess(html.index(self.url_detalhe(antiga)), html.index(self.url_detalhe(recente)))

    def test_fila_vazia(self):
        self.assertIn("Nada para avaliar", self.html(self.get(self.equipe, reverse("solicitacoes:avaliar"))))

    # --- menu e Início --------------------------------------------------------------------

    def test_menu_por_perfil_e_contador(self):
        inicio = reverse("core:inicio")
        solicitante = self.html(self.get(self.solicitante, inicio))
        self.assertIn(reverse("solicitacoes:nova"), solicitante)
        self.assertIn("Minhas solicitações", solicitante)
        self.assertNotIn("Para avaliar", solicitante)
        self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        equipe = self.html(self.get(self.equipe, inicio))
        self.assertIn("Para avaliar (1)", equipe)
        self.assertIn("Todas as solicitações", equipe)
        self.assertNotIn(reverse("solicitacoes:nova"), equipe)
        self.assertIn("Para avaliar (1)", self.html(self.get(self.diretoria, inicio)))
        self.assertIn("Para avaliar (2)", self.html(self.get(self.ambos, inicio)))

    def test_inicio_mostra_o_contador_so_para_quem_avalia(self):
        inicio = reverse("core:inicio")
        self.assertNotIn("Solicitações para avaliar", self.html(self.get(self.equipe, inicio)))
        self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        html = self.html(self.get(self.equipe, inicio))
        self.assertIn("Solicitações para avaliar: 1", html)
        self.assertIn(reverse("solicitacoes:avaliar"), html)
        self.assertNotIn("Solicitações para avaliar", self.html(self.get(self.solicitante, inicio)))
        self.assertNotIn("Solicitações para avaliar", self.html(self.get(self.visualizador, inicio)))

    # --- ficha do item --------------------------------------------------------------------

    def test_ficha_botao_e_aba_so_para_quem_deve_ver(self):
        ficha = reverse("pca:detalhe_processo", args=[self.ano, self.item.item_pca])
        solicitacao = self.criar(prazo_entrega="2027-01-10")
        da_unidade = self.html(self.get(self.solicitante, ficha))
        self.confere_casca(da_unidade)
        self.assertIn("Solicitar alteração", da_unidade)
        self.assertIn(f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item.item_pca}", da_unidade)
        self.assertIn(self.url_detalhe(solicitacao), da_unidade)
        for quem in (self.solicitante_b, self.visualizador, self.sem_vinculo):
            html = self.html(self.get(quem, ficha))
            self.assertNotIn("Solicitar alteração", html, quem.email)
            self.assertNotIn(self.url_detalhe(solicitacao), html, quem.email)
        for quem in (self.equipe, self.diretoria):
            html = self.html(self.get(quem, ficha))
            self.assertNotIn("Solicitar alteração", html, quem.email)  # não é da unidade do item
            self.assertIn(self.url_detalhe(solicitacao), html, quem.email)

    def test_ficha_sem_botao_quando_o_item_nao_aceita_pedido(self):
        concluido = self.novo_item(50, situacao="concluido")
        ficha = reverse("pca:detalhe_processo", args=[self.ano, concluido.item_pca])
        self.assertNotIn("Solicitar alteração", self.html(self.get(self.solicitante, ficha)))

    # --- estrutura de cada tela -----------------------------------------------------------

    def test_um_h1_e_no_maximo_uma_acao_primaria_em_cada_tela(self):
        solicitacao = self.criar(prazo_entrega="2027-01-10", valor_estimado="2.000,00")
        telas = {
            "nova_passo_1": (self.solicitante, reverse("solicitacoes:nova")),
            "nova_passo_2": (self.solicitante, f"{reverse('solicitacoes:nova')}?processo={self.ano}/{self.item.item_pca}"),
            "nova_inclusao": (self.solicitante, f"{reverse('solicitacoes:nova')}?tipo=inclusao"),
            "minhas": (self.solicitante, reverse("solicitacoes:minhas")),
            "avaliar": (self.ambos, reverse("solicitacoes:avaliar")),
            "detalhe_unidade": (self.solicitante, self.url_detalhe(solicitacao)),
            "detalhe_decisor": (self.ambos, self.url_detalhe(solicitacao)),
            "ficha": (self.solicitante, reverse("pca:detalhe_processo", args=[self.ano, self.item.item_pca])),
            "ficha_equipe": (self.admin, reverse("pca:detalhe_processo", args=[self.ano, self.item.item_pca])),
        }
        for nome, (quem, url) in telas.items():
            with self.subTest(tela=nome):
                resposta = self.get(quem, url)
                self.assertEqual(resposta.status_code, 200, nome)
                html = self.html(resposta)
                self.confere_casca(html)
                estrutura = _Estrutura()
                estrutura.feed(html)
                self.assertEqual(estrutura.h1, 1, nome)
                self.assertLessEqual(estrutura.primarios, 1, nome)
                if self.casca == "tabler":
                    self.assertNotRegex(html, r'class="[^"]*\bbr-[a-z]', nome)


class TelasDsgovTest(TelasMixin, CenarioBase):
    casca = "dsgov"


@CASCA_TABLER
class TelasTablerTest(TelasMixin, CenarioBase):
    casca = "tabler"
