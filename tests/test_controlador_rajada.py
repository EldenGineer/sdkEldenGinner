"""Controlador da rajada na GUI, sem câmera (frames sintéticos), no plugin offscreen.

Espera com time.sleep + processEvents, NUNCA QTest.qWait: ele segura o GIL e as threads
Python (a fila de salvamento) não andam (ver CLAUDE.md).
"""
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from sdk_elden.camera.armazenamento import ConfigArmazenamento, MetadadosCaptura
from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.gui.controlador_rajada import ControladorRajada
from sdk_elden.camera.rajada import ConfigRajada, ErroRajada

MODO = ModoCaptura("MJPG", 8, 6, 30.0)
META = MetadadosCaptura("Cam Teste: x", "/dev/video9", None, "uvcvideo", "usb-1", MODO, MODO, ())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def esperar(app, cond, segundos=5.0):
    limite = time.monotonic() + segundos
    while not cond() and time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.01)
    return cond()


@pytest.fixture
def ctrl(app, tmp_path):
    c = ControladorRajada()
    ev = {"salvas": [], "falhas": [], "parou": 0, "resumo": None}
    c.foto_salva.connect(ev["salvas"].append)
    c.falhou.connect(ev["falhas"].append)
    c.parou.connect(lambda: ev.__setitem__("parou", ev["parou"] + 1))
    c.terminou.connect(lambda r: ev.__setitem__("resumo", r))
    cfg_arm = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="s", formato="jpg")
    yield c, ev, cfg_arm
    c.fechar(5)


def alimentar(c, fps, segundos, t0=1000.0):
    for k in range(int(fps * segundos) + 1):
        c.ao_frame(np.full((6, 8, 3), k % 255, np.uint8), t0 + k / fps)


def test_rajada_por_quantidade_salva_e_resume(app, ctrl, tmp_path):
    c, ev, cfg_arm = ctrl
    c.iniciar(cfg_arm, ConfigRajada(intervalo_s=0.5, quantidade=4), "Cam Teste: x", lambda: META)
    assert c.ativo and "RAJADA 0/4" in c.texto_status()
    alimentar(c, 30, 5.0)
    assert not c.ativo and ev["parou"] == 1  # parou sozinha ao atingir a quantidade
    assert esperar(app, lambda: ev["resumo"] is not None)
    r = ev["resumo"]
    assert (r.feitas, r.salvas, r.descartadas, r.falhas) == (4, 4, 0, 0)
    assert len(ev["salvas"]) == 4
    dados = [json.loads(p.with_suffix(".json").read_text()) for p in ev["salvas"]]
    assert [d["rajada"]["indice"] for d in dados] == [1, 2, 3, 4]
    assert {d["rajada"]["id"] for d in dados} == {r.id}


def test_sem_limite_ate_parar(app, ctrl):
    c, ev, cfg_arm = ctrl
    c.iniciar(cfg_arm, ConfigRajada(intervalo_s=1.0, quantidade=0), "Cam", lambda: META)
    assert "RAJADA 0/∞" in c.texto_status()
    alimentar(c, 30, 3.0)
    assert c.ativo
    c.parar()
    assert not c.ativo and c.texto_status() == ""
    assert esperar(app, lambda: ev["resumo"] is not None)
    assert ev["resumo"].salvas == 4  # t0, +1, +2, +3


def test_frames_depois_de_parar_sao_ignorados(app, ctrl):
    c, ev, cfg_arm = ctrl
    c.iniciar(cfg_arm, ConfigRajada(intervalo_s=0.1, quantidade=0), "Cam", lambda: META)
    alimentar(c, 30, 0.5)
    c.parar()
    alimentar(c, 30, 0.5, t0=2000.0)
    assert esperar(app, lambda: ev["resumo"] is not None)
    assert ev["resumo"].salvas == ev["resumo"].feitas == 6


def test_falha_de_salvamento_e_reportada_sem_parar(app, ctrl):
    c, ev, cfg_arm = ctrl
    c.iniciar(cfg_arm, ConfigRajada(intervalo_s=0.5, quantidade=3), "Cam", lambda: META)
    c.ao_frame(np.zeros((0, 0, 3), np.uint8), 1000.0)  # imagem vazia: o imwrite recusa
    c.ao_frame(np.zeros((6, 8, 3), np.uint8), 1000.5)
    c.ao_frame(np.zeros((6, 8, 3), np.uint8), 1001.0)
    assert esperar(app, lambda: ev["resumo"] is not None)
    r = ev["resumo"]
    assert (r.salvas, r.falhas) == (2, 1) and r.primeira_falha and ev["falhas"]


def test_config_invalida_nao_inicia(ctrl):
    c, _, cfg_arm = ctrl
    with pytest.raises(ErroRajada):
        c.iniciar(cfg_arm, ConfigRajada(intervalo_s=0.001), "Cam", lambda: META)
    assert not c.ativo


def test_fechar_espera_salvamentos(app, ctrl, tmp_path):
    c, ev, _ = ctrl
    cfg_png = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="png", formato="png")
    c.iniciar(cfg_png, ConfigRajada(intervalo_s=0.05, quantidade=0), "Cam", lambda: META)
    for k in range(10):
        c.ao_frame(np.random.randint(0, 255, (720, 1280, 3), np.uint8), 1000 + k * 0.05)
    assert c.fechar(30)  # para e espera tudo que entrou na fila
    assert len(list((tmp_path / "r" / "png").glob("*.png"))) == 10
