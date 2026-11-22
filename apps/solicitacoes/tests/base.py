"""Cenário comum dos testes de serviço: um exercício aberto, três itens (a entregar,
atrasado, em tramitação), usuários de cada perfil e vínculos usuário↔unidade."""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils.timezone import localdate

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import Estado, Processo, Situacao
from apps.solicitacoes.models import VinculoUnidade


class CenarioBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        for nome in ("Concluído", "Em tramitação", "Sem informação", "Cancelado"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)
        cls.ano = localdate().year
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=cls.ano, defaults={"rotulo": f"PCA {cls.ano}", "situacao": SituacaoExercicio.ABERTO}
        )
        cls.tipo_nova = Tipo.objects.create(nome="Nova Contratação")
        cls.tipo_renovacao = Tipo.objects.create(nome="Renovação")
        cls.tipo_vigente = Tipo.objects.create(nome="Vigente")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Gerência A")
        cls.outra_unidade = Unidade.objects.create(nome="Gerência B")

        Usuario = get_user_model()

        def usuario(email, *grupos, **extra):
            novo = Usuario.objects.create_user(email=email, password="x", **extra)
            for grupo in grupos:
                novo.groups.add(Group.objects.get(name=grupo))
            return novo

        cls.solicitante = usuario("sol-a@example.com", "solicitante", first_name="Ana")
        VinculoUnidade.objects.create(usuario=cls.solicitante, unidade=cls.unidade)
        cls.colega = usuario("colega-a@example.com", "solicitante")
        VinculoUnidade.objects.create(usuario=cls.colega, unidade=cls.unidade)
        cls.solicitante_b = usuario("sol-b@example.com", "solicitante")
        VinculoUnidade.objects.create(usuario=cls.solicitante_b, unidade=cls.outra_unidade)
        cls.sem_vinculo = usuario("sem-vinculo@example.com", "solicitante")
        cls.equipe = usuario("equipe@example.com", "editor", first_name="Eva")
        cls.diretoria = usuario("diretoria@example.com", "diretoria", first_name="Davi")
        cls.ambos = usuario("ambos@example.com", "editor", "diretoria")
        cls.visualizador = usuario("visualizador@example.com", "visualizador")
        cls.admin = Usuario.objects.create_superuser(email="admin@example.com", password="x")

        # Item a entregar (no prazo), prazo daqui a muito tempo dentro do exercício.
        cls.item = cls.novo_item(1, prazo_entrega=date(cls.ano, 12, 15))
        # Item atrasado: NO_PRAZO gravado, prazo no passado (a leitura mostra Atrasado).
        cls.item_atrasado = cls.novo_item(2, prazo_entrega=date(cls.ano - 1, 12, 1))
        cls.item_tramitacao = cls.novo_item(
            3, situacao=Situacao.EM_TRAMITACAO, data_recebimento_gelic=date(cls.ano, 1, 20)
        )

    @classmethod
    def novo_item(cls, numero, *, tipo=None, unidade=None, **campos):
        padrao = dict(
            item_pca=numero,
            exercicio=cls.exercicio,
            descricao_objeto=f"Objeto do item {numero}",
            tipo=tipo or cls.tipo_nova,
            categoria=cls.categoria,
            unidade_organizacional=unidade or cls.unidade,
            estado=Estado.ATIVO,
            situacao=Situacao.NO_PRAZO,
            mes_previsto=6,
            valor_estimado="1000.00",
        )
        padrao.update(campos)
        item = Processo(**padrao)
        item._history_user = cls.admin
        item.save()
        return item
