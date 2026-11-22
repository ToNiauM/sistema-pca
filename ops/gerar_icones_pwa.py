"""Gera os 3 ícones do PWA a partir do novo símbolo vetorizado.

`core/static/img/logo-cfc-2.png` é 1024×1042 — mais alto que largo. Não há
recolorimento aqui (isso resolvia outro problema, da ` `, sobre
`logo_CFC.png`, arte diferente já removida): é só corte para quadrado e
redimensionamento.

`cortar_para_quadrado()` centraliza o corte em AMBOS os eixos — como a
largura já é o lado (1024 = min(largura, altura)), só a altura perde pixels,
9 de cada borda (topo e base), nunca de um lado só, para não decapitar o
símbolo em nenhuma direção. Os 3 tamanhos (`icon-192`, `icon-512`,
`icon-512-maskable`) saem do MESMO quadrado, sem padding extra de safe zone
para o maskable — decisão desta quick, diferente da ` `, que
preservava geometria herdada.

O usuário está ciente e aceitou que a arte sangra na borda esquerda.

PIL puro, sem numpy (host é PEP 668, sem numpy instalado) — roda direto no
host (Pillow 12.1.1 já instalado lá), nunca no container `web`, que não tem
Pillow no requirements.txt: é ferramenta de geração de asset, não dependência
de runtime (mesmo tratamento da ` `).
"""

from pathlib import Path

from PIL import Image

DIRETORIO_IMG = Path(__file__).resolve().parent.parent / "core" / "static" / "img"
ORIGEM = DIRETORIO_IMG / "logo-cfc-2.png"

TAMANHOS = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-512-maskable.png": 512,
}


def cortar_para_quadrado(im):
    """Corta uma imagem para o maior quadrado central possível.

    `lado = min(largura, altura)`. A dimensão maior perde pixels igualmente
    de cada borda — nunca só de um lado — para manter o símbolo centralizado.
    """
    largura, altura = im.size
    lado = min(largura, altura)

    sobra_x = largura - lado
    sobra_y = altura - lado
    esquerda = sobra_x // 2
    topo = sobra_y // 2

    return im.crop((esquerda, topo, esquerda + lado, topo + lado))


def gerar():
    im = Image.open(ORIGEM).convert("RGBA")
    quadrado = cortar_para_quadrado(im)

    for nome_arquivo, tamanho in TAMANHOS.items():
        redimensionado = quadrado.resize((tamanho, tamanho), Image.LANCZOS)
        destino = DIRETORIO_IMG / nome_arquivo
        redimensionado.save(destino)
        print("gerado:", destino, f"({tamanho}x{tamanho})")


if __name__ == "__main__":
    gerar()
