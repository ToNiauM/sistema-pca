# Gerada por `python manage.py makemigrations catalogo` (Django 5.2.16) e
# renomeada de `0004_indicereajuste.py` para um nome descritivo (Fase
# 36/, spec §2.3); o `RunPython` de seed abaixo foi
# ACRESCENTADO à mão depois da geração (edição permitida pelo plano — só o
# `CreateModel` acima é saída literal do Django).
#
# Valores oficiais do IBGE para IPCA/INPC 2024 (variação acumulada no ano) e
# fallback documentado para 2025: sem
# certeza do valor oficial fechado no momento desta migração, usa-se
# META_BC (3,00) como placeholder para as duas linhas de 2025 — corrigir
# quando o valor oficial do IBGE estiver disponível. `reverse_code = noop`
# (nunca migração reversa que apaga dado).
from decimal import Decimal

from django.db import migrations, models


def semear_indices(apps, schema_editor):
    IndiceReajuste = apps.get_model("catalogo", "IndiceReajuste")
    db = schema_editor.connection.alias

    # IBGE, IPCA acumulado 2024
    IndiceReajuste.objects.using(db).get_or_create(
        indice="IPCA", ano=2024, defaults={"percentual": Decimal("4.83")},
    )
    # IBGE, INPC acumulado 2024
    IndiceReajuste.objects.using(db).get_or_create(
        indice="INPC", ano=2024, defaults={"percentual": Decimal("4.77")},
    )
    # IPCA/INPC 2025 não confirmado — fallback META_BC documentado em;
    # corrigir quando o valor oficial
    # do IBGE estiver disponível.
    IndiceReajuste.objects.using(db).get_or_create(
        indice="IPCA", ano=2025, defaults={"percentual": Decimal("3.00")},
    )
    IndiceReajuste.objects.using(db).get_or_create(
        indice="INPC", ano=2025, defaults={"percentual": Decimal("3.00")},
    )
    for ano in range(2026, 2032):
        IndiceReajuste.objects.using(db).get_or_create(
            indice="META_BC", ano=ano, defaults={"percentual": Decimal("3.00")},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0003_ordenacao_ptbr'),
    ]

    operations = [
        migrations.CreateModel(
            name='IndiceReajuste',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indice', models.CharField(choices=[('IPCA', 'IPCA'), ('INPC', 'INPC'), ('IGP-M', 'IGP-M'), ('META_BC', 'Meta Bacen')], max_length=10, verbose_name='índice')),
                ('ano', models.PositiveSmallIntegerField(verbose_name='ano')),
                ('percentual', models.DecimalField(decimal_places=2, max_digits=6, verbose_name='percentual (%)')),
            ],
            options={
                'verbose_name': 'índice de reajuste',
                'verbose_name_plural': 'índices de reajuste',
                'ordering': ['-ano', 'indice'],
                'constraints': [models.UniqueConstraint(fields=('indice', 'ano'), name='catalogo_indicereajuste_indice_ano_unico')],
            },
        ),
        migrations.RunPython(semear_indices, reverse_code=migrations.RunPython.noop),
    ]
