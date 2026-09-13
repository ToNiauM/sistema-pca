"""Base compartilhada de setUp/POST para testes que editam um campo do
processo pelo formulário completo (`pca:editar_processo`).

`_dados_completos`/`_url_editar` reconstroem o POST inteiro de
`ProcessoForm` a partir do estado atual do processo, sobrepondo só o(s)
campo(s) que o teste quer mudar (submeter só 1 campo do form inteiro
apagaria os demais — `ModelForm` trata ausência como valor vazio, não
como "não mexeu"). `test_validators.py` e `test_execucao_contratual.py`
reaproveitam os mesmos dois helpers.

Módulo sem prefixo `test_` de propósito: não é uma suíte em si (nenhum
método `test_*`), só a fixture; o discovery padrão do Django (`test*.py`)
não deve tentar coletá-lo como um caso de teste vazio.
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.pca.models import Processo


class DetalheEdicaoBase(TransactionTestCase):
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
            email="editor-detalhe@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = User.objects.create_user(
            email="visualizador-detalhe@pca.local", password="senha-segura"
        )
        # item 26: Nova Contratação/NO PRAZO, sem nenhum fato gravado
        # (data_assinatura_contrato/data_recebimento_gelic), livre para o
        # teste sobrepor à vontade.
        self.processo = Processo.objects.get(item_pca=26)
        self.client.force_login(self.editor)

    def _dados_completos(self, **overrides):
        """Reconstrói o POST inteiro de `ProcessoForm` a partir do estado
        ATUAL do processo (o mesmo que `ProcessoForm(instance=...)` usaria
        como `initial`), sobrepondo só o(s) campo(s) que o teste quer
        mudar. Inclui por padrão o `management_form` do
        `ProcessoSEIFormSet` sem tocar nos filhos — quem quiser mexer em
        SEI usa `_dados_sei_formset`."""
        from apps.pca.forms import ProcessoForm

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
        dados.update(self._dados_sei_formset())
        dados["versao"] = self.processo.atualizado_em.isoformat()
        return dados

    def _dados_sei_formset(self, linhas_extra=2, excluir_ids=()):
        """Dados do `management_form` do `ProcessoSEIFormSet`, mais uma
        linha por filho já existente (inalterada) e `linhas_extra` linhas
        vazias — o mesmo shape que o GET de `pca:editar_processo`
        renderiza (`extra=2`)."""
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

    def _url_editar(self):
        return reverse("pca:editar_processo", args=[2026, self.processo.item_pca])
