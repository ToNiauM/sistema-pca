"""Renderer de formulários no padrão DSGov.

Com FORM_RENDERER apontando para cá, `{{ form }}` e `{{ form.campo }}` produzem o HTML canônico do DS:
br-input (texto, número, data, e-mail, senha), br-textarea, br-select (radios/checkboxes dentro de
br-list, como no exemplo oficial), br-checkbox, br-radio, br-upload, com rótulo, texto de ajuda e
mensagem de erro (`feedback danger`) nos lugares certos e aria-describedby ligado.
"""

from django.forms.renderers import TemplatesSetting


class DSGovFormRenderer(TemplatesSetting):
    form_template_name = "dsgov/forms/form.html"
    field_template_name = "dsgov/forms/field.html"
