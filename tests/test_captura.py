import os
from fractions import Fraction

import pytest

from sdk_elden.camera.captura import Captura, ErroCaptura, ModoCaptura, divergencias, validar_modo
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


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
@pytest.mark.parametrize("modo", [ModoCaptura("MJPG", 2560, 1440, 30), ModoCaptura("YUYV", 640, 480, 30)])
def test_captura_real(modo):
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
