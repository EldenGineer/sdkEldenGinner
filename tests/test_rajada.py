import json
import os
import time
from datetime import datetime

import numpy as np
import pytest

from sdk_elden.camera.armazenamento import (
    ConfigArmazenamento,
    ErroArmazenamento,
    MetadadosCaptura,
    salvar_captura,
)
from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.rajada import AgendaRajada, ConfigRajada, ErroRajada, bloco_sidecar


def frames(fps, segundos, t0=100.0):
    return [t0 + k / fps for k in range(int(fps * segundos) + 1)]


def capturas(agenda, instantes):
    return [t for t in instantes if agenda.deve_capturar(t)]


def test_um_por_intervalo_primeiro_frame_apos_o_horario():
    a = AgendaRajada(ConfigRajada(intervalo_s=1.0, quantidade=0))
    fotos = capturas(a, frames(30, 5.0))
    assert len(fotos) == 6  # t0, t0+1, ..., t0+5
    assert all(abs(f - (100.0 + k)) < 1 / 30 for k, f in enumerate(fotos))
    assert a.perdidas == 0


def test_quantidade_encerra():
    a = AgendaRajada(ConfigRajada(intervalo_s=0.5, quantidade=4))
    fotos = capturas(a, frames(30, 10.0))
    assert len(fotos) == 4 and a.terminou
    assert fotos[-1] == pytest.approx(101.5, abs=1 / 30)


def test_nao_acumula_atraso():
    """Frames a 15 fps com intervalo que não é múltiplo do período: os horários continuam ancorados em t0."""
    a = AgendaRajada(ConfigRajada(intervalo_s=0.3, quantidade=0))
    fotos = capturas(a, frames(15, 30.0))
    assert len(fotos) == 101
    assert fotos[-1] - 100.0 == pytest.approx(30.0, abs=1 / 15)  # sem deriva depois de 100 fotos


def test_intervalo_menor_que_o_frame_nunca_repete_frame():
    a = AgendaRajada(ConfigRajada(intervalo_s=0.05, quantidade=0))
    instantes = frames(10, 2.0)  # câmera a 10 fps, pedido 20 fotos/s
    fotos = capturas(a, instantes)
    assert fotos == instantes  # cada frame no máximo uma vez
    assert a.perdidas == pytest.approx(20, abs=1)  # metade dos horários não tinha frame novo


def test_camera_travada_pula_horarios_sem_disparar_seguidas():
    a = AgendaRajada(ConfigRajada(intervalo_s=1.0, quantidade=0))
    instantes = frames(30, 2.0) + [105.5] + [105.5 + k / 30 for k in range(1, 60)]
    fotos = capturas(a, instantes)
    assert 105.5 in fotos
    assert sum(1 for f in fotos if 105.5 <= f < 106.0) == 1  # só UMA foto ao voltar
    assert a.perdidas == 2  # horários 103 e 104 (o 105 é atendido pelo frame de 105,5)


def test_proximo_em():
    a = AgendaRajada(ConfigRajada(intervalo_s=2.0, quantidade=2))
    assert a.proximo_em(0.0) is None
    a.deve_capturar(10.0)
    assert a.proximo_em(10.5) == pytest.approx(1.5)
    a.deve_capturar(12.0)
    assert a.terminou and a.proximo_em(12.1) is None


@pytest.mark.parametrize("cfg", [ConfigRajada(intervalo_s=0.01), ConfigRajada(quantidade=-1)])
def test_config_invalida(cfg):
    with pytest.raises(ErroRajada):
        AgendaRajada(cfg)


# --- sidecar ---------------------------------------------------------------------------
MODO = ModoCaptura("MJPG", 8, 6, 30.0)
META = MetadadosCaptura("Cam: x", "/dev/video9", None, "uvcvideo", "usb-1", MODO, MODO, ())


def test_sidecar_leva_bloco_da_rajada(tmp_path):
    cfg = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="s")
    img = salvar_captura(np.zeros((6, 8, 3), np.uint8), META, cfg, datetime.now().astimezone(),
                         bloco_sidecar("20261119_150000_Cam", 3, ConfigRajada(intervalo_s=0.5, quantidade=10)))
    dados = json.loads(img.with_suffix(".json").read_text())
    assert dados["rajada"] == {"id": "20261119_150000_Cam", "indice": 3, "intervalo_s": 0.5, "quantidade": 10}
    assert dados["camera"]["caminho"] == "/dev/video9"  # campos padrão intactos


def test_extra_nao_sobrescreve_campos_padrao(tmp_path):
    cfg = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="s")
    with pytest.raises(ErroArmazenamento, match="sobrescreveriam"):
        salvar_captura(np.zeros((6, 8, 3), np.uint8), META, cfg, extra={"camera": "x"})
    assert not list(tmp_path.rglob("*.png"))


# --- câmera real -----------------------------------------------------------------------
REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_rajada_real(tmp_path):
    from sdk_elden.camera.captura import Captura
    from sdk_elden.utils.fila_trabalho import FilaTrabalho

    cfg_arm = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="s", formato="jpg")
    cfg = ConfigRajada(intervalo_s=0.25, quantidade=6)
    agenda = AgendaRajada(cfg)
    fila = FilaTrabalho(salvar_captura, 16)
    with Captura(REDEAGLE, ModoCaptura("MJPG", 1280, 720, 30)) as cap:
        meta = MetadadosCaptura("Redeagle", REDEAGLE, REDEAGLE, "uvcvideo", "usb", cap.pedido, cap.negociado, ())
        horarios = []
        limite = time.monotonic() + 5
        while not agenda.terminou and time.monotonic() < limite:
            frame = cap.ler()
            t = time.monotonic()
            if agenda.deve_capturar(t):
                horarios.append(t)
                fila.enviar(frame, meta, cfg_arm, datetime.now().astimezone(),
                            bloco_sidecar("teste", agenda.feitas, cfg))
    assert fila.fechar(10)
    assert fila.concluidas == 6 and fila.descartadas == 0 and fila.falhas == 0
    assert len(list((tmp_path / "r" / "s").glob("*.jpg"))) == 6
    intervalos = np.diff(horarios)
    assert np.all(np.abs(intervalos - 0.25) < 2 / cap.negociado.fps)  # ~1 frame de folga
