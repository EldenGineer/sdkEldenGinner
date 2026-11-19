import glob
from fractions import Fraction

import pytest

from sdk_elden.camera import dispositivos as d


def test_mapa_by_id_resolve_links(tmp_path):
    alvo = tmp_path / "video7"
    alvo.touch()
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    (by_id / "usb-Cam_X-video-index0").symlink_to(alvo)
    assert d.mapa_by_id(by_id) == {alvo: by_id / "usb-Cam_X-video-index0"}


def test_mapa_by_id_sem_diretorio(tmp_path):
    assert d.mapa_by_id(tmp_path / "nao_existe") == {}


def test_fourcc():
    assert d._fourcc(0x47504A4D) == "MJPG"


def test_nome_config_igual_v4l2ctl():
    assert d.nome_config("Exposure Time, Absolute") == "exposure_time_absolute"
    assert d.nome_config("White Balance, Automatic") == "white_balance_automatic"
    assert d.nome_config("Focus (absolute)") == "focus_absolute"


def test_fmt_fps():
    assert d._fmt_fps((Fraction(30), Fraction(15))) == "30, 15 fps"
    assert d._fmt_fps(()) == "fps não informado"


@pytest.mark.hardware
@pytest.mark.skipif(not glob.glob("/dev/video*"), reason="sem câmeras conectadas")
def test_lista_so_nos_de_captura():
    cams = d.listar_cameras()
    assert cams, "esperava ao menos uma câmera de captura"
    for c in cams:
        assert c.modos, f"{c.caminho} sem modos anunciados"
