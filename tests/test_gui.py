"""Testes da GUI rodando no plugin Qt 'offscreen' (sem abrir janela na tela)."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from sdk_elden.camera.gui.preview import WidgetPreview
from sdk_elden.camera.gui.thread_captura import frame_para_qimage


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_frame_para_qimage_preserva_cor_bgr(app):
    frame = np.zeros((4, 6, 3), np.uint8)
    frame[..., 0] = 255  # azul em BGR
    img = frame_para_qimage(frame)
    assert (img.width(), img.height()) == (6, 4)
    cor = img.pixelColor(0, 0)
    assert (cor.red(), cor.green(), cor.blue()) == (0, 0, 255)


def test_qimage_independe_do_buffer_numpy(app):
    frame = np.full((2, 2, 3), 10, np.uint8)
    img = frame_para_qimage(frame)
    frame[:] = 200
    assert img.pixelColor(0, 0).red() == 10


def test_preview_letterbox(app):
    w = WidgetPreview()
    w.resize(QSize(1000, 1000))
    w.mostrar(frame_para_qimage(np.zeros((90, 160, 3), np.uint8)))  # 16:9
    area = w.area_imagem()
    assert (area.width(), area.height()) == (1000, 562)
    assert area.y() == (1000 - 562) // 2


REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_janela_abre_recebe_frames_e_captura(app, tmp_path):
    import json

    from sdk_elden.camera.armazenamento import SECAO_CONFIG, ConfigArmazenamento
    from sdk_elden.camera.gui.janela_principal import JanelaPrincipal
    from sdk_elden.utils.config import salvar_secao

    arq = tmp_path / "camera.toml"  # nunca usar ~/.config nem ~/capturas reais em teste
    salvar_secao(arq, SECAO_CONFIG, ConfigArmazenamento(raiz=str(tmp_path / "cap"), repo="r", subrepo="s"))
    j = JanelaPrincipal(arq)
    assert not j.btn_capturar.isEnabled()
    linha = next(i for i, c in enumerate(j._cameras) if str(c.caminho_estavel) == REDEAGLE)
    j.lista.setCurrentRow(linha)
    j.cb_formato.setCurrentText("MJPG")
    j.cb_resolucao.setCurrentText("1280x720")
    j.abrir()
    limite = time.monotonic() + 5
    while j.ultimo_frame is None and time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.01)
    try:
        assert j.ultimo_frame is not None and j.ultimo_frame.shape == (720, 1280, 3)
        assert "ao vivo: MJPG 1280x720@30" in j.lbl_status_modo.text()
        assert not j.lista.isEnabled()  # edição travada durante o stream
        assert j.btn_capturar.isEnabled()

        img = j.capturar()
        assert img is not None and img.parent == tmp_path / "cap" / "r" / "s"
        meta = json.loads(img.with_suffix(".json").read_text())
        assert meta["camera"]["caminho_estavel"] == REDEAGLE
        assert meta["modo_negociado"]["largura"] == 1280
        assert "brightness" in meta["controles"]
    finally:
        j.parar()
    assert j.lista.isEnabled() and j.lbl_status_modo.text() == "parado"
    # após parar: frame antigo descartado e captura bloqueada
    assert j.ultimo_frame is None and not j.btn_capturar.isEnabled() and j.capturar() is None


def test_config_invalida_nao_e_sobrescrita(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from sdk_elden.camera.gui.janela_principal import JanelaPrincipal

    arq = tmp_path / "camera.toml"
    arq.write_text('[armazenamento]\nrepoo = "typo"\n')
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    j = JanelaPrincipal(arq)
    assert avisos and "repoo" in avisos[0]
    assert j.cfg.repo == "geral"  # padrões nesta sessão
    assert arq.read_text() == '[armazenamento]\nrepoo = "typo"\n'  # arquivo intocado
    j.close()
