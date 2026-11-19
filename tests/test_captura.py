import os
from fractions import Fraction

import pytest

from sdk_elden.camera.captura import Captura, ErroCaptura, ModoCaptura, divergencias, validar_modo
from sdk_elden.camera.controles import ControlesCamera
from sdk_elden.camera.dispositivos import ModoFrame

ANUNCIADOS = (
    ModoFrame("MJPG", 1280, 720, (Fraction(30),)),
    ModoFrame("YUYV", 1280, 720, (Fraction(10),)),
    ModoFrame("YUYV", 640, 480, ()),  # driver sem intervalos
)


def test_modo_anunciado():
    validar_modo(ModoCaptura("MJPG", 1280, 720, 30), ANUNCIADOS)


def test_resolucao_inexistente():
    with pytest.raises(ErroCaptura, match="não anunciado"):
        validar_modo(ModoCaptura("MJPG", 1234, 567, 30), ANUNCIADOS)


def test_fps_inexistente_para_o_formato():
    with pytest.raises(ErroCaptura, match="fps não anunciado"):
        validar_modo(ModoCaptura("YUYV", 1280, 720, 30), ANUNCIADOS)


def test_sem_intervalos_aceita_qualquer_fps():
    validar_modo(ModoCaptura("YUYV", 640, 480, 15), ANUNCIADOS)


def test_divergencias():
    pedido = ModoCaptura("MJPG", 1234, 567, 30)
    assert divergencias(pedido, pedido) == []
    erros = divergencias(pedido, ModoCaptura("MJPG", 1280, 720, 15))
    assert len(erros) == 2


REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"

# Exposição manual usada para medir FPS. 78 é o padrão do driver e manteve 30 fps
# na medição de 2026-11-19 (unidade da Redeagle ainda não confirmada, ver CLAUDE.md).
EXPOSICAO_TESTE = 78


@pytest.fixture
def exposicao_fixa():
    """Põe a Redeagle em exposição manual e restaura os valores originais no final.

    Em automático (Aperture Priority), o firmware alonga o tempo de frame com pouca
    luz (15–18 fps com 30 pedidos), e a Redeagle não tem exposure_dynamic_framerate
    para desligar isso. Sem esta fixture, o teste de FPS dependeria da luz do ambiente.
    """
    with ControlesCamera(REDEAGLE) as c:
        orig = {n: c.ler(n) for n in ("auto_exposure", "exposure_time_absolute")}
        try:
            c.escrever("auto_exposure", 1)  # Manual Mode: a exposição fica ativa
            c.escrever("exposure_time_absolute", EXPOSICAO_TESTE)
            yield
        finally:
            # a exposição só aceita escrita em manual: restaurar ela antes do modo
            c.escrever("auto_exposure", 1)
            c.escrever("exposure_time_absolute", orig["exposure_time_absolute"])
            c.escrever("auto_exposure", orig["auto_exposure"])
        assert {n: c.ler(n) for n in orig} == orig


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
@pytest.mark.parametrize("modo", [ModoCaptura("MJPG", 2560, 1440, 30), ModoCaptura("YUYV", 640, 480, 30)])
def test_captura_real(modo, exposicao_fixa):
    with Captura(REDEAGLE, modo) as cap:
        assert cap.negociado == modo
        frame = cap.ler()
        assert frame.shape == (modo.altura, modo.largura, 3)
        assert cap.medir_fps(20) > modo.fps * 0.8


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_captura_real_recusa_modo_invalido():
    with pytest.raises(ErroCaptura, match="não anunciado"):
        Captura(REDEAGLE, ModoCaptura("MJPG", 1234, 567, 30))
