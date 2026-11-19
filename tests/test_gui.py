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
def test_janela_abre_recebe_frames_e_captura(app, tmp_path, monkeypatch):
    import json

    from PySide6.QtWidgets import QMessageBox

    # sem tela, um QMessageBox modal espera um clique para sempre (a suíte travava quando a
    # câmera estava em uso por outro processo): falhar na hora, com a mensagem do erro
    def _falhar(_pai, titulo, texto, *a, **k):
        pytest.fail(f"{titulo}: {texto}")

    monkeypatch.setattr(QMessageBox, "critical", _falhar)
    monkeypatch.setattr(QMessageBox, "warning", _falhar)

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


# --- painéis, foco e modo compacto (sem câmera: listar_cameras devolve []) -----------
@pytest.fixture
def janela_sem_camera(app, tmp_path, monkeypatch):
    from sdk_elden.camera.gui import janela_principal as jp

    monkeypatch.setattr(jp, "listar_cameras", lambda: [])
    j = jp.JanelaPrincipal(tmp_path / "camera.toml")  # arquivo inexistente: padrões, nada é criado
    j.show()
    app.processEvents()
    yield j
    j.close()


def _ocultos(j):
    return j.painel_esquerdo.isHidden(), j.painel_controles.isHidden()


def test_alternar_paineis(janela_sem_camera):
    j = janela_sem_camera
    assert _ocultos(j) == (False, False)
    j.acao_cameras.trigger()
    assert _ocultos(j) == (True, False)
    j.acao_controles.trigger()
    assert _ocultos(j) == (True, True)
    assert not j.acao_foco.isChecked()  # ocultar os dois à mão não liga o foco


def test_foco_oculta_e_restaura_estado_anterior(janela_sem_camera):
    j = janela_sem_camera
    j.acao_controles.trigger()  # antes do foco: só câmeras visível
    j.acao_foco.trigger()
    assert _ocultos(j) == (True, True)
    j.acao_foco.trigger()
    assert _ocultos(j) == (False, True)  # volta exatamente ao que era


def test_abrir_painel_durante_foco_encerra_foco(janela_sem_camera):
    j = janela_sem_camera
    j.acao_foco.trigger()
    j.acao_controles.trigger()
    assert not j.acao_foco.isChecked()
    assert _ocultos(j) == (True, False)  # o outro painel continua oculto


def test_modo_compacto_oculta_ao_cruzar_e_restaura(app, janela_sem_camera):
    from sdk_elden.camera.gui.janela_principal import LARGURA_COMPACTA

    j = janela_sem_camera
    j.acao_controles.trigger()  # estado antes de estreitar: câmeras visível
    j.resize(LARGURA_COMPACTA - 200, 700)
    app.processEvents()
    assert _ocultos(j) == (True, True)
    j.acao_cameras.trigger()  # dentro do modo compacto os botões continuam valendo
    assert _ocultos(j) == (False, True)
    j.resize(LARGURA_COMPACTA + 300, 800)
    app.processEvents()
    assert _ocultos(j) == (False, True)  # restaura o estado de antes de estreitar


# --- gravação de vídeo pela GUI ---------------------------------------------------------
def test_gravar_sem_stream_nao_faz_nada(janela_sem_camera):
    j = janela_sem_camera
    assert not j.btn_gravar.isEnabled()
    j.alternar_gravacao()
    assert not j.gravando and not j.rec_visivel


def test_janela_config_gravacao_ida_e_volta(app, tmp_path):
    from sdk_elden.camera.armazenamento import ConfigArmazenamento
    from sdk_elden.camera.gravacao import ConfigGravacao
    from sdk_elden.camera.gui.janela_config import JanelaConfig

    cfg_grav = ConfigGravacao(formato="mp4", codificador="h264_nvenc", qualidade_h264=19)
    d = JanelaConfig(ConfigArmazenamento(raiz=str(tmp_path)), tmp_path / "c.toml", None, cfg_grav=cfg_grav)
    assert d.config_gravacao() == cfg_grav  # nada mudou: volta igual
    assert d.cb_codificador.isEnabled() and not d.sp_qualidade_mjpeg.isEnabled()
    d.cb_video_formato.setCurrentIndex(d.cb_video_formato.findData("mkv"))
    assert not d.cb_codificador.isEnabled() and d.sp_qualidade_mjpeg.isEnabled()  # MKV é sempre MJPG
    d.sp_qualidade_mjpeg.setValue(5)
    assert d.config_gravacao() == ConfigGravacao(formato="mkv", codificador="h264_nvenc",
                                                 qualidade_h264=19, qualidade_mjpeg=5)


def _janela_gravando(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from sdk_elden.camera.armazenamento import SECAO_CONFIG, ConfigArmazenamento
    from sdk_elden.camera.gui.janela_principal import JanelaPrincipal
    from sdk_elden.utils.config import salvar_secao

    def _falhar(_pai, titulo, texto, *a, **k):
        pytest.fail(f"{titulo}: {texto}")

    monkeypatch.setattr(QMessageBox, "critical", _falhar)
    monkeypatch.setattr(QMessageBox, "warning", _falhar)
    arq = tmp_path / "camera.toml"
    salvar_secao(arq, SECAO_CONFIG, ConfigArmazenamento(raiz=str(tmp_path / "cap"), repo="r", subrepo="s"))
    j = JanelaPrincipal(arq)
    j.show()  # sem show() a barra não é diagramada e o indicador REC não tem geometria
    j.lista.setCurrentRow(next(i for i, c in enumerate(j._cameras) if str(c.caminho_estavel) == REDEAGLE))
    j.cb_formato.setCurrentText("MJPG")
    j.cb_resolucao.setCurrentText("1280x720")
    j.abrir()
    limite = time.monotonic() + 5
    while not j.btn_gravar.isEnabled() and time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.01)
    assert j.btn_gravar.isEnabled()
    return j


def _esperar(app, cond, segundos=15):
    limite = time.monotonic() + segundos
    while not cond() and time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_gravar_pela_gui(app, tmp_path, monkeypatch):
    import json

    j = _janela_gravando(app, tmp_path, monkeypatch)
    try:
        destino = j.iniciar_gravacao()
        assert j.gravando and "Parar" in j.btn_gravar.text()
        _esperar(app, lambda: False, 1.5)  # ~1,5 s de vídeo
        assert "REC" in j.lbl_rec.text() and j.rec_visivel
        assert j.lbl_rec.geometry().width() < 400  # posicionado de verdade na barra (antes: 640x480 solto)
        j.alternar_gravacao()
        assert not j.gravando
        assert _esperar(app, lambda: destino.exists() and destino.with_suffix(".json").exists())
        assert _esperar(app, lambda: not j.rec_visivel)
        meta = json.loads(destino.with_suffix(".json").read_text())
        assert meta["tipo"] == "video" and meta["estatisticas"]["escritos"] > 20
        assert meta["estatisticas"]["descartados_fila"] == 0
        assert destino.parent == tmp_path / "cap" / "r" / "s"
    finally:
        j.parar()
        j.close()


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_fechar_janela_gravando_salva_o_video(app, tmp_path, monkeypatch):
    j = _janela_gravando(app, tmp_path, monkeypatch)
    destino = j.iniciar_gravacao()
    _esperar(app, lambda: False, 1.0)
    j.close()  # closeEvent: para o stream, encerra a gravação e ESPERA o arquivo fechar
    assert destino.exists() and destino.with_suffix(".json").exists()
    assert not list(destino.parent.glob(".*tmp*"))
