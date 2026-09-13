"""Relatório de conferência nominal do import, acumulado durante o
processamento de importar_pca.py, sem reprocessar a planilha. Emitido no
terminal e em arquivo, mesmo sob --dry-run, porque a gravação é I/O de
disco e sobrevive a um rollback de transação.

Nenhuma das quatro seções abaixo é corrigida em silêncio: cada uma lista
os itens nominalmente, nunca só a contagem."""

from datetime import date
from pathlib import Path

from django.utils import timezone

DIRETORIO_PADRAO = Path("ops/relatorios")


class Relatorio:
    def __init__(self, arquivo_fonte: str, dry_run: bool):
        self.arquivo_fonte = arquivo_fonte
        self.dry_run = dry_run

        self._entregas_antes_do_envio: list[tuple[int, date, date]] = []
        self._sem_prioridade_e_classificacao: list[int] = []
        self._multiplos_sei: list[tuple[int, list[str]]] = []
        self._mes_ambiguo: list[int] = []

        self.processos_criados = 0
        self.processos_ignorados = 0
        self.acompanhamentos_criados = 0
        self.acompanhamentos_ignorados = 0

    # -- acumulação, chamada de dentro de importar_pca.py, sem reabrir o workbook --

    def registrar_entrega_anterior_ao_envio(self, item_pca, data_envio, data_entrega):
        self._entregas_antes_do_envio.append((item_pca, data_envio, data_entrega))

    def registrar_sem_prioridade_e_classificacao(self, item_pca):
        self._sem_prioridade_e_classificacao.append(item_pca)

    def registrar_multiplos_sei(self, item_pca, numeros_sei):
        self._multiplos_sei.append((item_pca, list(numeros_sei)))

    def registrar_mes_ambiguo(self, item_pca):
        self._mes_ambiguo.append(item_pca)

    def registrar_processos_criados(self, quantidade):
        self.processos_criados += quantidade

    def registrar_processo_ignorado(self):
        self.processos_ignorados += 1

    def registrar_acompanhamentos_criados(self, quantidade):
        self.acompanhamentos_criados += quantidade

    def registrar_acompanhamentos_ignorados(self, quantidade):
        self.acompanhamentos_ignorados += quantidade

    # -- Formatação -----------------------------------------------------

    def formatar(self) -> str:
        agora = timezone.localtime()
        linhas = [
            "# Relatório de conferência do import",
            "",
            f"- Data/hora: {agora.strftime('%d/%m/%Y %H:%M')} (America/Sao_Paulo)",
            f"- Arquivo fonte: `{self.arquivo_fonte}`",
            f"- --dry-run: {'sim' if self.dry_run else 'não'}",
            f"- Processos criados: {self.processos_criados} "
            f"(ignorados por já existirem: {self.processos_ignorados})",
            f"- Acompanhamentos criados: {self.acompanhamentos_criados} "
            f"(ignorados por já existirem: {self.acompanhamentos_ignorados})",
            "",
        ]

        linhas += self._secao(
            "1. Entrega ao Delic anterior ao envio",
            self._entregas_antes_do_envio,
            lambda item: (
                f"- item {item[0]}: envio {item[1].strftime('%d/%m/%Y')} → "
                f"entrega {item[2].strftime('%d/%m/%Y')}"
            ),
            chave_ordenacao=lambda item: item[0],
        )
        linhas += self._secao(
            "2. Sem grau de prioridade e sem classificação",
            self._sem_prioridade_e_classificacao,
            lambda item: f"- item {item}",
        )
        linhas += self._secao(
            "3. Múltiplos números de processo SEI",
            self._multiplos_sei,
            lambda item: f"- item {item[0]}: {', '.join(item[1])}",
            chave_ordenacao=lambda item: item[0],
        )
        linhas += self._secao(
            "4. Mês previsto ambíguo (gravado como nulo, nunca inventado)",
            self._mes_ambiguo,
            lambda item: f"- item {item}: mês previsto não reconhecido na planilha",
        )

        linhas.append("")
        return "\n".join(linhas)

    @staticmethod
    def _secao(titulo, itens, formatar_item, chave_ordenacao=None):
        itens_ordenados = sorted(itens, key=chave_ordenacao) if itens else itens
        linhas = [f"## {titulo} ({len(itens)})", ""]
        if itens_ordenados:
            linhas.extend(formatar_item(item) for item in itens_ordenados)
        else:
            linhas.append("- Nenhum caso nesta execução.")
        linhas.append("")
        return linhas

    # -- emissão: terminal + arquivo --

    def emitir(self, escrever_stdout=print, diretorio_saida: Path = DIRETORIO_PADRAO) -> Path:
        texto = self.formatar()
        escrever_stdout(texto)

        diretorio_saida = Path(diretorio_saida)
        diretorio_saida.mkdir(parents=True, exist_ok=True)
        nome_arquivo = f"import-{timezone.localtime().strftime('%Y-%m-%d-%H%M')}.md"
        caminho = diretorio_saida / nome_arquivo
        caminho.write_text(texto, encoding="utf-8")
        return caminho
