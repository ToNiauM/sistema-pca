"""Testes de `apps.pca.sei.pdf` — módulo puro de leitura
de PDF externo "Contrato...". `construir_pdf_sintetico`/`TEXTO_ITEM_58`/
`ASSINATURAS_ITEM_58` são PÚBLICOS (não `_`-prefixados) de propósito —
`test_sei_coletor.py` (desta quick) importa e reusa o mesmo
construtor, nunca reescreve a lógica de gerar PDF. Nenhum teste deste
arquivo usa o PDF real do item 58 (dados pessoais) — todo texto/CNPJ/nome é
sintético, inventado para cobrir exatamente os padrões do `<behavior>` do
plano."""

import io
import unittest

import pypdf
from django.test import SimpleTestCase

from apps.pca.sei.pdf import (
    classificar_papel,
    extrair_assinaturas_digitais,
    extrair_texto,
    pertence_ao_processo,
    processar,
)

PROCESSO_ITEM_58 = "90796110000024.000002/2026-69"

# Preâmbulo + cláusulas sintéticas, inspiradas na estrutura real do item 58
# (CONTRATO Nº 25/2026, CFC x BELIZE COMPANY AUTO POSTO LTDA) — nomes/CNPJ
# inventados para o teste, nunca os dados reais do item. Texto todo em ASCII
# (sem acentuação) porque o construtor de PDF usa fonte Helvetica padrão via
# bytes latin-1 — as regex de `extracao.py` toleram "e" no lugar de "é/ê"
# (classes de caracteres `[eé]`/`[eê]`), então nenhum comportamento muda.
TEXTO_ITEM_58 = [
    "CONTRATO N. 25/2026",
    "",
    "CONTRATO QUE ENTRE SI CELEBRAM O CONSELHO FEDERAL DE CONTABILIDADE E A EMPRESA",
    "BELIZE COMPANY AUTO POSTO LTDA, NA FORMA ABAIXO.",
    "",
    "O CONSELHO FEDERAL DE CONTABILIDADE, CNPJ 33.618.570/0001-07 (CONTRATANTE),",
    "representado por WEBERTH FERNANDES, e a empresa BELIZE COMPANY AUTO POSTO LTDA,",
    "inscrita no CNPJ 31.238.552/0001-66, com sede em Brasilia (CONTRATADA),",
    "representada por CLEVER MORATO AXHCAR, firmam o presente contrato referente ao",
    f"processo SEI {PROCESSO_ITEM_58}.",
    "",
    "CLAUSULA PRIMEIRA - DO OBJETO",
    "1.1. Constitui objeto deste contrato o fornecimento de combustiveis.",
    "",
    "CLAUSULA SEGUNDA - DA VIGENCIA",
    "2.1. O prazo de vigencia da contratacao e de 12 (doze) meses, contados da",
    "data de assinatura.",
    "",
    "CLAUSULA QUINTA - DO VALOR",
    "5.1. O valor total da contratacao e de R$ 39.141,20 (trinta e nove mil e",
    "cento e quarenta e um reais e vinte centavos).",
    "",
    "A autenticidade deste documento pode ser conferida no site",
    "https://sei.cfc.org.br/sei/controlador_externo.php verificador.",
]

# Assinaturas digitais embutidas (AcroForm) — WEBERTH FERNANDES (CFC) e
# CLEVER MORATO AXHCAR (contratado), mesmos nomes/datas citados no CONTEXT
# do plano (`D:AAAAMMDDHHMMSS-03'00'`, CPF sintético anexado após ":").
ASSINATURAS_ITEM_58 = [
    ("WEBERTH FERNANDES:85681113191", "D:20260520152016-03'00'"),
    ("CLEVER MORATO AXHCAR:12345678901", "D:20260520161745-03'00'"),
]


def _escapar_pdf_texto(s: str) -> bytes:
    """Escapa parênteses/barra invertida para uso dentro de uma string
    literal `(...)` de um content stream PDF — cada linha vira seu próprio
    `Tj`, isolado, então mesmo parênteses balanceados (ex.: "(doze)") são
    escapados por segurança."""
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return s.encode("latin-1")


def _content_stream(linhas: list[str]) -> bytes:
    """Um `Tj` por linha, posicionamento absoluto na primeira (`Td`) e
    relativo nas demais (`0 -14 TD`, desce uma linha a cada chamada) —
    suficiente para `pypdf.extract_text()` separar as linhas por `"\\n"`."""
    partes = [b"BT", b"/F1 10 Tf", b"50 750 Td"]
    primeiro = True
    for linha in linhas:
        if not primeiro:
            partes.append(b"0 -14 TD")
        partes.append(b"(" + _escapar_pdf_texto(linha) + b") Tj")
        primeiro = False
    partes.append(b"ET")
    return b"\n".join(partes)


def construir_pdf_sintetico(
    linhas: list[str] | None = None,
    assinaturas: list[tuple[str, str]] | None = None,
) -> bytes:
    """Monta um PDF 1.7 mínimo, válido, à mão (cabeçalho, objetos, xref,
    trailer) — sem depender da API de alto nível de `pypdf.PdfWriter`
    (que não tem um jeito direto de anexar campos `/Sig` com `/V` prontos).
    `linhas` (default `TEXTO_ITEM_58`): cada uma vira um `Tj` na página
    única. `assinaturas` (default `None` = sem `/AcroForm` nenhum): lista
    de `(nome_com_cpf, data_pdf)` — cada par gera um campo `/FT /Sig` no
    `/AcroForm` da raiz, com `/V` apontando para um dicionário de
    assinatura `{"/Name": nome_com_cpf, "/M": data_pdf}`.

    Validado isoladamente (round-trip `pypdf.PdfReader`) antes de qualquer
    asserção contra `apps.pca.sei.pdf` — ver CONTEXT do plano."""
    if linhas is None:
        linhas = TEXTO_ITEM_58
    conteudo = _content_stream(linhas)

    partes_assinatura: list[tuple[int, int, str, str]] = []
    campos_refs: list[int] = []
    prox_obj = 7
    if assinaturas:
        for nome_cpf, data_m in assinaturas:
            campo_num = prox_obj
            sig_num = prox_obj + 1
            prox_obj += 2
            campos_refs.append(campo_num)
            partes_assinatura.append((campo_num, sig_num, nome_cpf, data_m))

    offsets: dict[int, int] = {}
    buf = bytearray()
    buf += b"%PDF-1.7\n"

    def _add_obj(num: int, body: bytes) -> None:
        offsets[num] = len(buf)
        buf.extend(f"{num} 0 obj\n".encode("ascii"))
        buf.extend(body)
        buf.extend(b"\nendobj\n")

    acroform_dict = b""
    if partes_assinatura:
        campos_str = " ".join(f"{n} 0 R" for n in campos_refs)
        acroform_dict = f"<< /Fields [{campos_str}] /SigFlags 3 >>".encode("ascii")

    catalog_extra = b" /AcroForm 6 0 R" if partes_assinatura else b""
    _add_obj(1, b"<< /Type /Catalog /Pages 2 0 R" + catalog_extra + b" >>")
    _add_obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    _add_obj(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    )
    _add_obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    offsets[5] = len(buf)
    buf.extend(b"5 0 obj\n")
    buf.extend(f"<< /Length {len(conteudo)} >>\nstream\n".encode("ascii"))
    buf.extend(conteudo)
    buf.extend(b"\nendstream\nendobj\n")

    if partes_assinatura:
        _add_obj(6, acroform_dict)
        for campo_num, sig_num, nome_cpf, data_m in partes_assinatura:
            _add_obj(
                campo_num,
                f"<< /FT /Sig /T (Signature{campo_num}) /V {sig_num} 0 R >>".encode("ascii"),
            )
            nome_escapado = _escapar_pdf_texto(nome_cpf).decode("latin-1")
            data_escapada = _escapar_pdf_texto(data_m).decode("latin-1")
            _add_obj(
                sig_num,
                (
                    "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
                    f"/Name ({nome_escapado}) /M ({data_escapada}) >>"
                ).encode("latin-1"),
            )

    maior_obj = max(offsets.keys())
    xref_offset = len(buf)
    buf.extend(f"xref\n0 {maior_obj + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for n in range(1, maior_obj + 1):
        off = offsets.get(n)
        if off is None:
            buf.extend(b"0000000000 00000 f \n")
        else:
            buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(b"trailer\n")
    buf.extend(f"<< /Size {maior_obj + 1} /Root 1 0 R >>\n".encode("ascii"))
    buf.extend(f"startxref\n{xref_offset}\n%%EOF".encode("ascii"))
    return bytes(buf)


# Processo/texto/assinaturas sintéticos para o Termo Aditivo em PDF (quick) — inspirados no CONTEXT do plano (item 89, seguro de
# veiculos), mas CNPJ/razao social/numero de processo todos INVENTADOS,
# nunca os dados reais. A clausula de prorrogacao usa a forma "por mais N
# meses, a partir de DD/MM/AAAA" (extrator `extrair_prorrogacao`, forma 2)
# em vez da forma "a partir de X ate Y" (forma 1) citada no texto do plano
# porque essa segunda forma exige o caractere acentuado "até" no corpo do
# PDF — o construtor sintetico usa a fonte Helvetica padrao (sem
# `/Encoding` no dicionario da fonte, que o pypdf le como StandardEncoding)
# via bytes latin-1, e o byte de "é" nao faz o round-trip corretamente
# nessa combinacao (confirmado empiricamente: "até" vira "atØ" na extracao
# de texto) — mesma razao, documentada no topo do arquivo, pela qual
# TEXTO_ITEM_58 e inteiramente ASCII. A forma "por mais N meses" nao usa
# nenhum caractere acentuado e produz os MESMOS inicio/fim desejados pelo
# <behavior> do plano (26/07/2026 + 12 meses - 1 dia = 25/07/2027).
PROCESSO_ITEM_89 = "90796110000024.000099/2026-10"

TEXTO_ADITIVO_ITEM_89 = [
    "TERMO ADITIVO N. 3 AO CONTRATO N. 26/2023",
    "",
    "TERMO ADITIVO QUE ENTRE SI CELEBRAM O CONSELHO FEDERAL DE CONTABILIDADE",
    "E A EMPRESA SEGURADORA EXEMPLO VEICULOS LTDA, NA FORMA ABAIXO.",
    "",
    "O CONSELHO FEDERAL DE CONTABILIDADE, CNPJ 33.618.570/0001-07 (CONTRATANTE),",
    "representado por MARIA EXEMPLO SILVA, e a empresa SEGURADORA EXEMPLO",
    "VEICULOS LTDA, inscrita no CNPJ 12.345.678/0001-95, com sede em Brasilia",
    "(CONTRATADA), representada por JOAO EXEMPLO SOUZA, firmam o presente",
    f"termo aditivo referente ao processo SEI {PROCESSO_ITEM_89}.",
    "",
    "CLAUSULA PRIMEIRA - DA PRORROGACAO",
    "1.1. Fica prorrogado o prazo de vigencia do contrato por mais 12 (doze)",
    "meses, a partir de 26/07/2026.",
    "",
    "CLAUSULA SEGUNDA - DO VALOR",
    "2.1. O valor mensal do contrato passa a ser de R$ 4.104,00 (quatro mil",
    "e cento e quatro reais).",
    "",
    "A autenticidade deste documento pode ser conferida no site",
    "https://sei.cfc.org.br/sei/controlador_externo.php verificador.",
]

ASSINATURAS_ADITIVO_ITEM_89 = [
    ("MARIA EXEMPLO SILVA:11122233344", "D:20260724100000-03'00'"),
    ("JOAO EXEMPLO SOUZA:55566677788", "D:20260724110000-03'00'"),
]


def _linhas_outro_orgao() -> list[str]:
    """Mesmo preâmbulo do item 58, mas citando o processo de OUTRO órgão —
    `pertence_ao_processo` deve recusar porque os dígitos do processo DESTE
    item nunca aparecem no texto."""
    linhas = list(TEXTO_ITEM_58)
    idx = next(i for i, l in enumerate(linhas) if PROCESSO_ITEM_58 in l)
    linhas[idx] = "processo SEI 23069.000001/2024-11."
    return linhas


class TestExtrairTexto(SimpleTestCase):
    def test_pdf_valido_extrai_texto_das_linhas(self):
        pdf_bytes = construir_pdf_sintetico()
        texto = extrair_texto(pdf_bytes)
        self.assertIsNotNone(texto)
        self.assertIn("CONTRATO N. 25/2026", texto)
        self.assertIn("CONSELHO FEDERAL DE CONTABILIDADE", texto)
        self.assertIn(PROCESSO_ITEM_58, texto)

    def test_pdf_corrompido_devolve_none_sem_lancar(self):
        self.assertIsNone(extrair_texto(b"isto nao e um PDF de verdade"))

    def test_pdf_com_stream_vazio_devolve_none(self):
        pdf_bytes = construir_pdf_sintetico(linhas=[""])
        self.assertIsNone(extrair_texto(pdf_bytes))

    def test_bytes_vazios_devolve_none(self):
        self.assertIsNone(extrair_texto(b""))


class TestPertenceAoProcesso(unittest.TestCase):
    def test_menciona_cfc_e_processo_devolve_true(self):
        texto = "O CONSELHO FEDERAL DE CONTABILIDADE... processo 90796110000024.000002/2026-69."
        self.assertTrue(pertence_ao_processo(texto, PROCESSO_ITEM_58))

    def test_tolera_variacao_de_pontuacao_no_numero(self):
        texto = "CONSELHO FEDERAL DE CONTABILIDADE processo 90796110000024 000002 2026 69"
        self.assertTrue(pertence_ao_processo(texto, PROCESSO_ITEM_58))

    def test_sem_mencao_ao_cfc_devolve_false(self):
        texto = f"Contrato de outro orgao, processo {PROCESSO_ITEM_58}."
        self.assertFalse(pertence_ao_processo(texto, PROCESSO_ITEM_58))

    def test_sem_numero_do_processo_devolve_false(self):
        texto = "O CONSELHO FEDERAL DE CONTABILIDADE celebra este contrato."
        self.assertFalse(pertence_ao_processo(texto, PROCESSO_ITEM_58))

    def test_numero_processo_none_devolve_false(self):
        texto = "O CONSELHO FEDERAL DE CONTABILIDADE celebra este contrato."
        self.assertFalse(pertence_ao_processo(texto, None))

    def test_texto_vazio_devolve_false(self):
        self.assertFalse(pertence_ao_processo("", PROCESSO_ITEM_58))
        self.assertFalse(pertence_ao_processo(None, PROCESSO_ITEM_58))


class TestClassificarPapel(unittest.TestCase):
    def test_nome_mais_proximo_de_contratante_e_cfc(self):
        texto = "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE), representado por FULANO DE TAL, assina."
        self.assertEqual(classificar_papel("FULANO DE TAL", texto), "cfc")

    def test_nome_mais_proximo_de_contratada_e_externo(self):
        texto = (
            "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE) e a empresa X "
            "(CONTRATADA), representada por FULANA DE TAL, assina."
        )
        self.assertEqual(classificar_papel("FULANA DE TAL", texto), "externo")

    def test_nome_ausente_do_texto_devolve_none(self):
        texto = "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE) assina."
        self.assertIsNone(classificar_papel("NINGUEM AQUI", texto))

    def test_sem_nenhum_marcador_antes_do_nome_devolve_none(self):
        texto = "FULANO DE TAL assina este documento, sem nenhuma qualificacao anterior."
        self.assertIsNone(classificar_papel("FULANO DE TAL", texto))

    def test_nome_ou_texto_vazio_devolve_none(self):
        self.assertIsNone(classificar_papel("", "qualquer texto"))
        self.assertIsNone(classificar_papel("FULANO", ""))

    def test_marcador_quebrado_por_espaco_ainda_classifica_externo(self):
        # "CONTRATADO" saiu do pypdf como "CONTRA TADO".
        texto = (
            "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE) e a empresa X "
            "(CONTRA TADO), representada por FULANA DE TAL, assina."
        )
        self.assertEqual(classificar_papel("FULANA DE TAL", texto), "externo")

    def test_nome_quebrado_por_quebra_de_linha_ainda_e_encontrado(self):
        # O próprio nome saiu com uma quebra de linha no meio.
        texto = (
            "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE), representado por "
            "FULANO DE \nTAL, assina."
        )
        self.assertEqual(classificar_papel("FULANO DE TAL", texto), "cfc")

    def test_cenario_combinado_marcador_e_nome_quebrados(self):
        # Replica a forma do achado real (PDF 1469673, item 89)
        # sem usar nenhum nome/CNPJ/processo real.
        texto = (
            "O CONSELHO FEDERAL DE CONTABILIDADE (CONTRATANTE), representado por "
            "FULANO DE TAL, e a empresa X (CONTRA TADO), representada por "
            "FULANA DE TAL e por CICLANO \nSILVA, assinam."
        )
        self.assertEqual(classificar_papel("FULANO DE TAL", texto), "cfc")
        self.assertEqual(classificar_papel("FULANA DE TAL", texto), "externo")
        self.assertEqual(classificar_papel("CICLANO SILVA", texto), "externo")


class TestExtrairAssinaturasDigitais(SimpleTestCase):
    def test_duas_assinaturas_no_acroform(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        assinaturas = extrair_assinaturas_digitais(pdf_bytes)
        self.assertEqual(len(assinaturas), 2)
        nomes = {a["nome"] for a in assinaturas}
        self.assertEqual(nomes, {"WEBERTH FERNANDES", "CLEVER MORATO AXHCAR"})
        por_nome = {a["nome"]: a for a in assinaturas}
        self.assertEqual(por_nome["WEBERTH FERNANDES"]["data"], "20/05/2026")
        self.assertEqual(por_nome["WEBERTH FERNANDES"]["hora"], "15:20")
        self.assertEqual(por_nome["CLEVER MORATO AXHCAR"]["data"], "20/05/2026")
        self.assertEqual(por_nome["CLEVER MORATO AXHCAR"]["hora"], "16:17")
        # CPF nunca sobrevive em `nome` (mesma disciplina do HTML).
        self.assertNotIn(":", por_nome["WEBERTH FERNANDES"]["nome"])

    def test_sem_acroform_devolve_lista_vazia(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=None)
        self.assertEqual(extrair_assinaturas_digitais(pdf_bytes), [])

    def test_pdf_corrompido_devolve_lista_vazia_sem_lancar(self):
        self.assertEqual(extrair_assinaturas_digitais(b"nao e pdf"), [])


class TestProcessarItem58Feliz(SimpleTestCase):
    """Caso feliz do CONTEXT do plano: PDF "item 58" com texto extraível,
    menciona CFC + o número do processo, 2 assinaturas digitais
    classificáveis — tudo extraído como se fosse um contrato HTML."""

    def setUp(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        self.resultado = processar(pdf_bytes, PROCESSO_ITEM_58)

    def test_conteudo_pdf(self):
        self.assertEqual(self.resultado["conteudo"], "pdf")

    def test_assinado_pelas_duas_partes(self):
        self.assertTrue(self.resultado["assinado_cfc"])
        self.assertTrue(self.resultado["assinado_externo"])

    def test_numero_no_corpo(self):
        self.assertEqual(self.resultado["numero_no_corpo"], "25/2026")

    def test_valor_contratado(self):
        self.assertEqual(self.resultado["valor"]["cifra"], "39.141,20")
        self.assertTrue(self.resultado["valor"]["confere"])

    def test_contratado(self):
        self.assertEqual(
            self.resultado["contratado"]["cnpj"], "31.238.552/0001-66"
        )
        self.assertEqual(
            self.resultado["contratado"]["razao_social"],
            "BELIZE COMPANY AUTO POSTO LTDA",
        )

    def test_vigencia_12_meses_desde_assinatura(self):
        from datetime import date

        self.assertEqual(self.resultado["vigencia"]["inicio"], date(2026, 5, 20))
        self.assertEqual(self.resultado["vigencia"]["fim"], date(2027, 5, 19))
        self.assertEqual(self.resultado["vigencia"]["forma"], "prazo_desde_assinatura")

    def test_ultima_assinatura(self):
        self.assertEqual(self.resultado["ultima_assinatura"], "20/05/2026 16:17")

    def test_prorrogacao_ausente_no_texto_vira_tudo_none(self):
        # Segundo item do <behavior> da o PDF do item
        # 58 (contrato, sem clausula de prorrogacao) ganha a chave NOVA
        # `prorrogacao`, sempre presente no envelope de sucesso, mas sem
        # casar nenhuma das duas formas de `extrair_prorrogacao` nesse
        # texto -> {"inicio": None, "fim": None}. Nenhuma chave JA existente
        # muda de valor (ver os testes acima, inalterados).
        self.assertEqual(self.resultado["prorrogacao"], {"inicio": None, "fim": None})


class TestProcessarTermoAditivoComProrrogacao(SimpleTestCase):
    """Primeiro item do <behavior> da PDF sintético de
    um Termo Aditivo de prorrogação (item 89), assinado pelas duas partes
    -> `processar()` devolve `conteudo="pdf"` e a chave nova `prorrogacao`
    com o mesmo resultado que `extracao.extrair_prorrogacao` produziria
    para este texto."""

    def setUp(self):
        pdf_bytes = construir_pdf_sintetico(
            linhas=TEXTO_ADITIVO_ITEM_89, assinaturas=ASSINATURAS_ADITIVO_ITEM_89
        )
        self.resultado = processar(pdf_bytes, PROCESSO_ITEM_89)

    def test_conteudo_pdf(self):
        self.assertEqual(self.resultado["conteudo"], "pdf")

    def test_assinado_pelas_duas_partes(self):
        self.assertTrue(self.resultado["assinado_cfc"])
        self.assertTrue(self.resultado["assinado_externo"])

    def test_numero_no_corpo(self):
        self.assertEqual(self.resultado["numero_no_corpo"], "26/2023")

    def test_valor_contratado(self):
        self.assertEqual(self.resultado["valor"]["cifra"], "4.104,00")
        self.assertTrue(self.resultado["valor"]["confere"])

    def test_confere_true(self):
        self.assertTrue(self.resultado["valor"]["confere"])

    def test_prorrogacao(self):
        from datetime import date

        self.assertEqual(
            self.resultado["prorrogacao"],
            {"inicio": date(2026, 7, 26), "fim": date(2027, 7, 25)},
        )


class TestProcessarOutroOrgao(SimpleTestCase):
    """PDF "Contrato..." de outro órgão — não menciona os dígitos DESTE
    processo (ainda que mencione o CFC, caso mais difícil de descartar) ->
    descarte silencioso, nenhum campo extraído."""

    def test_outro_orgao_descartado_silenciosamente(self):
        pdf_bytes = construir_pdf_sintetico(
            linhas=_linhas_outro_orgao(), assinaturas=ASSINATURAS_ITEM_58
        )
        resultado = processar(pdf_bytes, PROCESSO_ITEM_58)
        self.assertEqual(resultado["conteudo"], "pdf_outro_orgao")
        self.assertNotIn("valor", resultado)
        self.assertNotIn("contratado", resultado)
        self.assertNotIn("vigencia", resultado)
        self.assertNotIn("prorrogacao", resultado)


class TestProcessarSemTexto(SimpleTestCase):
    def test_pdf_sem_texto_extraivel(self):
        pdf_bytes = construir_pdf_sintetico(linhas=[""], assinaturas=None)
        resultado = processar(pdf_bytes, PROCESSO_ITEM_58)
        self.assertEqual(resultado["conteudo"], "pdf_sem_texto")
        self.assertIsNone(resultado["texto_corpo"])
        self.assertNotIn("prorrogacao", resultado)


class TestProcessarSemAssinaturaDigital(SimpleTestCase):
    def test_pdf_sem_assinatura_digital_vira_pendencia_manual(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=None)
        resultado = processar(pdf_bytes, PROCESSO_ITEM_58)
        self.assertEqual(resultado["conteudo"], "pdf_sem_assinatura_digital")
        self.assertFalse(resultado["assinado_cfc"])
        self.assertFalse(resultado["assinado_externo"])
