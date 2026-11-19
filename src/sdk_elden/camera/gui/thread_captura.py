"""Thread de captura: dona da `Captura`, entrega frames à GUI por sinal Qt.

A abertura (negociação) acontece DENTRO da thread, para a GUI não travar enquanto o
driver configura o stream. Erros de abertura ou leitura viram o sinal `erro`, e a thread termina.
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from sdk_elden.camera.captura import Captura, ErroCaptura, ModoCaptura

JANELA_FPS_S = 1.0  # janela da média móvel do FPS medido


def frame_para_qimage(frame: np.ndarray) -> QImage:
    """BGR (OpenCV) -> QImage sem conversão de cor. O .copy() desacopla do buffer do numpy."""
    altura, largura, _ = frame.shape
    return QImage(frame.data, largura, altura, frame.strides[0], QImage.Format.Format_BGR888).copy()


class ThreadCaptura(QThread):
    aberta = Signal(object)        # ModoCaptura negociado
    novo_frame = Signal(QImage, object)  # imagem p/ exibir + frame BGR (np.ndarray) original, p/ salvar depois
    fps_medido = Signal(float)
    erro = Signal(str)

    def __init__(self, caminho: str | Path, modo: ModoCaptura, parent=None):
        super().__init__(parent)
        self.caminho = caminho
        self.modo = modo
        self._parar = False

    def parar(self) -> None:
        """Pede para encerrar; o loop sai após o frame corrente (no máx. ~1 intervalo de frame)."""
        self._parar = True

    def run(self) -> None:
        try:
            with Captura(self.caminho, self.modo) as cap:
                self.aberta.emit(cap.negociado)
                instantes: deque[float] = deque()
                ultimo_aviso = time.monotonic()
                while not self._parar:
                    frame = cap.ler()
                    self.novo_frame.emit(frame_para_qimage(frame), frame)
                    agora = time.monotonic()
                    instantes.append(agora)
                    while instantes and agora - instantes[0] > JANELA_FPS_S:
                        instantes.popleft()
                    if agora - ultimo_aviso >= JANELA_FPS_S and len(instantes) > 1:
                        self.fps_medido.emit((len(instantes) - 1) / (instantes[-1] - instantes[0]))
                        ultimo_aviso = agora
        except ErroCaptura as e:
            self.erro.emit(str(e))
