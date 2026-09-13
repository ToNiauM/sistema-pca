"""`pca:editar_processo` é página própria (`processo_formulario.html`),
não um modal multi-aba. Os invariantes de negócio que sobrevivem
(fronteira de confiança, trava otimista, histórico, `status`
inalcançável por este caminho) continuam cobertos abaixo.

Convive com `test_execucao_contratual.py` (o bloco de execução
contratual, também retargetado para este form). A mesma superfície de
validação (CNPJ/vigência) migrou para
`test_validators.py`/`_bases_edicao_campo.py`, via este mesmo form."""

from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import close_old_connections
from django.test import Client, TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca import services
from apps.pca.forms import ProcessoForm
from apps.pca.models import Processo, ProcessoSEI, Situacao


class FormularioEdicaoBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            "apps/pca/fixtures/modelo-controle-exemplo.xlsx",
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-form@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = User.objects.create_user(
            email="visualizador-form@pca.local", password="senha-segura"
        )
        # Processo NOVO (`services.criar_processo`), não um item importado da
        # planilha real: os itens 1-149 carregam dado histórico legítimo mas
        # às vezes sujo (ex.: CNPJ mascarado incompleto) em campos fora do
        # escopo do teste — como o `ProcessoForm` inteiro é revalidado a
        # cada submissão, sem edição por campo isolado, reenviar esse dado
        # sujo sem intenção de mudá-lo reprovaria a submissão por um
        # motivo alheio ao que o teste verifica. Um processo novo nasce com
        # todo o bloco de execução contratual vazio.
        self.processo = services.criar_processo(
            usuario=self.editor,
            descricao_objeto="Processo de teste da Task 3",
            tipo_id=Tipo.objects.first().pk,
            categoria_id=Categoria.objects.first().pk,
            unidade_organizacional_id=Unidade.objects.first().pk,
        )
        self.client.force_login(self.editor)

    @property
    def url(self):
        return reverse("pca:editar_processo", args=[2026, self.processo.item_pca])

    @property
    def url_detalhe(self):
        return reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])

    def versao(self):
        self.processo.refresh_from_db()
        return self.processo.atualizado_em.isoformat()

    def dados_completos(self, **overrides):
        """Reconstrói o POST do `ProcessoForm` inteiro a partir do estado
        atual do processo, sobrepondo só o(s) campo(s) que o teste muda —
        ausência num `ModelForm` é "apague", não "não mexeu": o form
        inteiro é submetido de uma vez, sem abas. Inclui por padrão o
        `management_form` do `ProcessoSEIFormSet` sem tocar nos filhos —
        quem quiser mexer em SEI usa `dados_sei_formset`."""
        self.processo.refresh_from_db()
        form = ProcessoForm(instance=self.processo)
        dados = {}
        for nome in form.fields:
            valor = form.initial.get(nome)
            if valor is None:
                dados[nome] = ""
            elif hasattr(valor, "isoformat"):
                dados[nome] = valor.isoformat()
            else:
                dados[nome] = str(valor)
        dados.update(
            {chave: ("" if valor is None else str(valor)) for chave, valor in overrides.items()}
        )
        dados.update(self.dados_sei_formset())
        dados["versao"] = self.versao()
        return dados

    def dados_sei_formset(self, linhas_extra=2, excluir_ids=()):
        """Dados do `management_form` do `ProcessoSEIFormSet`, mais uma
        linha por filho já existente (inalterada) e `linhas_extra` linhas
        vazias — o mesmo shape que o GET renderiza (`extra=2`). `excluir_ids`
        marca `DELETE` nas linhas existentes cujo pk está no conjunto."""
        self.processo.refresh_from_db()
        existentes = list(self.processo.numeros_sei.order_by("id"))
        dados = {
            "numeros_sei-TOTAL_FORMS": str(len(existentes) + linhas_extra),
            "numeros_sei-INITIAL_FORMS": str(len(existentes)),
            "numeros_sei-MIN_NUM_FORMS": "0",
            "numeros_sei-MAX_NUM_FORMS": "1000",
        }
        for indice, sei in enumerate(existentes):
            dados[f"numeros_sei-{indice}-id"] = str(sei.pk)
            dados[f"numeros_sei-{indice}-numero_sei"] = sei.numero_sei
            if sei.pk in excluir_ids:
                dados[f"numeros_sei-{indice}-DELETE"] = "on"
        for indice in range(len(existentes), len(existentes) + linhas_extra):
            dados[f"numeros_sei-{indice}-id"] = ""
            dados[f"numeros_sei-{indice}-numero_sei"] = ""
        return dados


class TestPermissao(FormularioEdicaoBase):
    def test_visualizador_recebe_403_no_get(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 403)

    def test_visualizador_recebe_403_no_post(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.post(self.url, self.dados_completos())
        self.assertEqual(resposta.status_code, 403)

    def test_editor_ve_pagina_editavel(self):
        resposta = self.client.get(self.url)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("<form", conteudo)
        self.assertEqual(conteudo.count("<h1"), 1)
        self.assertNotIn("<br-modal", conteudo)
        self.assertNotIn("x-data", conteudo)

    def test_exercicio_fechado_redireciona_ao_detalhe_sem_abrir_formulario(self):
        Exercicio.objects.filter(ano=2026).update(situacao=SituacaoExercicio.FECHADO)
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, self.url_detalhe)


class TestGravacaoBasica(FormularioEdicaoBase):
    def test_grava_varios_campos_numa_submissao_com_historico(self):
        dados = self.dados_completos(
            descricao_objeto="Objeto atualizado pela Task 3",
            grau_prioridade="",
        )
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.descricao_objeto, "Objeto atualizado pela Task 3")
        self.assertTrue(
            self.processo.history.filter(history_user=self.editor).exists()
        )

    def test_valor_monetario_mascarado_em_pt_br_e_aceito(self):
        dados = self.dados_completos(valor_estimado="35.000,00")
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.processo.refresh_from_db()
        self.assertEqual(str(self.processo.valor_estimado), "35000.00")

    def test_sucesso_grava_messages_success_e_redireciona_ao_detalhe(self):
        resposta = self.client.post(self.url, self.dados_completos(), follow=True)
        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertIn("Processo atualizado.", mensagens)


class TestFronteiraDeConfianca(FormularioEdicaoBase):
    def test_situacao_nao_e_alteravel_por_este_caminho(self):
        situacao_antes = self.processo.situacao
        dados = self.dados_completos()
        dados["situacao"] = Situacao.CONCLUIDO
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, situacao_antes)

    def test_formulario_nao_renderiza_campo_fora_da_allowlist(self):
        resposta = self.client.get(self.url)
        conteudo = resposta.content.decode()
        self.assertNotIn('name="situacao"', conteudo)
        self.assertNotIn('name="estado"', conteudo)


class TestConcorrenciaEValidacao(FormularioEdicaoBase):
    def test_versao_desatualizada_nao_grava_e_devolve_versao_nova(self):
        descricao_antes = self.processo.descricao_objeto
        dados = self.dados_completos(descricao_objeto="Não deveria gravar")
        dados["versao"] = "2000-01-01T00:00:00+00:00"

        resposta = self.client.post(self.url, dados)

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("mudou enquanto você editava", resposta.content.decode())
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.descricao_objeto, descricao_antes)

    def test_valor_invalido_nao_grava_nenhum_campo_da_submissao(self):
        descricao_antes = self.processo.descricao_objeto
        dados = self.dados_completos(
            descricao_objeto="Não deveria gravar isto também",
            valor_estimado="não-é-um-número",
        )

        resposta = self.client.post(self.url, dados)

        self.assertEqual(resposta.status_code, 200)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.descricao_objeto, descricao_antes)

    def test_vigencia_invertida_na_mesma_submissao_e_recusada(self):
        dados = self.dados_completos(
            vigencia_inicio="2026-06-01", vigencia_fim="2026-01-01"
        )
        resposta = self.client.post(self.url, dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(
            "A vigência final não pode ser anterior à inicial.",
            resposta.content.decode(),
        )

    def test_vigencia_coerente_na_mesma_submissao_grava(self):
        dados = self.dados_completos(
            vigencia_inicio="2026-01-01", vigencia_fim="2026-06-01"
        )
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.processo.refresh_from_db()
        self.assertEqual(str(self.processo.vigencia_inicio), "2026-01-01")
        self.assertEqual(str(self.processo.vigencia_fim), "2026-06-01")

    def test_exercicio_fechado_recusa_a_escrita(self):
        dados = self.dados_completos(descricao_objeto="Não deveria gravar (fechado)")
        Exercicio.objects.filter(ano=2026).update(situacao=SituacaoExercicio.FECHADO)

        resposta = self.client.post(self.url, dados)

        # O mesmo guard de exercício fechado que barra o GET (`TestPermissao`)
        # cobre o POST direto (URL antiga, script) — recusa ANTES de tentar
        # `services.bloquear_para_edicao`.
        self.assertRedirects(resposta, self.url_detalhe)


class TestCriacaoUsaMesmoFormulario(FormularioEdicaoBase):
    """`ProcessoForm(criando=True)` — só 4 campos, sem fieldsets."""

    def test_criando_expõe_só_4_campos(self):
        resposta = self.client.get(reverse("pca:criar_processo"))
        self.assertEqual(resposta.status_code, 200)
        for campo in ("descricao_objeto", "tipo", "categoria", "unidade_organizacional"):
            self.assertIn(f'name="{campo}"', resposta.content.decode())
        for campo in ("valor_estimado", "mes_previsto", "modalidade"):
            self.assertNotIn(f'name="{campo}"', resposta.content.decode())

    def test_criando_nao_renderiza_formset_de_sei(self):
        resposta = self.client.get(reverse("pca:criar_processo"))
        conteudo = resposta.content.decode()
        self.assertNotIn("numeros_sei-TOTAL_FORMS", conteudo)


class TestFormsetSei(FormularioEdicaoBase):
    """Números SEI só mudam dentro do fieldset Processo, persistidos
    junto com o Salvar do `ProcessoForm`, mesma transação e mesmo token
    otimista (`ProcessoSEIFormSet`)."""

    def test_get_monta_duas_linhas_extras_e_filhos_existentes_em_ordem_de_id(self):
        primeiro = ProcessoSEI.objects.create(
            processo=self.processo, numero_sei="11111.000001/2026-01"
        )
        segundo = ProcessoSEI.objects.create(
            processo=self.processo, numero_sei="11111.000002/2026-01"
        )
        resposta = self.client.get(self.url)
        conteudo = resposta.content.decode()
        self.assertIn('name="numeros_sei-TOTAL_FORMS" value="4"', conteudo)
        self.assertIn('name="numeros_sei-INITIAL_FORMS" value="2"', conteudo)
        self.assertLess(
            conteudo.index(primeiro.numero_sei), conteudo.index(segundo.numero_sei)
        )

    def test_post_com_linha_extra_preenchida_cria_exatamente_um_numero_sei(self):
        dados = self.dados_completos()
        dados["numeros_sei-0-numero_sei"] = "22222.000001/2026-01"

        resposta = self.client.post(self.url, dados)

        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(
            list(self.processo.numeros_sei.values_list("numero_sei", flat=True)),
            ["22222.000001/2026-01"],
        )

    def test_post_com_delete_remove_exatamente_o_filho_marcado(self):
        mantido = ProcessoSEI.objects.create(
            processo=self.processo, numero_sei="33333.000001/2026-01"
        )
        removido = ProcessoSEI.objects.create(
            processo=self.processo, numero_sei="33333.000002/2026-01"
        )
        dados = self.dados_completos()
        dados.update(self.dados_sei_formset(excluir_ids={removido.pk}))

        resposta = self.client.post(self.url, dados)

        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(
            list(self.processo.numeros_sei.values_list("pk", flat=True)), [mantido.pk]
        )

    def test_zero_numeros_nao_grava_nada_e_uma_linha_unica_salva_um(self):
        # EDGE FIC29-01 empty — linhas extras vazias são ignoradas.
        resposta = self.client.post(self.url, self.dados_completos())
        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(self.processo.numeros_sei.count(), 0)

        dados = self.dados_completos()
        dados["numeros_sei-0-numero_sei"] = "44444.000001/2026-01"
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(
            list(self.processo.numeros_sei.values_list("numero_sei", flat=True)),
            ["44444.000001/2026-01"],
        )

    def test_duplicado_retorna_200_com_erro_e_nada_muda(self):
        # EDGE FIC29-01 adjacency — dois números iguais no mesmo processo
        # colidem com `ProcessoSEI.unique_together`.
        existente = ProcessoSEI.objects.create(
            processo=self.processo, numero_sei="55555.000001/2026-01"
        )
        descricao_antes = self.processo.descricao_objeto
        dados = self.dados_completos(descricao_objeto="Não deveria gravar (duplicado)")
        dados["numeros_sei-1-numero_sei"] = existente.numero_sei

        resposta = self.client.post(self.url, dados)

        self.assertEqual(resposta.status_code, 200)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.descricao_objeto, descricao_antes)
        self.assertEqual(
            list(self.processo.numeros_sei.values_list("pk", "numero_sei")),
            [(existente.pk, existente.numero_sei)],
        )

    def test_editor_sem_permissao_e_exercicio_fechado_continuam_bloqueados(self):
        # A fronteira de permissão/exercício já existente cobre o formset:
        # nenhum caminho novo de escrita nasce com ele.
        self.client.force_login(self.visualizador)
        resposta = self.client.post(self.url, self.dados_completos())
        self.assertEqual(resposta.status_code, 403)

        self.client.force_login(self.editor)
        Exercicio.objects.filter(ano=2026).update(situacao=SituacaoExercicio.FECHADO)
        dados = self.dados_completos()
        dados["numeros_sei-0-numero_sei"] = "66666.000001/2026-01"
        resposta = self.client.post(self.url, dados)
        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(self.processo.numeros_sei.count(), 0)


class TestIdempotenciaEConcorrenciaSei(FormularioEdicaoBase):
    """EDGE FIC29-01 idempotency/concurrency — o mesmo token otimista do
    `ProcessoForm` cobre o formset: só uma gravação integral vence."""

    def test_reenvio_do_mesmo_post_apos_token_consumido_nao_duplica(self):
        dados = self.dados_completos()
        dados["numeros_sei-0-numero_sei"] = "77777.000001/2026-01"

        primeira = self.client.post(self.url, dados)
        self.assertRedirects(primeira, self.url_detalhe)
        self.assertEqual(self.processo.numeros_sei.count(), 1)

        segunda = self.client.post(self.url, dados)  # mesmo payload, versão já consumida

        self.assertEqual(segunda.status_code, 200)
        self.assertEqual(self.processo.numeros_sei.count(), 1)
        self.assertEqual(
            list(self.processo.numeros_sei.values_list("numero_sei", flat=True)),
            ["77777.000001/2026-01"],
        )

    def test_duas_submissoes_concorrentes_com_a_mesma_versao_tem_no_maximo_uma_gravacao(self):
        versao = self.versao()

        def enviar(numero):
            close_old_connections()
            try:
                cliente = Client()
                cliente.force_login(self.editor)
                dados = self.dados_completos()
                dados["versao"] = versao
                dados["numeros_sei-0-numero_sei"] = f"88888.{numero:06d}/2026-01"
                return cliente.post(self.url, dados)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            respostas = list(executor.map(enviar, (1, 2)))

        codigos = sorted(resposta.status_code for resposta in respostas)
        # Uma vence (302, grava) e a outra perde a corrida — 200 (conflito de
        # versão ou, se a colisão só aparecer depois do lock, validação do
        # formset) ou 403 (perde e o exercício segue igual); em nenhum caso a
        # perdedora deixa mudança parcial no `ProcessoSEI`.
        self.assertIn(302, codigos)
        self.assertEqual(self.processo.numeros_sei.count(), 1)
