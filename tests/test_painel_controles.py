import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QSlider, QSpinBox

from sdk_elden.camera.controles import ControlesCamera
from sdk_elden.camera.dispositivos import InfoControle
from sdk_elden.camera.gui.painel_controles import EditorControle, PainelControles

INT = InfoControle(id=1, nome="gain", tipo="int", suportado=True, minimo=0, maximo=255, passo=1,
                   padrao=0, valor=10, inativo=False, somente_leitura=False)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def editor(info):
    escritas = []
    e = EditorControle(info, lambda n, v: escritas.append((n, v)), lambda n: None)
    return e, escritas


def test_int_vira_slider_e_spinbox_sincronizados(app):
    e, escritas = editor(INT)
    slider, spin = e.findChild(QSlider), e.findChild(QSpinBox)
    assert (slider.minimum(), slider.maximum(), spin.value()) == (0, 255, 10)
    slider.setValue(42)
    assert spin.value() == 42 and escritas == [("gain", 42)]
    spin.setValue(43)
    assert slider.value() == 43


def test_atualizar_nao_dispara_escrita(app):
    e, escritas = editor(INT)
    e.atualizar(replace(INT, valor=99))
    assert e.findChild(QSpinBox).value() == 99 and escritas == []


def test_bool_e_menu(app):
    e, esc = editor(replace(INT, nome="wb", tipo="bool", minimo=0, maximo=1, valor=1))
    assert e.findChild(QCheckBox).isChecked()
    e2, _ = editor(replace(INT, nome="ae", tipo="menu", minimo=0, maximo=3, valor=3,
                           menu={1: "Manual Mode", 3: "Aperture Priority Mode"}))
    cb = e2.findChild(QComboBox)
    assert [cb.itemText(i) for i in range(cb.count())] == ["Manual Mode", "Aperture Priority Mode"]
    assert cb.currentData() == 3


def test_menu_com_valor_fora_do_anunciado_aparece(app):
    e, _ = editor(replace(INT, tipo="menu", minimo=0, maximo=3, valor=0, menu={1: "M", 3: "A"}))
    assert "fora do menu" in e.findChild(QComboBox).currentText()


@pytest.mark.parametrize("campo", ["inativo", "somente_leitura"])
def test_flags_desabilitam(app, campo):
    e, _ = editor(replace(INT, **{campo: True}))
    assert not e.findChild(QSpinBox).isEnabled()


def test_nao_suportado_e_int64_gigante(app):
    e, _ = editor(replace(INT, tipo="0x107", suportado=False, valor=None))
    assert "não suportado" in e.findChild(QLabel).text()
    e2, _ = editor(replace(INT, tipo="int64", maximo=2**40))
    assert "excede int32" in e2.findChild(QLabel).text()


def test_remontar_nao_deixa_widgets_fantasmas(app):
    p = PainelControles()
    conteudo = p._grade.parentWidget()
    p._montar()
    p._montar()
    # sem câmera: só o rótulo "nenhuma câmera selecionada", mesmo sem rodar o loop de eventos
    rotulos = [w for w in conteudo.findChildren(QLabel) if w.parent() is conteudo]
    assert [r.text() for r in rotulos] == ["nenhuma câmera selecionada"]


REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"


@pytest.mark.hardware
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_painel_real_dependencia_exposicao(app):
    with ControlesCamera(REDEAGLE) as c:
        orig = {n: c.ler(n) for n in ("auto_exposure", "exposure_time_absolute")}
    p = PainelControles()
    p.definir_camera(REDEAGLE)
    try:
        ae = p._editores["auto_exposure"].findChild(QComboBox)
        exp = p._editores["exposure_time_absolute"].findChild(QSpinBox)

        p._escrever("auto_exposure", 3)
        assert not exp.isEnabled()
        p._escrever("auto_exposure", 1)  # Manual -> painel relê e habilita a exposição
        assert ae.currentData() == 1 and exp.isEnabled()

        p._restaurar("auto_exposure")  # quirk: padrão 0 inválido -> erro visível, sem crash
        assert "quirk" in p.lbl_erro.text()
    finally:
        p._escrever("auto_exposure", 1)
        p._escrever("exposure_time_absolute", orig["exposure_time_absolute"])
        p._escrever("auto_exposure", orig["auto_exposure"])
        p.fechar()
    with ControlesCamera(REDEAGLE) as c:
        assert {n: c.ler(n) for n in orig} == orig
