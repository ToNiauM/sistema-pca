#!/usr/bin/env python3
"""Gera módulos (apps Django) completos a partir de um `sistema.yaml`, no padrão da skill dsgov.

Uso:
    python3 <skill>/scripts/gerar_app.py <raiz-do-projeto> <sistema.yaml> [--app NOME] [--forcar]

Para cada app do YAML cria apps/<app>/ com models, forms, views (listagem com busca/filtros/ordenação/
paginação, criar, editar, detalhe, excluir), urls, admin, testes e templates já no DSGov; registra o app
em INSTALLED_APPS, em config/urls.py e no menu lateral. Roda `makemigrations` ao final.

O formato do YAML está em references/especificacao.md. O modelo (IA) só escreve regras de negócio
DEPOIS de gerar: validações em forms.py/models.py, cálculos, permissões, fluxos de situação.
Templates gerados podem ser editados, mas continuam sujeitos ao verificador.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from string import Template

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML não instalado: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ------------------------------------------------------------------ util

def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return t


def classe(texto: str) -> str:
    return "".join(p.capitalize() for p in slug(texto).split("_"))


def escrever(caminho: Path, conteudo: str, forcar: bool):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists() and not forcar:
        print(f"  mantido  {caminho}")
        return
    caminho.write_text(conteudo, encoding="utf-8")
    print(f"  gerado   {caminho}")


def inserir_marcador(arquivo: Path, marcador: str, linha: str):
    texto = arquivo.read_text(encoding="utf-8")
    if linha.strip() in texto:
        return
    if marcador not in texto:
        raise SystemExit(f"marcador {marcador!r} não encontrado em {arquivo}")
    indent = re.search(r"^([ \t]*)" + re.escape(marcador), texto, re.M).group(1)
    texto = texto.replace(f"{indent}{marcador}", f"{indent}{linha}\n{indent}{marcador}", 1)
    arquivo.write_text(texto, encoding="utf-8")
    print(f"  editado  {arquivo}")


# ------------------------------------------------------------------ campos

TIPOS = {
    # tipo: (django field, kwargs extras, tipo de coluna na listagem)
    "texto": ("models.CharField", {"max_length": 200}, "texto"),
    "texto_longo": ("models.TextField", {}, "texto"),
    "inteiro": ("models.IntegerField", {}, "numero"),
    "decimal": ("models.DecimalField", {"max_digits": 14, "decimal_places": 2}, "numero"),
    "moeda": ("models.DecimalField", {"max_digits": 14, "decimal_places": 2}, "moeda"),
    "percentual": ("models.DecimalField", {"max_digits": 6, "decimal_places": 2}, "percentual"),
    "data": ("models.DateField", {}, "data"),
    "data_hora": ("models.DateTimeField", {}, "data"),
    "booleano": ("models.BooleanField", {"default": False}, "booleano"),
    "email": ("models.EmailField", {}, "texto"),
    "cpf": ("models.CharField", {"max_length": 14}, "texto"),
    "cnpj": ("models.CharField", {"max_length": 18}, "texto"),
    "arquivo": ("models.FileField", {"upload_to": "'arquivos/%Y/%m/'"}, "texto"),
    "escolha": ("models.CharField", {"max_length": 40}, "texto"),
    "fk": ("models.ForeignKey", {}, "texto"),
}

INPUT_TYPE = {"data": "date", "data_hora": "datetime-local", "email": "email", "inteiro": "number",
              "decimal": "number", "moeda": "number", "percentual": "number"}


def campo_model(c: dict, app: dict) -> str:
    tipo = c.get("tipo", "texto")
    if tipo not in TIPOS:
        raise SystemExit(f"tipo de campo desconhecido: {tipo} (campo {c['nome']})")
    fld, kwargs, _ = TIPOS[tipo]
    kwargs = dict(kwargs)
    args = [f'"{c.get("rotulo", c["nome"].replace("_", " ").capitalize())}"']
    if tipo == "texto" and c.get("max"):
        kwargs["max_length"] = c["max"]
    if tipo == "escolha":
        kwargs["choices"] = f"{classe(c['nome'])}Opcoes.choices"
        if c.get("padrao") is not None:
            kwargs["default"] = f'"{c["padrao"]}"'
        maior = max(len(str(v)) for v, _ in c["opcoes"])
        kwargs["max_length"] = max(40, maior)
    if tipo == "fk":
        para = c["para"] if "." in c["para"] else f"{app['nome']}.{c['para']}"
        args = [f'"{para}"', f'verbose_name="{c.get("rotulo", c["nome"].capitalize())}"']
        kwargs["on_delete"] = "models.PROTECT"
        kwargs["related_name"] = f'"{c.get("relacao", "+")}"' if c.get("relacao") else '"+"'
    if not c.get("obrigatorio", True) and tipo not in ("booleano",):
        kwargs["blank"] = True
        if tipo not in ("texto", "texto_longo", "email", "cpf", "cnpj", "escolha"):
            kwargs["null"] = True
    if c.get("unico"):
        kwargs["unique"] = True
    if c.get("ajuda"):
        kwargs["help_text"] = f'"{c["ajuda"]}"'
    if c.get("padrao") is not None and tipo != "escolha":
        kwargs["default"] = repr(c["padrao"]) if not isinstance(c["padrao"], str) else f'"{c["padrao"]}"'
    partes = args + [f"{k}={v}" for k, v in kwargs.items()]
    return f"    {c['nome']} = {fld}({', '.join(partes)})"


def lookup(caminho: str) -> str:
    return caminho.replace(".", "__")


# ------------------------------------------------------------------ templates Python

T_APPS = Template('''from django.apps import AppConfig


class ${Classe}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.${app}"
    verbose_name = "${rotulo}"
''')

T_MODELS = Template('''"""Modelos do módulo ${rotulo}. Gerado pela skill dsgov a partir de sistema.yaml.

Regras de negócio entram aqui (métodos, propriedades, clean()) e em forms.py — nunca nos templates.
"""

from django.db import models
from django.urls import reverse

${opcoes}

${modelos}
''')

T_MODELO = Template('''class ${Classe}(models.Model):
${campos}
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "${rotulo}"
        verbose_name_plural = "${rotulo_plural}"
        ordering = ["${ordenacao}"]

    def __str__(self):
        return str(self.${campo_str})

    def get_absolute_url(self):
        return reverse("${app}:${modelo}_detalhe", args=[self.pk])
${metodos_status}''')

T_STATUS = Template('''
    # Chave semântica para a br-tag status (cores fixas do DS): ${mapa}
    STATUS_${CAMPO} = ${dict_status}

    def ${campo}_chave(self):
        return self.STATUS_${CAMPO}.get(self.${campo}, "info")
''')

T_FORMS = Template('''"""Formulários do módulo ${rotulo}. O HTML sai do renderer DSGov; aqui só campos e validações."""

from django import forms

from .models import ${classes}

${forms}
''')

T_FORM = Template('''class ${Classe}Form(forms.ModelForm):
    class Meta:
        model = ${Classe}
        fields = [${fields}]
        widgets = {
${widgets}
        }

    def clean(self):
        dados = super().clean()
        # Regras de negócio entre campos entram aqui (ex.: data_fim >= data_inicio).
        return dados
''')

T_VIEWS = Template('''"""Views do módulo ${rotulo}. Listagem, criação, edição, detalhe e exclusão no padrão dsgov."""

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from core.listagem import ListagemView

from .forms import ${forms_import}
from .models import ${classes}
${imports_externos}

${views}
''')

T_VIEWS_MODELO = Template('''
class Listar${Classe}(PermissionRequiredMixin, ListagemView):
    permission_required = "${app}.view_${modelo}"
    model = ${Classe}
    template_name = "${app}/${modelo}_listar.html"
    template_parcial = "${app}/_${modelo}_tabela.html"
    titulo = "${rotulo_plural}"
    busca_campos = [${busca}]
    ordenacoes = {${ordenacoes}}
    ordenacao_padrao = "${ordenacao}"
    filtros = {${filtros}}
    colunas = [
${colunas}
    ]

    def get_queryset(self):
        return super().get_queryset()${select_related}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["trilha"] = [("${rotulo_plural}", None)]
        ctx["url_novo"] = reverse("${app}:${modelo}_novo")
        return ctx

    def opcoes_filtros(self):
        return {
${opcoes_filtros}
        }


class Criar${Classe}(PermissionRequiredMixin, CreateView):
    permission_required = "${app}.add_${modelo}"
    model = ${Classe}
    form_class = ${Classe}Form
    template_name = "${app}/${modelo}_formulario.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = "${novo} ${rotulo_min}"
        ctx["trilha"] = [("${rotulo_plural}", reverse("${app}:${modelo}_listar")), ("${novo} ${rotulo_min}", None)]
        ctx["url_cancelar"] = reverse("${app}:${modelo}_listar")
        return ctx

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, "${rotulo} cadastrad${o} com sucesso.")
        return resposta


class Editar${Classe}(PermissionRequiredMixin, UpdateView):
    permission_required = "${app}.change_${modelo}"
    model = ${Classe}
    form_class = ${Classe}Form
    template_name = "${app}/${modelo}_formulario.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = f"Editar ${rotulo_min}"
        ctx["trilha"] = [("${rotulo_plural}", reverse("${app}:${modelo}_listar")), (str(self.object), self.object.get_absolute_url()), ("Editar", None)]
        ctx["url_cancelar"] = self.object.get_absolute_url()
        return ctx

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, "${rotulo} atualizad${o} com sucesso.")
        return resposta


class Detalhe${Classe}(PermissionRequiredMixin, DetailView):
    permission_required = "${app}.view_${modelo}"
    model = ${Classe}
    template_name = "${app}/${modelo}_detalhe.html"
    context_object_name = "objeto"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = str(self.object)
        ctx["trilha"] = [("${rotulo_plural}", reverse("${app}:${modelo}_listar")), (str(self.object), None)]
        ctx["campos"] = [
${campos_detalhe}
        ]
        return ctx


class Excluir${Classe}(PermissionRequiredMixin, DeleteView):
    permission_required = "${app}.delete_${modelo}"
    model = ${Classe}
    template_name = "${app}/${modelo}_confirmar_exclusao.html"
    success_url = reverse_lazy("${app}:${modelo}_listar")
    context_object_name = "objeto"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = "Excluir ${rotulo_min}"
        ctx["trilha"] = [("${rotulo_plural}", reverse("${app}:${modelo}_listar")), (str(self.object), self.object.get_absolute_url()), ("Excluir", None)]
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "${rotulo} excluíd${o}.")
        return super().form_valid(form)
''')

T_URLS = Template('''from django.urls import path

from . import views

app_name = "${app}"

urlpatterns = [
${rotas}
]
''')

T_ROTAS = Template('''    path("${prefixo}", views.Listar${Classe}.as_view(), name="${modelo}_listar"),
    path("${prefixo}novo/", views.Criar${Classe}.as_view(), name="${modelo}_novo"),
    path("${prefixo}<int:pk>/", views.Detalhe${Classe}.as_view(), name="${modelo}_detalhe"),
    path("${prefixo}<int:pk>/editar/", views.Editar${Classe}.as_view(), name="${modelo}_editar"),
    path("${prefixo}<int:pk>/excluir/", views.Excluir${Classe}.as_view(), name="${modelo}_excluir"),''')

T_ADMIN = Template('''from django.contrib import admin

from .models import ${classes}

${registros}
''')

T_TESTS = Template('''"""Testes gerados: as telas respondem e passam no verificador estrutural. Amplie com regras de negócio."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def usuario(db):
    u = get_user_model().objects.create_superuser("teste", "t@t.br", "senha-forte-123")
    return u


@pytest.fixture
def cliente(client, usuario):
    client.force_login(usuario)
    return client

${testes}
''')

T_TESTE_MODELO = Template('''
def test_${modelo}_listar_responde(cliente):
    r = cliente.get(reverse("${app}:${modelo}_listar"))
    assert r.status_code == 200
    assert b"br-table" in r.content


def test_${modelo}_formulario_no_padrao_ds(cliente):
    r = cliente.get(reverse("${app}:${modelo}_novo"))
    assert r.status_code == 200
    assert b"br-input" in r.content or b"br-select" in r.content
    assert b"<select" not in r.content
''')

# ------------------------------------------------------------------ templates HTML

T_LISTAR = Template('''{% extends "base.html" %}
{% load dsgov %}
{% block titulo %}{{ titulo }}{% endblock %}
{% block conteudo %}
<div class="d-flex align-items-center mb-4">
  <h1 class="mb-0">{{ titulo }}</h1>
  {% if perms.${app}.add_${modelo} %}
  <div class="ml-auto"><a class="br-button primary" href="{{ url_novo }}"><i class="fas fa-plus mr-1" aria-hidden="true"></i>${novo} ${rotulo_min}</a></div>
  {% endif %}
</div>

<form class="row align-items-end mb-3" method="get" action="{{ request.path }}" role="search"
      hx-get="{{ request.path }}" hx-target="#listagem" hx-push-url="true" hx-trigger="submit, change delay:150ms">
  <div class="col-sm-12 col-md-5 mb-3">
    <div class="br-input has-icon">
      <label for="busca">Buscar</label>
      <div class="input-icon"><i class="fas fa-search" aria-hidden="true"></i></div>
      <input id="busca" name="q" type="search" value="{{ busca }}" placeholder="${placeholder_busca}"/>
      <button class="br-button circle small" type="submit" aria-label="Buscar"><i class="fas fa-search" aria-hidden="true"></i></button>
    </div>
  </div>
${filtros_html}
</form>

<div id="listagem">{% include "${app}/_${modelo}_tabela.html" %}</div>
{% endblock %}
''')

T_FILTRO = Template('''  <div class="col-sm-6 col-md-3 mb-3">
    <div class="br-select">
      <div class="br-input">
        <label for="filtro-${param}">${rotulo}</label>
        <input id="filtro-${param}" type="text" placeholder="Todos" autocomplete="off"/>
        <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger"><i class="fas fa-angle-down" aria-hidden="true"></i></button>
      </div>
      <div class="br-list" tabindex="0">
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="filtro-${param}-todos" name="${param}" type="radio" value=""{% if not request.GET.${param} %} checked="checked"{% endif %}/>
            <label for="filtro-${param}-todos">Todos</label>
          </div>
        </div>
        {% for valor, rotulo in opcoes_filtros.${param} %}
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="filtro-${param}-{{ forloop.counter }}" name="${param}" type="radio" value="{{ valor }}"{% if request.GET.${param} == valor|stringformat:"s" %} checked="checked"{% endif %}/>
            <label for="filtro-${param}-{{ forloop.counter }}">{{ rotulo }}</label>
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
''')

T_TABELA = Template('''{% load dsgov %}
{% include "dsgov/_filtros_ativos.html" %}
<div class="br-table" data-random="data-random">
  <div class="table-header">
    <div class="top-bar">
      <div class="table-title">{{ page_obj.paginator.count }} {% if page_obj.paginator.count == 1 %}registro{% else %}registros{% endif %}</div>
      <div class="actions-trigger text-nowrap">
        <button class="br-button circle" type="button" id="densidade-${modelo}" title="Ver mais opções" data-toggle="dropdown" data-target="densidade-${modelo}-lista" aria-label="Definir densidade da tabela" aria-haspopup="true"><i class="fas fa-ellipsis-v" aria-hidden="true"></i></button>
        <div class="br-list" id="densidade-${modelo}-lista" role="menu" aria-labelledby="densidade-${modelo}" hidden="hidden">
          <button class="br-item" type="button" data-density="small" role="menuitem">Densidade alta</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="medium" role="menuitem">Densidade média</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="large" role="menuitem">Densidade baixa</button>
        </div>
      </div>
    </div>
  </div>
  <table>
    <caption class="sr-only">{{ titulo }}</caption>
    <thead>
      <tr>
        {% for col in colunas %}
        <th scope="col"{% if col.tipo == "moeda" or col.tipo == "numero" or col.tipo == "percentual" %} class="dsgov-numero"{% endif %}>{% if col.ordenar %}{% ordenar_por col.ordenar col.rotulo %}{% else %}{{ col.rotulo }}{% endif %}</th>
        {% endfor %}
        <th scope="col" class="dsgov-acoes"><span class="sr-only">Ações</span></th>
      </tr>
    </thead>
    <tbody>
      {% for objeto in objetos %}
      <tr>
        {% for col in colunas %}
        <td data-th="{{ col.rotulo }}"{% if col.tipo == "moeda" or col.tipo == "numero" or col.tipo == "percentual" %} class="dsgov-numero"{% endif %}>
          {% if col.tipo == "status" %}{% with chave=objeto|atributo:col.chave %}{% tag_status objeto|atributo:col.campo chave %}{% endwith %}{% elif forloop.first %}<a href="{{ objeto.get_absolute_url }}">{{ objeto|exibir:col }}</a>{% else %}{{ objeto|exibir:col }}{% endif %}
        </td>
        {% endfor %}
        <td class="dsgov-acoes">
          <a class="br-button circle small" href="{{ objeto.get_absolute_url }}" aria-label="Visualizar {{ objeto }}"><i class="fas fa-eye" aria-hidden="true"></i></a>
          {% if perms.${app}.change_${modelo} %}<a class="br-button circle small" href="{% url '${app}:${modelo}_editar' objeto.pk %}" aria-label="Editar {{ objeto }}"><i class="fas fa-pen" aria-hidden="true"></i></a>{% endif %}
          {% if perms.${app}.delete_${modelo} %}<a class="br-button circle small" href="{% url '${app}:${modelo}_excluir' objeto.pk %}" aria-label="Excluir {{ objeto }}"><i class="fas fa-trash" aria-hidden="true"></i></a>{% endif %}
        </td>
      </tr>
      {% empty %}
      <tr><td colspan="{{ colunas|length|add:1 }}" class="text-center py-4">Nenhum registro encontrado{% if filtros_ativos %} com os filtros atuais{% endif %}.</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% if is_paginated or page_obj.paginator.count > 10 %}
  <div class="table-footer">{% paginacao page_obj "#listagem" %}</div>
  {% endif %}
</div>
''')

T_FORMULARIO = Template('''{% extends "base.html" %}
{% block titulo %}{{ titulo }}{% endblock %}
{% block conteudo %}
<div class="d-flex align-items-center mb-4">
  <h1 class="mb-0">{{ titulo }}</h1>
</div>
<div class="row">
  <div class="col-md-8">
    <form method="post" enctype="multipart/form-data" novalidate>
      {% csrf_token %}
      {{ form }}
      {% include "dsgov/_acoes_formulario.html" %}
    </form>
  </div>
</div>
{% endblock %}
''')

T_DETALHE = Template('''{% extends "base.html" %}
{% load dsgov %}
{% block titulo %}{{ titulo }}{% endblock %}
{% block conteudo %}
<div class="d-flex align-items-center mb-4">
  <h1 class="mb-0">{{ titulo }}</h1>
  <div class="ml-auto">
    {% if perms.${app}.delete_${modelo} %}<a class="br-button secondary mr-2" href="{% url '${app}:${modelo}_excluir' objeto.pk %}"><i class="fas fa-trash mr-1" aria-hidden="true"></i>Excluir</a>{% endif %}
    {% if perms.${app}.change_${modelo} %}<a class="br-button primary" href="{% url '${app}:${modelo}_editar' objeto.pk %}"><i class="fas fa-pen mr-1" aria-hidden="true"></i>Editar</a>{% endif %}
  </div>
</div>
<div class="row">
  <div class="col-md-8">
    <div class="br-card">
      <div class="card-content">
        <dl class="dsgov-detalhe row mb-0">
          {% for campo in campos %}
          <div class="{% if campo.largo %}col-12{% else %}col-sm-6{% endif %}">
            <dt>{{ campo.rotulo }}</dt>
            <dd>{% if campo.tipo == "status" %}{% with chave=objeto|atributo:campo.chave %}{% tag_status objeto|atributo:campo.campo chave %}{% endwith %}{% else %}{{ objeto|exibir:campo|linebreaksbr }}{% endif %}</dd>
          </div>
          {% endfor %}
        </dl>
      </div>
    </div>
    <p class="text-down-01 text-gray-70 mt-3">Cadastrado em {{ objeto.criado_em|data_br }} · Atualizado em {{ objeto.atualizado_em|data_br }}</p>
    <a class="br-button" href="{% url '${app}:${modelo}_listar' %}"><i class="fas fa-arrow-left mr-1" aria-hidden="true"></i>Voltar</a>
  </div>
</div>
{% endblock %}
''')

T_EXCLUIR = Template('''{% extends "base.html" %}
{% block titulo %}{{ titulo }}{% endblock %}
{% block conteudo %}
<div class="d-flex align-items-center mb-4">
  <h1 class="mb-0">{{ titulo }}</h1>
</div>
<div class="row">
  <div class="col-md-8">
    <div class="br-message warning mb-4">
      <div class="icon"><i class="fas fa-exclamation-triangle fa-lg" aria-hidden="true"></i></div>
      <div class="content" role="alert"><span class="message-title">Esta ação não pode ser desfeita.</span><span class="message-body"> O registro <strong>{{ objeto }}</strong> será excluído permanentemente.</span></div>
    </div>
    <form method="post">
      {% csrf_token %}
      <div class="dsgov-acoes-formulario">
        <a class="br-button" href="{{ objeto.get_absolute_url }}">Cancelar</a>
        <button class="br-button primary" type="submit"><i class="fas fa-trash mr-1" aria-hidden="true"></i>Confirmar exclusão</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
''')


# ------------------------------------------------------------------ geração

def gerar_app(raiz: Path, sistema: dict, app: dict, forcar: bool):
    nome = slug(app["nome"])
    app["nome"] = nome
    rotulo_app = app.get("rotulo", nome.capitalize())
    pasta = raiz / "apps" / nome
    tpl = pasta / "templates" / nome
    print(f"\n== app {nome} ({rotulo_app})")

    opcoes_py, modelos_py, forms_py, views_py, rotas, registros, testes = [], [], [], [], [], [], []
    classes = []
    imports_externos = set()
    itens_menu = []

    for m in app["modelos"]:
        Classe = classe(m["nome"])
        modelo = slug(m["nome"])
        rotulo = m.get("rotulo", Classe)
        rotulo_plural = m.get("rotulo_plural", rotulo + "s")
        rotulo_min = rotulo.lower()
        campos = m["campos"]
        classes.append(Classe)
        nomes_campos = [c["nome"] for c in campos]
        campo_str = m.get("campo_str") or next((c["nome"] for c in campos if c.get("tipo", "texto") in ("texto", "fk")), nomes_campos[0])

        # choices
        metodos_status = ""
        for c in campos:
            if c.get("tipo") == "escolha":
                linhas = "\n".join(f'    {slug(str(v)).upper()} = "{v}", "{r}"' for v, r in c["opcoes"])
                opcoes_py.append(f"class {classe(c['nome'])}Opcoes(models.TextChoices):\n{linhas}\n")
                if c.get("status"):
                    metodos_status += T_STATUS.substitute(
                        campo=c["nome"], CAMPO=c["nome"].upper(), mapa=", ".join(f"{k}→{v}" for k, v in c["status"].items()),
                        dict_status="{" + ", ".join(f'"{k}": "{v}"' for k, v in c["status"].items()) + "}")

        lst = m.get("listagem", {})
        ordenacao = lst.get("ordenacao", f"-{'criado_em'}")
        modelos_py.append(T_MODELO.substitute(
            Classe=Classe, campos="\n".join(campo_model(c, app) for c in campos), rotulo=rotulo,
            rotulo_plural=rotulo_plural, ordenacao=ordenacao, campo_str=campo_str, app=nome, modelo=modelo,
            metodos_status=metodos_status))

        # forms
        widgets = []
        for c in campos:
            t = c.get("tipo", "texto")
            attrs = {}
            if t in INPUT_TYPE:
                attrs["type"] = INPUT_TYPE[t]
            if t in ("moeda", "decimal", "percentual"):
                attrs["step"] = "0.01"
            if c.get("col"):
                attrs["col"] = c["col"]
            elif t in ("data", "data_hora", "moeda", "decimal", "inteiro", "percentual", "booleano", "cpf", "cnpj"):
                attrs["col"] = "col-md-6"
            if t == "texto_longo":
                attrs["rows"] = 4
            if attrs:
                w = {"texto_longo": "forms.Textarea", "data": "forms.DateInput", "data_hora": "forms.DateTimeInput",
                     "escolha": "forms.Select", "fk": "forms.Select", "booleano": "forms.CheckboxInput"}.get(t, "forms.TextInput")
                if t in ("inteiro", "decimal", "moeda", "percentual"):
                    w = "forms.NumberInput"
                if t == "email":
                    w = "forms.EmailInput"
                if t == "arquivo":
                    w = "forms.ClearableFileInput"
                a = ", ".join(f'"{k}": {repr(v)}' for k, v in attrs.items())
                extra = ', format="%Y-%m-%d"' if t == "data" else (', format="%Y-%m-%dT%H:%M"' if t == "data_hora" else "")
                widgets.append(f'            "{c["nome"]}": {w}(attrs={{{a}}}{extra}),')
        forms_py.append(T_FORM.substitute(Classe=Classe, fields=", ".join(f'"{n}"' for n in nomes_campos), widgets="\n".join(widgets)))

        # listagem
        col_nomes = lst.get("colunas", nomes_campos[:5])
        por_nome = {c["nome"]: c for c in campos}
        colunas = []
        ordenacoes = {}
        select_related = []
        for cn in col_nomes:
            base = cn.split(".")[0]
            c = por_nome.get(base, {"nome": cn, "rotulo": cn})
            t = c.get("tipo", "texto")
            tipo_col = TIPOS.get(t, ("", {}, "texto"))[2]
            campo_tpl = cn if "." in cn else (f"get_{cn}_display" if t == "escolha" else cn)
            entrada = {"campo": campo_tpl, "rotulo": c.get("rotulo", cn.replace("_", " ").capitalize()), "tipo": tipo_col, "ordenar": slug(cn)}
            if t == "escolha" and c.get("status"):
                entrada["tipo"] = "status"
                entrada["chave"] = f"{cn}_chave"
            ordenacoes[slug(cn)] = lookup(cn) if "." in cn or t != "fk" else f"{cn}__{por_nome.get(cn, {}).get('exibir', 'pk')}"
            if t == "fk":
                select_related.append(base)
                if "." not in cn:
                    entrada["campo"] = cn  # __str__ do relacionado
            colunas.append("        " + repr(entrada) + ",")
        busca = [lookup(b) for b in lst.get("busca", [c["nome"] for c in campos if c.get("tipo", "texto") == "texto"][:2])]
        filtros = {}
        opcoes_filtros = []
        filtros_html = []
        for f in lst.get("filtros", []):
            c = por_nome[f]
            tipo_f = c.get("tipo", "texto")
            if tipo_f not in ("escolha", "fk", "booleano"):
                raise SystemExit(f"filtro '{f}' em {m['nome']}: só campos escolha, fk ou booleano podem ser filtro")
            filtros[f] = f if tipo_f in ("escolha", "booleano") else f"{f}_id"
            if tipo_f == "booleano":
                opcoes_filtros.append(f'            "{f}": [("True", "Sim"), ("False", "Não")],')
            elif tipo_f == "escolha":
                opcoes_filtros.append(f'            "{f}": {classe(f)}Opcoes.choices,')
                if f"{classe(f)}Opcoes" not in classes:
                    classes.append(f"{classe(f)}Opcoes")
            else:
                para = c["para"].split(".")[-1]
                opcoes_filtros.append(f'            "{f}": [(o.pk, str(o)) for o in {para}.objects.all()[:200]],')
                if "." in c["para"]:
                    outro_app = c["para"].split(".")[0]
                    imports_externos.add(f"from apps.{outro_app}.models import {para}")
                elif para not in classes:
                    classes.append(para)
            filtros_html.append(T_FILTRO.substitute(param=f, rotulo=c.get("rotulo", f.capitalize())))
        campos_detalhe = []
        for c in m.get("detalhe", nomes_campos):
            cc = por_nome[c]
            t = cc.get("tipo", "texto")
            entrada = {"campo": f"get_{c}_display" if t == "escolha" else c, "rotulo": cc.get("rotulo", c.capitalize()),
                       "tipo": TIPOS[t][2], "largo": t == "texto_longo"}
            if t == "escolha" and cc.get("status"):
                entrada["tipo"], entrada["chave"] = "status", f"{c}_chave"
            campos_detalhe.append("            " + repr(entrada) + ",")

        genero = m.get("genero", "f")
        novo, o = ("Novo", "o") if genero == "m" else ("Nova", "a")
        views_py.append(T_VIEWS_MODELO.substitute(
            Classe=Classe, app=nome, modelo=modelo, rotulo=rotulo, rotulo_plural=rotulo_plural, rotulo_min=rotulo_min, novo=novo, o=o,
            busca=", ".join(f'"{b}"' for b in busca), ordenacoes=", ".join(f'"{k}": "{v}"' for k, v in ordenacoes.items()),
            ordenacao=ordenacao, filtros=", ".join(f'"{k}": "{v}"' for k, v in filtros.items()), colunas="\n".join(colunas),
            select_related=f".select_related({', '.join(repr(s) for s in select_related)})" if select_related else "",
            opcoes_filtros="\n".join(opcoes_filtros), campos_detalhe="\n".join(campos_detalhe)))
        prefixo = "" if len(app["modelos"]) == 1 else f"{modelo}/"
        rotas.append(T_ROTAS.substitute(prefixo=prefixo, Classe=Classe, modelo=modelo))
        registros.append(f"admin.site.register({Classe})")
        testes.append(T_TESTE_MODELO.substitute(app=nome, modelo=modelo))
        itens_menu.append((rotulo_plural, f"{nome}:{modelo}_listar", f"{nome}.view_{modelo}"))

        placeholder = ", ".join(por_nome.get(b.split(".")[0], {}).get("rotulo", b) for b in lst.get("busca", busca)).lower()
        escrever(tpl / f"{modelo}_listar.html", T_LISTAR.substitute(app=nome, modelo=modelo, rotulo_min=rotulo_min, novo=novo,
                 placeholder_busca=f"Buscar por {placeholder}" if placeholder else "Buscar", filtros_html="".join(filtros_html)), forcar)
        escrever(tpl / f"_{modelo}_tabela.html", T_TABELA.substitute(app=nome, modelo=modelo), forcar)
        escrever(tpl / f"{modelo}_formulario.html", T_FORMULARIO.substitute(), forcar)
        escrever(tpl / f"{modelo}_detalhe.html", T_DETALHE.substitute(app=nome, modelo=modelo), forcar)
        escrever(tpl / f"{modelo}_confirmar_exclusao.html", T_EXCLUIR.substitute(), forcar)

    escrever(pasta / "__init__.py", "", forcar)
    escrever(pasta / "apps.py", T_APPS.substitute(Classe=classe(nome), app=nome, rotulo=rotulo_app), forcar)
    escrever(pasta / "models.py", T_MODELS.substitute(rotulo=rotulo_app, opcoes="\n".join(opcoes_py), modelos="\n\n".join(modelos_py)), forcar)
    modelos_locais = [classe(m["nome"]) for m in app["modelos"]]
    escrever(pasta / "forms.py", T_FORMS.substitute(rotulo=rotulo_app, classes=", ".join(modelos_locais), forms="\n\n".join(forms_py)), forcar)
    escrever(pasta / "views.py", T_VIEWS.substitute(rotulo=rotulo_app, forms_import=", ".join(f"{c}Form" for c in modelos_locais),
             classes=", ".join(dict.fromkeys(classes)), views="\n".join(views_py),
             imports_externos="\n".join(sorted(imports_externos))), forcar)
    escrever(pasta / "urls.py", T_URLS.substitute(app=nome, rotas="\n".join(rotas)), forcar)
    escrever(pasta / "admin.py", T_ADMIN.substitute(classes=", ".join(modelos_locais), registros="\n".join(registros)), forcar)
    escrever(pasta / "tests.py", T_TESTS.substitute(testes="".join(testes)), forcar)
    (pasta / "migrations").mkdir(exist_ok=True)
    escrever(pasta / "migrations" / "__init__.py", "", forcar)

    # registro no projeto
    inserir_marcador(raiz / "config/settings/base.py", "# __APPS__", f'"apps.{nome}",')
    inserir_marcador(raiz / "config/urls.py", "# __URLS__", f'path("{nome}/", include("apps.{nome}.urls")),')
    icone = app.get("icone", "fas fa-folder")
    if len(itens_menu) == 1:
        r, u, p = itens_menu[0]
        linha = f'{{"rotulo": "{r}", "icone": "{icone}", "url": reverse("{u}"), "permissao": "{p}"}},'
    else:
        filhos = ", ".join(f'{{"rotulo": "{r}", "url": reverse("{u}"), "permissao": "{p}"}}' for r, u, p in itens_menu)
        linha = f'{{"rotulo": "{rotulo_app}", "icone": "{icone}", "filhos": [{filhos}]}},'
    inserir_marcador(raiz / "core/menu.py", "# __MENU__", linha)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raiz", type=Path)
    ap.add_argument("yaml", type=Path)
    ap.add_argument("--app", help="gera só este app")
    ap.add_argument("--forcar", action="store_true", help="sobrescreve arquivos existentes")
    ap.add_argument("--sem-migracoes", action="store_true")
    args = ap.parse_args()
    raiz = args.raiz.resolve()
    sistema = yaml.safe_load(args.yaml.read_text(encoding="utf-8"))
    for app in sistema.get("apps", []):
        if args.app and slug(app["nome"]) != slug(args.app):
            continue
        gerar_app(raiz, sistema, app, args.forcar)
    if not args.sem_migracoes:
        print("\n== makemigrations")
        r = subprocess.run([sys.executable, "manage.py", "makemigrations"], cwd=raiz, check=False)
        if r.returncode != 0:
            print(f"AVISO: makemigrations falhou com o interpretador {sys.executable}. Rode este script com o Python "
                  "do projeto (venv com Django instalado) ou execute `python manage.py makemigrations` manualmente.")
    print("\nPróximos passos: python manage.py migrate · escrever regras de negócio em apps/<app>/forms.py e models.py ·"
          " rodar scripts/verificar.py antes de entregar.")


if __name__ == "__main__":
    main()
