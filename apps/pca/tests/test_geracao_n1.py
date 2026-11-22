"""Testes do serviço `apps.pca.servicos.geracao_n1` (Fase 40) e das views "Gerar itens de N+1", spec
documento interno de desenho.

`TestPreviaGeracao`/`TestGerar` reaproveitam `_BaseCatalogo` de
`test_servicos_contratos.py` (catálogo mínimo, `TestCase` puro, sem
importação de planilha). `TestGerarN1Views` (ao final deste
arquivo) monta sua própria fixture de usuários (superusuário/editor com
`gerir_exercicio`/visualizador) — a guarda desta ação é mais estrita que a
virada (superuser ∧ gerir_exercicio, não só a permissão)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import Processo, RegimeExecucao, Situacao
from apps.pca.projecao.virada import Destino
from apps.pca.servicos import consultas_fluxo
from apps.pca.servicos.geracao_n1 import (
    CatalogoIncompleto,
    ExercicioDestinoFechado,
    gerar,
    previa,
)
from apps.pca.tests.test_servicos_contratos import _BaseCatalogo

HOJE = date(2026, 9, 22)


class _BaseGeracaoN1(_BaseCatalogo):
    """`_popular_catalogo` cria `Tipo("Vigente {sufixo}")`, que NÃO
    normaliza para "vigente" — os dois nomes exatos exigidos pelo serviço
    (`Tipo.nome_normalizado in {"renovacao", "vigente"}`) são criados à
    parte aqui."""

    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("GeracaoN1")
        cls.tipo_renovacao_n1 = Tipo.objects.create(nome="Renovação")
        cls.tipo_vigente_n1 = Tipo.objects.create(nome="Vigente")


class TestPreviaGeracao(_BaseGeracaoN1):
    def test_classificacao_das_quatro_linhas_e_contagens(self):
        renovacao = self._criar_item(
            vigencia_fim=date(2027, 3, 31), renovacao_prevista=True
        )
        encerra = self._criar_item(
            vigencia_fim=date(2027, 5, 31), renovacao_prevista=False
        )
        vigente = self._criar_item(
            vigencia_fim=date(2028, 12, 31), mes_previsto=6
        )
        nao_entra_renova_n = self._criar_item(
            vigencia_fim=date(2026, 12, 31), renovacao_prevista=True
        )
        nao_entra_vencido = self._criar_item(
            vigencia_fim=date(2026, 1, 1), renovacao_prevista=False
        )

        resultado = previa(self.exercicio, hoje=HOJE)
        por_pk = {linha.processo.pk: linha for linha in resultado.linhas}

        linha_renovacao = por_pk[renovacao.pk]
        self.assertEqual(linha_renovacao.destino, Destino.RENOVACAO_N1)
        self.assertEqual(linha_renovacao.estado, "novo")
        self.assertEqual(linha_renovacao.tipo_chave, "renovacao")
        self.assertEqual(linha_renovacao.situacao, "no_prazo")
        self.assertEqual(linha_renovacao.mes, 3)

        linha_encerra = por_pk[encerra.pk]
        self.assertEqual(linha_encerra.destino, Destino.ENCERRA_N1)
        self.assertEqual(linha_encerra.estado, "novo")
        self.assertEqual(linha_encerra.tipo_chave, "vigente")
        self.assertEqual(linha_encerra.situacao, "concluido")
        self.assertEqual(linha_encerra.mes, 5)

        linha_vigente = por_pk[vigente.pk]
        self.assertEqual(linha_vigente.destino, Destino.VIGENTE_N1)
        self.assertEqual(linha_vigente.estado, "novo")
        self.assertEqual(linha_vigente.tipo_chave, "vigente")
        self.assertEqual(linha_vigente.situacao, "concluido")
        self.assertEqual(linha_vigente.mes, 6)

        self.assertEqual(por_pk[nao_entra_renova_n.pk].estado, "nao_entra")
        self.assertEqual(por_pk[nao_entra_renova_n.pk].destino, Destino.RENOVA_N)
        self.assertEqual(por_pk[nao_entra_vencido.pk].estado, "nao_entra")
        self.assertEqual(por_pk[nao_entra_vencido.pk].destino, Destino.VENCIDO)

        self.assertEqual(resultado.novos, 3)
        self.assertEqual(resultado.ja_gerados, 0)
        self.assertEqual(resultado.nao_entram, 2)
        self.assertEqual(resultado.contagem[Destino.RENOVACAO_N1], 1)
        self.assertEqual(resultado.contagem[Destino.ENCERRA_N1], 1)
        self.assertEqual(resultado.contagem[Destino.VIGENTE_N1], 1)
        self.assertEqual(resultado.contagem[Destino.RENOVA_N], 1)
        self.assertEqual(resultado.contagem[Destino.VENCIDO], 1)
        self.assertEqual(resultado.erros, [])
        self.assertFalse(resultado.exercicio_destino_existe)
        self.assertEqual(resultado.ano_destino, self.exercicio.ano + 1)

    def test_valor_da_projecao_quando_o_motor_tem_parcela_em_n1(self):
        item = self._criar_item(
            vigencia_fim=date(2028, 12, 31),
            vigencia_inicio=date(2026, 1, 1),
            regime_execucao=RegimeExecucao.CONTINUADO,
            valor_mensal=Decimal("1000.00"),
            data_assinatura_contrato=date(2026, 1, 1),
            valor_estimado=Decimal("999999.99"),
        )
        resultado = previa(self.exercicio, hoje=HOJE)
        linha = next(l for l in resultado.linhas if l.processo.pk == item.pk)

        ano_destino = self.exercicio.ano + 1
        projecao, _itens = consultas_fluxo.projecao_oficial(self.exercicio, hoje=HOJE)
        esperado = sum(
            (
                p.valor
                for p in projecao.parcelas
                if p.item_pca == item.item_pca
                and p.camada != "planejado"
                and p.competencia.startswith(f"{ano_destino}-")
            ),
            Decimal("0"),
        ).quantize(Decimal("0.01"))

        self.assertEqual(linha.fonte_valor, "projecao")
        self.assertEqual(linha.valor, esperado)
        self.assertGreater(linha.valor, Decimal("0"))
        self.assertNotEqual(linha.valor, item.valor_estimado)

    def test_valor_cai_no_fallback_da_origem_sem_parcela_no_motor(self):
        item = self._criar_item(
            vigencia_fim=date(2028, 12, 31),
            valor_estimado=Decimal("50000.00"),
            valor_mensal=None,
            regime_execucao=None,
        )
        resultado = previa(self.exercicio, hoje=HOJE)
        linha = next(l for l in resultado.linhas if l.processo.pk == item.pk)
        self.assertEqual(linha.fonte_valor, "origem")
        self.assertEqual(linha.valor, Decimal("50000.00"))

    def test_ja_gerado_aparece_com_o_item_gerado(self):
        item = self._criar_item(
            vigencia_fim=date(2027, 3, 31), renovacao_prevista=True
        )
        gerar(self.exercicio, usuario=None, hoje=HOJE)
        resultado = previa(self.exercicio, hoje=HOJE)
        linha = next(l for l in resultado.linhas if l.processo.pk == item.pk)
        self.assertEqual(linha.estado, "ja_gerado")
        self.assertIsNotNone(linha.item_gerado)
        self.assertEqual(resultado.novos, 0)
        self.assertEqual(resultado.ja_gerados, 1)

    def test_catalogo_sem_tipo_renovacao_preenche_erros(self):
        self.tipo_renovacao_n1.delete()
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)
        resultado = previa(self.exercicio, hoje=HOJE)
        self.assertIn("Catálogo sem o tipo 'Renovação'", resultado.erros)


class TestGerar(_BaseGeracaoN1):
    def test_gerar_cria_so_os_tres_destinos_que_entram(self):
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)
        self._criar_item(vigencia_fim=date(2027, 5, 31), renovacao_prevista=False)
        self._criar_item(vigencia_fim=date(2028, 12, 31))
        self._criar_item(vigencia_fim=date(2026, 12, 31), renovacao_prevista=True)
        self._criar_item(vigencia_fim=date(2026, 1, 1), renovacao_prevista=False)

        resultado = gerar(self.exercicio, usuario=None, hoje=HOJE)

        self.assertEqual(len(resultado.criados), 3)
        self.assertEqual(resultado.exercicio_destino.ano, 2027)
        self.assertEqual(resultado.exercicio_destino.situacao, SituacaoExercicio.ABERTO)
        self.assertEqual(
            Processo.objects.filter(exercicio__ano=2027).count(), 3
        )

    def test_campos_copiados_tipo_situacao_mes_valor_e_execucao(self):
        origem = self._criar_item(
            vigencia_fim=date(2027, 3, 31),
            renovacao_prevista=True,
            fornecedor_razao_social="Fornecedor Teste Ltda",
            numero_instrumento_contratual="CT 99/2026",
            valor_estimado=Decimal("12345.67"),
        )
        gerar(self.exercicio, usuario=None, hoje=HOJE)
        novo = Processo.objects.get(exercicio__ano=2027, origem=origem)

        self.assertEqual(novo.tipo, self.tipo_renovacao_n1)
        self.assertEqual(novo.situacao, Situacao.NO_PRAZO)
        self.assertEqual(novo.mes_previsto, 3)
        self.assertEqual(novo.fornecedor_razao_social, "Fornecedor Teste Ltda")
        self.assertEqual(novo.numero_instrumento_contratual, "CT 99/2026")
        self.assertEqual(novo.vigencia_fim, origem.vigencia_fim)
        self.assertEqual(novo.origem_id, origem.pk)
        self.assertEqual(novo.numeros_sei.count(), 0)
        self.assertIsNone(novo.data_inclusao_pca)
        self.assertIsNone(novo.data_envio_gelic)
        self.assertIsNone(novo.data_recebimento_gelic)
        self.assertIsNone(novo.data_prevista_conclusao)

        registro = novo.history.order_by("history_date").first()
        self.assertEqual(registro.history_change_reason, "Geração N+1 a partir de contratos (Fase 40)")

    def test_numeracao_continua_do_maximo_existente_em_n1(self):
        Exercicio.objects.create(ano=2027, rotulo="PCA 2027", situacao=SituacaoExercicio.ABERTO)
        Processo.objects.create(
            item_pca=40,
            exercicio=Exercicio.objects.get(ano=2027),
            descricao_objeto="Item pré-existente em 2027",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.uo,
        )
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)

        resultado = gerar(self.exercicio, usuario=None, hoje=HOJE)
        self.assertEqual(resultado.criados[0].item_pca, 41)

    def test_exercicio_destino_ja_existente_fechado_recusa_geracao(self):
        # QA 30/09 (.4) — decisão do usuário sobrepõe a spec original da Fase 40
        # §0 ("gerar como está" no destino fechado): agora a geração inteira é recusada,
        # nada é escrito, quando o exercício de destino já existe FECHADO.
        Exercicio.objects.create(ano=2027, rotulo="PCA 2027", situacao=SituacaoExercicio.FECHADO)
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)

        with self.assertRaises(ExercicioDestinoFechado):
            gerar(self.exercicio, usuario=None, hoje=HOJE)
        self.assertEqual(Processo.objects.filter(exercicio__ano=2027).count(), 0)

    def test_segunda_chamada_cria_zero(self):
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)
        gerar(self.exercicio, usuario=None, hoje=HOJE)
        resultado = gerar(self.exercicio, usuario=None, hoje=HOJE)
        self.assertEqual(resultado.criados, [])
        self.assertEqual(Processo.objects.filter(exercicio__ano=2027).count(), 1)

    def test_sem_tipo_renovacao_levanta_catalogo_incompleto_e_nao_grava(self):
        self.tipo_renovacao_n1.delete()
        self._criar_item(vigencia_fim=date(2027, 3, 31), renovacao_prevista=True)
        with self.assertRaises(CatalogoIncompleto):
            gerar(self.exercicio, usuario=None, hoje=HOJE)
        self.assertEqual(Processo.objects.filter(exercicio__ano=2027).count(), 0)


class TestGerarN1Views(TestCase):
    """Acesso superuser ∧ `gerir_exercicio` (mais estrito que a virada,
    que só exige a permissão). `editor` tem `gerir_exercicio` mas NÃO é
    superusuário → 403 (a checagem redundante para superusuário real é
    intencional, ver interfaces do plano)."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.uo = Unidade.objects.create(nome="Unidade Views N1")
        cls.tipo = Tipo.objects.create(nome="Tipo Views N1")
        cls.tipo_renovacao_n1 = Tipo.objects.create(nome="Renovação")
        cls.tipo_vigente_n1 = Tipo.objects.create(nome="Vigente")
        cls.categoria = Categoria.objects.create(nome="Categoria Views N1")

        User = get_user_model()
        cls.superusuario = User.objects.create_superuser(
            email="super-n1@pca.local", password="senha-segura"
        )
        cls.editor_com_permissao = User.objects.create_user(
            email="editor-n1@pca.local", password="senha-segura"
        )
        cls.editor_com_permissao.user_permissions.add(
            Permission.objects.get(codename="gerir_exercicio"),
            Permission.objects.get(codename="view_acompanhamento"),
            Permission.objects.get(codename="ver_analises"),
        )
        cls.visualizador = User.objects.create_user(
            email="visualizador-n1@pca.local", password="senha-segura"
        )
        cls.visualizador.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento"),
            Permission.objects.get(codename="ver_analises"),
        )

        Processo.objects.create(
            item_pca=1,
            exercicio=cls.exercicio,
            descricao_objeto="Contrato de teste — views N1",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.uo,
            vigencia_fim=date(2027, 3, 31),
            renovacao_prevista=True,
        )

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")

    def test_superusuario_ve_a_previa(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.get(reverse("pca:gerar_n1", args=[2026]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "<h1 class=\"mb-0\">Gerar itens de 2027</h1>", html=False)
        self.assertContains(resposta, "Gerar")

    def test_previa_mostra_mes_por_extenso_nunca_digito_cru(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.get(reverse("pca:gerar_n1", args=[2026]))
        self.assertNotRegex(resposta.content.decode(), r'mês \d')

    def test_editor_com_permissao_mas_sem_superuser_recebe_403(self):
        self.client.force_login(self.editor_com_permissao)
        resposta = self.client.get(reverse("pca:gerar_n1", args=[2026]))
        self.assertEqual(resposta.status_code, 403)
        resposta_post = self.client.post(reverse("pca:gerar_n1_confirmar", args=[2026]))
        self.assertEqual(resposta_post.status_code, 403)

    def test_visualizador_recebe_403(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("pca:gerar_n1", args=[2026]))
        self.assertEqual(resposta.status_code, 403)

    def test_post_confirmar_gera_e_redireciona_para_tabela_de_n1(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.post(reverse("pca:gerar_n1_confirmar", args=[2026]))
        self.assertRedirects(
            resposta, f"{reverse('pca:tabela')}?exercicio=2027", fetch_redirect_response=False
        )
        self.assertTrue(
            Processo.objects.filter(exercicio__ano=2027, origem__isnull=False).exists()
        )
        seguida = self.client.get(resposta.url)
        mensagens = [str(m) for m in get_messages(seguida.wsgi_request)]
        self.assertTrue(any("gerado" in m for m in mensagens))

    def test_segundo_post_confirmar_nao_gera_nada_e_avisa(self):
        self.client.force_login(self.superusuario)
        self.client.post(reverse("pca:gerar_n1_confirmar", args=[2026]))
        resposta = self.client.post(reverse("pca:gerar_n1_confirmar", args=[2026]))
        self.assertRedirects(
            resposta, reverse("pca:gerar_n1", args=[2026]), fetch_redirect_response=False
        )
        seguida = self.client.get(resposta.url)
        mensagens = [str(m) for m in get_messages(seguida.wsgi_request)]
        self.assertTrue(any("Nada a gerar" in m for m in mensagens))

    def test_botao_aparece_em_prazos_e_gerenciar_exercicios_so_para_superusuario(self):
        self.client.force_login(self.superusuario)
        prazos = self.client.get(f"{reverse('pca:analise_prazos')}?exercicio=2026")
        self.assertContains(prazos, "Gerar itens de 2027")
        gerir = self.client.get(reverse("pca:gerenciar_exercicios"))
        self.assertContains(gerir, "Gerar itens de 2027")

        self.client.force_login(self.editor_com_permissao)
        prazos_editor = self.client.get(f"{reverse('pca:analise_prazos')}?exercicio=2026")
        self.assertNotContains(prazos_editor, "Gerar itens de 2027")
        gerir_editor = self.client.get(reverse("pca:gerenciar_exercicios"))
        self.assertNotContains(gerir_editor, "Gerar itens de 2027")
