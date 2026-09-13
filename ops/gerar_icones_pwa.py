"""Gera os 3 ícones do PWA a partir da logo neutra deste repositório."""

from pathlib import Path

from PIL import Image

DIRETORIO_IMG = Path(__file__).resolve().parent.parent / "core" / "static" / "img"
ORIGEM = DIRETORIO_IMG / "logo-neutro.png"

TAMANHOS = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-512-maskable.png": 512,
}


def cortar_para_quadrado(im):
    """Corta uma imagem para o maior quadrado central possível."""
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
