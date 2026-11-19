"""Captura de frames via OpenCV (backend V4L2) com negociação explícita de modo.

Regras (ver ~/dev/mctech/testes_cam/camera_utils.py, de onde veio a lição):
1. FOURCC -> resolução -> FPS, NESTA ordem. As resoluções dependem do formato e
   as taxas dependem de formato+resolução.
2. Validar o pedido contra os modos que o driver ANUNCIA antes de abrir: um modo
   inexistente é trocado em silêncio pelo driver (verificado: pedido 1234x567 na
   Redeagle virou 1280x720 sem erro).
3. Conferir o que foi negociado depois de abrir. Os getters do OpenCV 5.1 batem
   com o G_FMT/G_PARM do driver (conferido via linuxpy em 2026-11-19).

Controles (exposição, ganho...) NÃO passam por aqui; use controles.ControlesCamera.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from sdk_elden.camera.dispositivos import ModoFrame, modos_anunciados

TOLERANCIA_FPS = 0.5
BUFFERS_PADRAO = 2  # poucos buffers = menos latência no preview; explícito, não o padrão do OpenCV
FRAMES_AQUECIMENTO = 30  # ~1 s a 30 fps; ver Captura.medir_fps


class ErroCaptura(Exception):
    pass


@dataclass(frozen=True)
class ModoCaptura:
    fourcc: str
    largura: int
    altura: int
    fps: float

    def __str__(self) -> str:
        return f"{self.fourcc} {self.largura}x{self.altura}@{self.fps:g}"


def validar_modo(modo: ModoCaptura, anunciados: tuple[ModoFrame, ...]) -> None:
    """Levanta ErroCaptura se o modo não estiver entre os anunciados pelo driver."""
    candidatos = [m for m in anunciados if (m.fourcc, m.largura, m.altura) == (modo.fourcc, modo.largura, modo.altura)]
    if not candidatos:
        opcoes = ", ".join(f"{m.fourcc} {m.largura}x{m.altura}" for m in anunciados)
        raise ErroCaptura(f"modo {modo.fourcc} {modo.largura}x{modo.altura} não anunciado. Opções: {opcoes}")
    taxas = candidatos[0].fps
    if taxas and not any(abs(float(f) - modo.fps) <= TOLERANCIA_FPS for f in taxas):
        raise ErroCaptura(f"{modo.fps:g} fps não anunciado para {modo}; taxas: {[float(f) for f in taxas]}")


def divergencias(pedido: ModoCaptura, negociado: ModoCaptura) -> list[str]:
    erros = []
    if (pedido.fourcc, pedido.largura, pedido.altura) != (negociado.fourcc, negociado.largura, negociado.altura):
        erros.append(f"pedido {pedido.fourcc} {pedido.largura}x{pedido.altura}, "
                     f"driver entregou {negociado.fourcc} {negociado.largura}x{negociado.altura}")
    if abs(pedido.fps - negociado.fps) > TOLERANCIA_FPS:
        erros.append(f"pedido {pedido.fps:g} fps, driver entregou {negociado.fps:g}")
    return erros


def _fourcc_texto(valor: float) -> str:
    v = int(valor)
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))


class Captura:
    """Stream aberto de uma câmera. Use como context manager.

    estrito=True (padrão): qualquer divergência na negociação levanta ErroCaptura.
    estrito=False: abre mesmo assim e registra as divergências em `self.avisos`.
    """

    def __init__(self, caminho: str | Path, modo: ModoCaptura, buffers: int = BUFFERS_PADRAO, estrito: bool = True):
        self.caminho = Path(caminho)
        self.pedido = modo
        validar_modo(modo, modos_anunciados(self.caminho))

        self._cap = cv2.VideoCapture(str(self.caminho), cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise ErroCaptura(f"não foi possível abrir {self.caminho} (em uso por outro processo?)")
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*modo.fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, modo.largura)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, modo.altura)
        self._cap.set(cv2.CAP_PROP_FPS, modo.fps)
        if not self._cap.set(cv2.CAP_PROP_BUFFERSIZE, buffers):
            self.fechar()
            raise ErroCaptura(f"driver recusou {buffers} buffers")

        self.negociado = ModoCaptura(
            fourcc=_fourcc_texto(self._cap.get(cv2.CAP_PROP_FOURCC)),
            largura=int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            altura=int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=self._cap.get(cv2.CAP_PROP_FPS),
        )
        self.avisos = divergencias(modo, self.negociado)
        if self.avisos and estrito:
            self.fechar()
            raise ErroCaptura("negociação divergente: " + "; ".join(self.avisos))

    def ler(self) -> np.ndarray:
        """Próximo frame em BGR (MJPG/YUYV já convertidos pelo OpenCV)."""
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise ErroCaptura(f"{self.caminho}: falha ao ler frame (câmera desconectada?)")
        return frame

    def medir_fps(self, n_frames: int = 60, aquecimento: int = FRAMES_AQUECIMENTO) -> float:
        """FPS real em regime, medido no relógio monotônico.

        Descarta `aquecimento` frames antes de medir. Logo após o start do stream, a
        Redeagle às vezes sobe gradualmente (22 -> 26 -> 29 -> 30 fps no 1º segundo,
        observado em 2026-11-19), e medir junto daria um valor que não é o de regime.
        """
        for _ in range(max(aquecimento, 1)):  # o 1º frame sempre inclui o tempo de start
            self.ler()
        inicio = time.monotonic()
        for _ in range(n_frames):
            self.ler()
        return n_frames / (time.monotonic() - inicio)

    def fechar(self) -> None:
        self._cap.release()

    def __enter__(self) -> Captura:
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()


def main() -> None:
    ap = argparse.ArgumentParser(description="Abre uma câmera num modo explícito e mede o FPS real")
    ap.add_argument("dispositivo", help="/dev/videoN ou /dev/v4l/by-id/...")
    ap.add_argument("--fourcc", required=True, help="ex.: MJPG, YUYV")
    ap.add_argument("--largura", type=int, required=True)
    ap.add_argument("--altura", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--frames", type=int, default=60)
    a = ap.parse_args()
    modo = ModoCaptura(a.fourcc.upper(), a.largura, a.altura, a.fps)
    try:
        with Captura(a.dispositivo, modo) as cap:
            print(f"negociado: {cap.negociado}")
            print(f"fps medido em {a.frames} frames: {cap.medir_fps(a.frames):.1f}")
    except ErroCaptura as e:
        raise SystemExit(f"ERRO: {e}")


if __name__ == "__main__":
    main()
