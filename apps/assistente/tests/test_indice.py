"""`apps.assistente.indice`: schema, geração atômica, reaproveitamento
por hash, escritor único, medição de busca (A05..A08).
Cliente de embeddings sempre falso e determinístico — vetor derivado do
hash do texto, dimensão 8 (exceto no teste de medição, que usa 1536)."""

import fcntl
import hashlib
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.assistente import fontes as fontes_mod
from apps.assistente import indice
from apps.assistente.cliente import ErroCliente, RespostaEmbeddings

_DIMENSAO_PADRAO = 8


def _vetor_do_hash(texto: str, dimensao: int = _DIMENSAO_PADRAO):
    digest = hashlib.sha256(texto.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) * 2 - 1) for i in range(dimensao)]


class _ClienteEmbeddingsFalso:
    def __init__(self, dimensao=_DIMENSAO_PADRAO, explodir_no_lote=None):
        self.dimensao = dimensao
        self.explodir_no_lote = explodir_no_lote
        self.chamadas_embeddings = 0
        self.textos_recebidos: list[list[str]] = []

    def embeddings(self, textos, timeout_s):
        indice_lote = self.chamadas_embeddings
        self.chamadas_embeddings += 1
        self.textos_recebidos.append(list(textos))
        if self.explodir_no_lote is not None and indice_lote == self.explodir_no_lote:
            raise ErroCliente("provedor")
        vetores = [_vetor_do_hash(t, self.dimensao) for t in textos]
        return RespostaEmbeddings(vetores=vetores, tokens=len(textos) * 3)


class _UsuarioFalso:
    is_authenticated = True
    is_active = True

    def __init__(self, *, acompanhamento=False, analises=False):
        self._acompanhamento = acompanhamento
        self._analises = analises

    def has_perm(self, perm):
        if perm == "pca.view_acompanhamento":
            return self._acompanhamento
        if perm == "pca.ver_analises":
            return self._analises
        return False


def _trecho(*, fonte="docs", ref, ordem=0, texto=None, permissao="", exercicio=None,
            item_pca=None, titulo="Título", url=None, atualizado_em=None):
    return fontes_mod.Trecho(
        fonte=fonte, ref=ref, ordem=ordem, titulo=titulo,
        texto=texto if texto is not None else f"texto do trecho {ref}",
        url=url, exercicio=exercicio, item_pca=item_pca,
        permissao=permissao, atualizado_em=atualizado_em,
    )


class _IndiceTestBase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.caminho_indice = Path(self._tmp.name) / "indice.sqlite3"
        self._override = override_settings(
            IA_INDICE_PATH=str(self.caminho_indice),
            IA_MODELO_EMBED="modelo-teste",
            IA_TIMEOUT_S=5,
        )
        self._override.enable()
        self.addCleanup(self._override.disable)
        indice._CACHE_MATRIZ.clear()
        self.addCleanup(indice._CACHE_MATRIZ.clear)

    def _meta_atual(self):
        con = indice._conectar()
        try:
            return indice._ler_meta(con)
        finally:
            con.close()

    def _refs_atuais(self):
        con = indice._conectar()
        try:
            return {linha[0] for linha in con.execute("SELECT ref FROM trecho").fetchall()}
        finally:
            con.close()


class TestIndexarPrimeiraGeracao(_IndiceTestBase):
    def test_publica_geracao_1_com_contagens(self):
        trechos = [
            _trecho(ref="a", fonte="docs"),
            _trecho(ref="b", fonte="acompanhamento", permissao="pca.view_acompanhamento"),
        ]
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=trechos):
            resumo = indice.indexar(cliente, agora=timezone.now())

        self.assertEqual(resumo.geracao, 1)
        self.assertEqual(resumo.novos, 2)
        self.assertEqual(resumo.reaproveitados, 0)
        self.assertEqual(resumo.removidos, 0)
        self.assertEqual(cliente.chamadas_embeddings, 1)

        meta = self._meta_atual()
        self.assertEqual(meta["geracao"], "1")
        self.assertEqual(meta["modelo_embed"], "modelo-teste")
        contagens = meta["contagens_json"]
        self.assertIn("docs", contagens)
        self.assertIn("acompanhamento", contagens)


class TestIndexarIncremental(_IndiceTestBase):
    def test_sem_mudanca_nao_chama_embeddings(self):
        trechos = [_trecho(ref="a")]
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=trechos):
            indice.indexar(cliente, agora=timezone.now())
            resumo2 = indice.indexar(cliente, agora=timezone.now())

        self.assertEqual(resumo2.novos, 0)
        self.assertEqual(resumo2.reaproveitados, 1)
        self.assertEqual(cliente.chamadas_embeddings, 1)

    def test_mudar_url_ou_permissao_atualiza_sem_reembeddar(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a", url="/x")]):
            indice.indexar(cliente, agora=timezone.now())
        with mock.patch(
            "apps.assistente.fontes.extrair_tudo",
            return_value=[_trecho(ref="a", url="/y", permissao="pca.ver_analises")],
        ):
            resumo = indice.indexar(cliente, agora=timezone.now())

        self.assertEqual(resumo.novos, 0)
        self.assertEqual(cliente.chamadas_embeddings, 1)
        con = indice._conectar()
        try:
            linha = con.execute("SELECT url, permissao FROM trecho WHERE ref='a'").fetchone()
        finally:
            con.close()
        self.assertEqual(linha, ("/y", "pca.ver_analises"))

    def test_texto_diferente_reembedda(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a", texto="texto 1")]):
            indice.indexar(cliente, agora=timezone.now())
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a", texto="texto 2")]):
            resumo = indice.indexar(cliente, agora=timezone.now())
        self.assertEqual(resumo.novos, 1)
        self.assertEqual(cliente.chamadas_embeddings, 2)

    def test_trecho_sumido_e_removido(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch(
            "apps.assistente.fontes.extrair_tudo",
            return_value=[_trecho(ref="a"), _trecho(ref="b")],
        ):
            indice.indexar(cliente, agora=timezone.now())
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            resumo = indice.indexar(cliente, agora=timezone.now())

        self.assertEqual(resumo.removidos, 1)
        self.assertEqual(self._refs_atuais(), {"a"})

    def test_troca_de_modelo_forca_reconstrucao(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            indice.indexar(cliente, agora=timezone.now())

        with override_settings(IA_MODELO_EMBED="outro-modelo"):
            with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
                resumo = indice.indexar(cliente, agora=timezone.now())

        self.assertEqual(resumo.novos, 1)
        self.assertEqual(cliente.chamadas_embeddings, 2)
        self.assertEqual(self._meta_atual()["modelo_embed"], "outro-modelo")

    def test_completo_reembedda_mesmo_sem_mudanca(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            indice.indexar(cliente, agora=timezone.now())
            resumo = indice.indexar(cliente, completo=True, agora=timezone.now())

        self.assertEqual(resumo.novos, 1)
        self.assertEqual(cliente.chamadas_embeddings, 2)


class TestIndexarFalhaEConcorrencia(_IndiceTestBase):
    def test_falha_no_segundo_lote_preserva_geracao_anterior(self):
        cliente1 = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            indice.indexar(cliente1, agora=timezone.now())

        muitos_trechos = [_trecho(ref=f"n{i}", texto=f"texto totalmente novo {i}") for i in range(70)]
        cliente2 = _ClienteEmbeddingsFalso(explodir_no_lote=1)
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=muitos_trechos):
            with self.assertRaises(ErroCliente):
                indice.indexar(cliente2, agora=timezone.now())

        self.assertEqual(self._meta_atual()["geracao"], "1")
        self.assertEqual(self._refs_atuais(), {"a"})

    def test_geracao_concorrente_devolve_indice_ocupado(self):
        caminho_lock = indice._lock_path()
        caminho_lock.parent.mkdir(parents=True, exist_ok=True)
        arquivo_lock = open(caminho_lock, "a+")
        fcntl.flock(arquivo_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            cliente = _ClienteEmbeddingsFalso()
            with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
                with self.assertRaises(indice.IndiceOcupado):
                    indice.indexar(cliente, agora=timezone.now())
        finally:
            fcntl.flock(arquivo_lock, fcntl.LOCK_UN)
            arquivo_lock.close()

    def test_thread_concorrente_segurando_o_flock_devolve_ocupado(self):
        pronto = threading.Event()
        liberar = threading.Event()

        def segurar_lock():
            caminho_lock = indice._lock_path()
            caminho_lock.parent.mkdir(parents=True, exist_ok=True)
            with open(caminho_lock, "a+") as arquivo:
                fcntl.flock(arquivo, fcntl.LOCK_EX)
                pronto.set()
                liberar.wait(timeout=5)
                fcntl.flock(arquivo, fcntl.LOCK_UN)

        thread = threading.Thread(target=segurar_lock)
        thread.start()
        try:
            self.assertTrue(pronto.wait(timeout=5))
            cliente = _ClienteEmbeddingsFalso()
            with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
                with self.assertRaises(indice.IndiceOcupado):
                    indice.indexar(cliente, agora=timezone.now())
        finally:
            liberar.set()
            thread.join(timeout=5)

    def test_arquivo_corrompido_levanta_indicendisponivel(self):
        self.caminho_indice.parent.mkdir(parents=True, exist_ok=True)
        self.caminho_indice.write_bytes(b"nao e um banco sqlite valido")
        with self.assertRaises(indice.IndiceIndisponivel):
            indice._conectar()


class TestVetorNormaZero(_IndiceTestBase):
    def test_vetor_de_norma_zero_nao_quebra_e_nao_e_retornado(self):
        class _ClienteZero:
            def embeddings(self, textos, timeout_s):
                return RespostaEmbeddings(vetores=[[0.0] * _DIMENSAO_PADRAO for _ in textos], tokens=1)

        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            indice.indexar(_ClienteZero(), agora=timezone.now())

        resultado = indice.buscar(
            usuario=_UsuarioFalso(),
            vetor_consulta=[1.0] * _DIMENSAO_PADRAO,
            k=5,
            limiar=0.1,
        )
        self.assertEqual(resultado, [])


class TestIndiceAusenteOuSemCliente(_IndiceTestBase):
    def test_indexar_sem_cliente_levanta_indicendisponivel(self):
        with self.assertRaises(indice.IndiceIndisponivel):
            indice.indexar(None, agora=timezone.now())

    def test_buscar_sem_arquivo_de_indice_levanta_indicendisponivel(self):
        with self.assertRaises(indice.IndiceIndisponivel):
            indice.buscar(usuario=_UsuarioFalso(), vetor_consulta=[0.0] * _DIMENSAO_PADRAO)

    def test_publicado_em_sem_arquivo_devolve_none(self):
        self.assertIsNone(indice.publicado_em())

    def test_publicado_em_depois_de_indexar(self):
        cliente = _ClienteEmbeddingsFalso()
        with mock.patch("apps.assistente.fontes.extrair_tudo", return_value=[_trecho(ref="a")]):
            indice.indexar(cliente, agora=timezone.now())
        self.assertIsNotNone(indice.publicado_em())


class TestMedicaoBuscaComVetoresSinteticos(_IndiceTestBase):
    def test_50_mil_vetores_dimensao_1536_busca_aquecida(self):
        rng = np.random.default_rng(42)
        dim = 1536
        n = 50_000

        con = indice._conectar()
        try:
            for i in range(n):
                cursor = con.execute(
                    "INSERT INTO trecho(fonte, ref, ordem, titulo, texto, url, exercicio, "
                    "item_pca, permissao, hash_texto, atualizado_em) "
                    "VALUES ('docs', ?, 0, 't', 'texto', NULL, NULL, NULL, '', 'h', NULL)",
                    (f"ref{i}",),
                )
                vetor = rng.standard_normal(dim).astype("<f4")
                norma = np.linalg.norm(vetor)
                if norma > 0:
                    vetor = vetor / norma
                con.execute(
                    "INSERT INTO vetor(trecho_id, dim, blob) VALUES (?, ?, ?)",
                    (cursor.lastrowid, dim, vetor.astype("<f4").tobytes()),
                )
            indice._upsert_meta(con, "geracao", "1")
            indice._upsert_meta(con, "modelo_embed", "medicao")
            indice._upsert_meta(con, "dimensao", str(dim))
            indice._upsert_meta(con, "fragmentador_versao", "1")
        finally:
            con.close()

        indice._CACHE_MATRIZ.clear()
        usuario = _UsuarioFalso()
        vetor_consulta = rng.standard_normal(dim).tolist()

        # 1ª chamada aquece a matriz em cache (custo de I/O + montagem).
        indice.buscar(usuario=usuario, vetor_consulta=vetor_consulta, k=6, limiar=0.0)

        inicio = time.monotonic()
        indice.buscar(usuario=usuario, vetor_consulta=vetor_consulta, k=6, limiar=0.0)
        duracao_ms = (time.monotonic() - inicio) * 1000

        print(
            f"[medição 39-02] indice.buscar aquecida, 50.000 vetores dim=1536: "
            f"{duracao_ms:.2f} ms (objetivo <50ms; teto do assert 1000ms para não flakar "
            f"em dev com 2 vCPUs sob contenção da suíte completa)"
        )
        # Objetivo de medição (<50ms, confirmado isolado: ~44ms neste dev —
        # ver SUMMARY do plano); o assert usa uma margem BEM generosa
        # (1000ms) porque, quando a suíte INTEIRA roda em sequência (2
        # vCPUs compartilhadas), a contenção de CPU de centenas de outros
        # testes antes deste eleva o tempo medido — não é regressão do
        # código, é o ambiente. `objetivo de medição, não garantia` (spec
        # §5).
        self.assertLess(duracao_ms, 1000)
