import os
from dataclasses import replace

import pytest

from sdk_elden.camera.controles import ControlesCamera, ErroControle, validar_valor
from sdk_elden.camera.dispositivos import InfoControle

INT = InfoControle(
    id=1, nome="gain", tipo="int", suportado=True, minimo=0, maximo=255, passo=1,
    padrao=0, valor=0, inativo=False, somente_leitura=False,
)
MENU = replace(INT, nome="auto_exposure", tipo="menu", minimo=0, maximo=3, padrao=0,
               menu={1: "Manual Mode", 3: "Aperture Priority Mode"})


def test_int_dentro_da_faixa():
    validar_valor(INT, 200)
    validar_valor(INT, True)  # bool vira 1


@pytest.mark.parametrize("valor", [-1, 256])
def test_int_fora_da_faixa(valor):
    with pytest.raises(ErroControle, match="fora da faixa"):
        validar_valor(INT, valor)


def test_step():
    info = replace(INT, minimo=10, maximo=100, passo=5)
    validar_valor(info, 15)
    with pytest.raises(ErroControle, match="step"):
        validar_valor(info, 17)


def test_tipo_errado():
    with pytest.raises(ErroControle, match="inteiro"):
        validar_valor(INT, 1.5)


def test_menu_com_buraco():
    validar_valor(MENU, 3)
    with pytest.raises(ErroControle, match="inválido"):
        validar_valor(MENU, 2)  # o driver pula o índice 2


def test_bitmask():
    info = replace(INT, tipo="bitmask", maximo=0b101)
    validar_valor(info, 0b100)
    with pytest.raises(ErroControle, match="máscara"):
        validar_valor(info, 0b010)


@pytest.mark.parametrize("campo,msg", [("inativo", "inativo"), ("somente_leitura", "somente leitura"),
                                       ("suportado", "não suportado")])
def test_flags_bloqueiam(campo, msg):
    info = replace(INT, **{campo: campo != "suportado"})
    with pytest.raises(ErroControle, match=msg):
        validar_valor(info, 1)


# --- hardware: Redeagle em /dev/video2 (valores restaurados ao final) ---------
REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_escrita_real_e_dependencia_de_exposicao():
    with ControlesCamera(REDEAGLE) as c:
        orig = {n: c.ler(n) for n in ("brightness", "auto_exposure", "exposure_time_absolute")}
        try:
            alvo = 7 if orig["brightness"] != 7 else 6
            assert c.escrever("brightness", alvo) == alvo

            c.escrever("auto_exposure", 3)  # automático -> exposição inativa
            with pytest.raises(ErroControle, match="inativo"):
                c.escrever("exposure_time_absolute", 200)

            c.escrever("auto_exposure", 1)  # manual -> exposição ativa
            assert c.escrever("exposure_time_absolute", 200) == 200

            with pytest.raises(ErroControle, match="quirk"):
                c.restaurar_padrao("auto_exposure")
        finally:
            c.escrever("auto_exposure", 1)
            c.escrever("exposure_time_absolute", orig["exposure_time_absolute"])
            c.escrever("auto_exposure", orig["auto_exposure"])
            c.escrever("brightness", orig["brightness"])
        assert {n: c.ler(n) for n in orig} == orig
