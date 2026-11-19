import json
import os
import subprocess
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from sdk_elden.camera.armazenamento import ConfigArmazenamento, MetadadosCaptura
from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.gravacao import (
    ConfigGravacao,
    ErroGravacao,
    Gravador,
    RelogioCFR,
    finalizar_com_sidecar,
    iniciar_gravacao,
    montar_comando,
    validar_config_gravacao,
)

FFMPEG = Path(ConfigGravacao().ffmpeg)
FFPROBE = FFMPEG.with_name("ffprobe")
# os testes entregam frames em rajada (muito mais rápido que tempo real): fila grande para não
# descartar; o descarte por fila cheia tem teste próprio
RAJADA = 1000
precisa_ffmpeg = pytest.mark.skipif(not (FFMPEG.exists() and FFPROBE.exists()), reason="ffmpeg/ffprobe ausentes")


# --- RelogioCFR (puro) -----------------------------------------------------------------
def test_relogio_camera_na_taxa_escreve_um_por_frame():
    r = RelogioCFR(30)
    assert [r.vezes(i / 30) for i in range(10)] == [1] * 10


def test_relogio_camera_na_metade_repete_e_mantem_duracao():
    """Redeagle caindo para 15 fps: cada frame vira 2 e o vídeo dura o tempo real."""
    r = RelogioCFR(30)
    vezes = [r.vezes(i / 15) for i in range(31)]  # 2 s reais
    assert vezes[0] == 1 and all(v == 2 for v in vezes[1:])
    assert r.escritos / 30 == pytest.approx(2.0, abs=1 / 30)


def test_relogio_camera_rapida_descarta():
    r = RelogioCFR(30)
    vezes = [r.vezes(i / 60) for i in range(60)]
    assert vezes.count(0) == pytest.approx(30, abs=1)
    assert r.escritos == pytest.approx(30, abs=1)


def test_relogio_tolera_jitter():
    r = RelogioCFR(30)
    ts = [i / 30 + (0.008 if i % 2 else -0.008) for i in range(1, 300)]
    r.vezes(0.0)
    vezes = [r.vezes(t) for t in ts]
    assert set(vezes) == {1}  # ±8 ms de atraso não cria repetições/descartes


def test_relogio_fps_invalido():
    with pytest.raises(ValueError):
        RelogioCFR(0)


# --- comando e config (puro) -----------------------------------------------------------
def test_comando_mp4_libx264():
    c = montar_comando(ConfigGravacao(), 640, 480, 30, Path("/x/.v.tmp.mp4"))
    assert c[0] == "/usr/bin/ffmpeg"
    assert c[c.index("-s") + 1] == "640x480" and c[c.index("-framerate") + 1] == "30"
    assert c[c.index("-c:v") + 1] == "libx264" and c[c.index("-crf") + 1] == "23"
    assert c[-3:] == ["-f", "mp4", "/x/.v.tmp.mp4"]


def test_comando_nvenc_e_mkv():
    c = montar_comando(ConfigGravacao(codificador="h264_nvenc", qualidade_h264=19), 640, 480, 30, Path("/v.mp4"))
    assert c[c.index("-c:v") + 1] == "h264_nvenc" and c[c.index("-cq") + 1] == "19"
    c = montar_comando(ConfigGravacao(formato="mkv"), 640, 480, 29.97, Path("/v.mkv"))
    assert c[c.index("-c:v") + 1] == "mjpeg" and c[c.index("-framerate") + 1] == "29.97"
    assert c[-3:-1] == ["-f", "matroska"]


@pytest.mark.parametrize("campo,valor", [("formato", "avi"), ("codificador", "x265"), ("qualidade_h264", 60),
                                         ("qualidade_mjpeg", 1), ("ffmpeg", "ffmpeg")])
def test_config_gravacao_invalida(campo, valor):
    with pytest.raises(ErroGravacao):
        validar_config_gravacao(replace(ConfigGravacao(), **{campo: valor}))


# --- gravação real com ffmpeg (sem câmera) ---------------------------------------------
def sondar(arquivo: Path) -> dict:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,nb_read_frames,r_frame_rate", "-of", "json", str(arquivo)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]


def gerar(g: Gravador, n: int, fps_camera: float, l=64, a=48):
    for i in range(n):
        frame = np.full((a, l, 3), (i * 7) % 255, np.uint8)
        g.escrever(frame, i / fps_camera)


@precisa_ffmpeg
@pytest.mark.parametrize("cfg,codec", [(ConfigGravacao(), "h264"), (ConfigGravacao(formato="mkv"), "mjpeg")])
def test_grava_arquivo_valido(tmp_path, cfg, codec):
    destino = tmp_path / f"v.{cfg.formato}"
    g = Gravador(cfg, destino, 64, 48, 30, fila=RAJADA)
    gerar(g, 30, 30)
    assert g.finalizar() == destino
    s = sondar(destino)
    assert (s["codec_name"], s["width"], s["height"]) == (codec, 64, 48)
    assert int(s["nb_read_frames"]) == 30 and Fraction(s["r_frame_rate"]) == 30
    assert not list(tmp_path.glob(".*tmp*"))  # temporário renomeado


@precisa_ffmpeg
def test_camera_lenta_gera_duracao_real(tmp_path):
    g = Gravador(ConfigGravacao(), tmp_path / "v.mp4", 64, 48, 30, fila=RAJADA)
    gerar(g, 31, 15)  # 2 s reais a 15 fps
    g.finalizar()
    est = g.estatisticas()
    assert est.recebidos == 31 and est.repetidos == 30 and est.duracao_s == pytest.approx(2.0, abs=0.05)
    assert int(sondar(tmp_path / "v.mp4")["nb_read_frames"]) == est.escritos


@precisa_ffmpeg
def test_fila_cheia_descarta_conta_e_arquivo_bate(tmp_path):
    g = Gravador(ConfigGravacao(), tmp_path / "v.mp4", 64, 48, 30, fila=1)
    gerar(g, 60, 30)
    g.finalizar()
    est = g.estatisticas()
    assert est.descartados_fila > 0  # rajada com fila 1: o ffmpeg não acompanha
    assert est.recebidos == 60
    assert int(sondar(tmp_path / "v.mp4")["nb_read_frames"]) == est.escritos  # contagem honesta


@precisa_ffmpeg
def test_codec_que_falha_vira_erro_e_nao_deixa_lixo(tmp_path):
    # largura ímpar: yuv420p exige dimensões pares, o libx264 recusa (falha real do ffmpeg)
    g = Gravador(ConfigGravacao(), tmp_path / "v.mp4", 63, 48, 30)
    with pytest.raises(ErroGravacao):
        gerar(g, 5, 30, l=63)
        time.sleep(0.5)
        gerar(g, 5, 30, l=63)
        g.finalizar()
    assert not list(tmp_path.iterdir())


def test_ffmpeg_inexistente(tmp_path):
    with pytest.raises(ErroGravacao, match="não encontrado"):
        Gravador(ConfigGravacao(ffmpeg="/nao/existe/ffmpeg"), tmp_path / "v.mp4", 64, 48, 30)


@precisa_ffmpeg
def test_frame_de_tamanho_errado(tmp_path):
    g = Gravador(ConfigGravacao(), tmp_path / "v.mp4", 64, 48, 30)
    with pytest.raises(ErroGravacao, match="diferente do esperado"):
        g.escrever(np.zeros((48, 32, 3), np.uint8), 0.0)
    g.cancelar()
    assert not list(tmp_path.iterdir())


@precisa_ffmpeg
def test_nunca_sobrescreve(tmp_path):
    (tmp_path / "v.mp4").write_bytes(b"x")
    with pytest.raises(ErroGravacao, match="já existe"):
        Gravador(ConfigGravacao(), tmp_path / "v.mp4", 64, 48, 30)


@precisa_ffmpeg
def test_iniciar_e_finalizar_com_sidecar(tmp_path):
    modo = ModoCaptura("MJPG", 64, 48, 30.0)
    meta = MetadadosCaptura("Cam Teste: x", "/dev/video9", None, "uvcvideo", "usb-1", modo, modo, ())
    cfg_arm = ConfigArmazenamento(raiz=str(tmp_path), repo="r", subrepo="s")
    g = iniciar_gravacao(cfg_arm, ConfigGravacao(), meta, fila=RAJADA)
    assert g.destino.parent == tmp_path / "r" / "s" and g.destino.name.endswith("_Cam_Teste_64x48.mp4")
    gerar(g, 10, 30)
    arquivo = finalizar_com_sidecar(g, cfg_arm, meta)
    dados = json.loads(arquivo.with_suffix(".json").read_text())
    assert dados["tipo"] == "video" and dados["arquivo"] == arquivo.name
    assert dados["estatisticas"]["escritos"] == 10 and dados["gravacao"]["codificador"] == "libx264"
    assert dados["camera"]["caminho"] == "/dev/video9"


REDEAGLE = "/dev/v4l/by-id/usb-XC-TECH_2k_usb_Camera_Redeagle_20250820.1412-video-index0"


@pytest.mark.hardware
@precisa_ffmpeg
@pytest.mark.skipif(not os.path.exists(REDEAGLE), reason="Redeagle não conectada")
def test_grava_da_camera_real(tmp_path):
    from sdk_elden.camera.captura import Captura

    modo = ModoCaptura("MJPG", 1280, 720, 30)
    destino = tmp_path / "real.mp4"
    with Captura(REDEAGLE, modo) as cap:
        g = Gravador(ConfigGravacao(), destino, 1280, 720, cap.negociado.fps)
        fim = time.monotonic() + 2
        chegadas = []
        while time.monotonic() < fim:
            frame = cap.ler()
            chegadas.append(time.monotonic())
            g.escrever(frame, chegadas[-1])
        g.finalizar()
    est = g.estatisticas()
    s = sondar(destino)
    assert (s["width"], s["height"]) == (1280, 720)
    assert est.descartados_fila == 0
    # o vídeo começa no 1º frame (não na abertura do stream, que leva ~0,2 s): a duração real é o
    # intervalo entre o 1º e o último frame + 1 quadro, qualquer que seja o FPS entregue pela câmera
    real = chegadas[-1] - chegadas[0] + 1 / cap.negociado.fps
    assert est.duracao_s == pytest.approx(real, abs=1.5 / cap.negociado.fps)
