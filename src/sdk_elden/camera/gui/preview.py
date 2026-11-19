"""Widget que desenha o frame mais recente mantendo a proporção.

Desenha direto no paintEvent (QPainter.drawImage) em vez de usar QLabel.setPixmap:
assim a cópia QImage->QPixmap a cada frame é evitada, e chamadas seguidas de update() são
coalescidas pelo Qt. Se a GUI ficar mais lenta que a câmera, só o frame mais novo é desenhado.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from sdk_elden.camera.gui import tema


class WidgetPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._imagem: QImage | None = None
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def mostrar(self, imagem: QImage) -> None:
        self._imagem = imagem
        self.update()

    def limpar(self) -> None:
        self._imagem = None
        self.update()

    def area_imagem(self) -> QRect:
        """Retângulo (em coords do widget) onde a imagem é desenhada, com letterbox."""
        if self._imagem is None:
            return QRect()
        tamanho = self._imagem.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - tamanho.width()) // 2
        y = (self.height() - tamanho.height()) // 2
        return QRect(x, y, tamanho.width(), tamanho.height())

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tema.PREVIEW))
        if self._imagem is None:
            p.setPen(QColor(tema.TEXTO_DESAB))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "sem imagem")
        else:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(self.area_imagem(), self._imagem)
        p.end()
