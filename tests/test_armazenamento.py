import json
from dataclasses import replace
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from sdk_elden.camera.armazenamento import (
    ConfigArmazenamento,
    ErroArmazenamento,
    MetadadosCaptura,
    salvar_captura,
    slug,
    validar_config,
)
from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.dispositivos import InfoControle

AGORA = datetime(2026, 11, 19, 14, 30, 12, 123456, tzinfo=timezone.utc)
MODO = ModoCaptura("MJPG", 64, 48, 30.0)
CTRL = InfoControle(id=1, nome="auto_exposure", tipo="menu", suportado=True, minimo=0, maximo=3, passo=1,
                    padrao=0, valor=1, inativo=False, somente_leitura=False, menu={1: "Manual Mode"})
NAO_SUP = replace(CTRL, nome="roi", tipo="0x107", suportado=False, valor=None, menu={})
META = MetadadosCaptura("2k usb Camera Redeagle: 2k usb ", "/dev/video2", "/dev/v4l/by-id/x", "uvcvideo",
                        "usb-1", MODO, MODO, (CTRL, NAO_SUP))


def frame():
    f = np.zeros((48, 64, 3), np.uint8)
    f[:, :32] = (255, 0, 0)  # metade azul (BGR)
    return f


def cfg(tmp_path, **kw):
    return ConfigArmazenamento(raiz=str(tmp_path), repo="proj", subrepo="lote_01", **kw)


def test_slug():
    assert slug("2k usb Camera Redeagle: 2k usb ") == "2k_usb_Camera_Redeagle"
    assert slug(":::") == "camera"


@pytest.mark.parametrize("campo,valor", [("repo", "../fora"), ("repo", "a/b"), ("subrepo", ".oculto"),
                                         ("subrepo", ""), ("raiz", "relativo/x"), ("formato", "bmp"),
                                         ("qualidade_jpg", 0)])
def test_config_invalida(tmp_path, campo, valor):
    with pytest.raises(ErroArmazenamento):
        validar_config(replace(cfg(tmp_path), **{campo: valor}))


def test_salva_png_sem_perda_e_sidecar(tmp_path):
    img = salvar_captura(frame(), META, cfg(tmp_path), AGORA)
    assert img == tmp_path / "proj" / "lote_01" / "20261119_143012_123_2k_usb_Camera_Redeagle_64x48.png"
    assert np.array_equal(cv2.imread(str(img)), frame())
    meta = json.loads(img.with_suffix(".json").read_text())
    assert meta["arquivo"] == img.name and meta["repo"] == "proj" and meta["subrepo"] == "lote_01"
    assert meta["capturado_em"] == "2026-11-19T14:30:12.123+00:00"
    assert meta["camera"]["nome"] == "2k usb Camera Redeagle: 2k usb"
    assert meta["modo_negociado"] == {"fourcc": "MJPG", "largura": 64, "altura": 48, "fps": 30.0}
    assert meta["controles"] == {"auto_exposure": {"valor": 1, "inativo": False, "menu": "Manual Mode"}}
    assert meta["qualidade_jpg"] is None
    assert not list(img.parent.glob(".*"))  # sem temporários


def test_salva_jpg_com_qualidade(tmp_path):
    img = salvar_captura(frame(), META, cfg(tmp_path, formato="jpg", qualidade_jpg=80), AGORA)
    assert img.suffix == ".jpg" and cv2.imread(str(img)).shape == (48, 64, 3)
    assert json.loads(img.with_suffix(".json").read_text())["qualidade_jpg"] == 80


def test_nunca_sobrescreve(tmp_path):
    salvar_captura(frame(), META, cfg(tmp_path), AGORA)
    with pytest.raises(ErroArmazenamento, match="já existe"):
        salvar_captura(frame(), META, cfg(tmp_path), AGORA)


def test_imwrite_que_lanca_cv2_error_vira_erro(tmp_path):
    vazio = np.zeros((0, 0, 3), np.uint8)  # imwrite lança cv2.error com imagem vazia
    with pytest.raises(ErroArmazenamento, match="rejeitou"):
        salvar_captura(vazio, META, cfg(tmp_path), AGORA)
    assert not list((tmp_path / "proj" / "lote_01").iterdir())  # nada: nem sidecar órfão, nem temporário


def test_imwrite_que_retorna_false_vira_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: False)
    with pytest.raises(ErroArmazenamento, match="retornou False"):
        salvar_captura(frame(), META, cfg(tmp_path), AGORA)
    assert not list((tmp_path / "proj" / "lote_01").iterdir())
