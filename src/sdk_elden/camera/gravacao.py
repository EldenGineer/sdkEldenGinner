"""Gravação de vídeo: frames BGR -> ffmpeg (processo externo) -> MP4 H.264 ou MKV MJPG.

Decisão do usuário (2026-11-19): gravar via o ffmpeg do sistema, porque o opencv-python-headless
instalado NÃO tem H.264 (avc1/H264/X264 falharam no VideoWriter; MJPG/mp4v/FFV1 funcionaram).

Taxa de quadros: a câmera nem sempre entrega a taxa negociada (a Redeagle cai para 15 fps,
ver CLAUDE.md). Se o ffmpeg recebesse "30 fps" e chegassem 15, o vídeo tocaria 2x mais rápido.
Por isso `RelogioCFR` usa o horário de chegada de cada frame e REPETE frames para preencher
os buracos (ou descarta, se a câmera vier mais rápida): o arquivo sai com taxa constante
(compatível com qualquer player) e com a DURAÇÃO REAL.

Fluxo: `escrever()` nunca bloqueia quem chama (thread da GUI/captura): o frame vai para uma fila
limitada (FILA_FRAMES) e uma thread própria o empurra para o stdin do ffmpeg. Fila cheia =
frame descartado e contado (`estatisticas().descartados_fila`), nunca travamento.

Arquivos: escreve em `.<nome>.tmp.<ext>` e só renomeia ao terminar com sucesso, como as fotos.
"""
from __future__ import annotations

import argparse
import math
import os
import queue
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from sdk_elden.camera.armazenamento import (
    ARQUIVO_CONFIG,
    SECAO_CONFIG,
    ConfigArmazenamento,
    MetadadosCaptura,
    dados_camera,
    diretorio_destino,
    escrever_sidecar,
    nome_base,
    validar_config,
)

SECAO_GRAVACAO = "gravacao"
FORMATOS_VIDEO = ("mp4", "mkv")          # mp4 = H.264; mkv = MJPG (cada frame um JPEG)
CODIFICADORES_H264 = ("libx264", "h264_nvenc")
FILA_FRAMES = 8                          # 2560x1440 BGR = 11 MB por frame -> ~88 MB no máximo
TEMPO_MAX_FINALIZAR_S = 30.0             # espera explícita pelo ffmpeg fechar o arquivo
_FIM = object()


class ErroGravacao(Exception):
    pass


@dataclass
class ConfigGravacao:
    formato: str = "mp4"
    # libx264 por padrão: em 2560x1440 foi MAIS rápido que o NVENC neste notebook (1,6 s vs 1,9 s
    # para 10 s de vídeo de teste, medido em 2026-11-19), gera arquivo menor e não depende da GPU.
    codificador: str = "libx264"
    qualidade_h264: int = 23     # CRF (libx264) / CQ (nvenc): menor = melhor e maior
    qualidade_mjpeg: int = 3     # -q:v do mjpeg: 2 (melhor) a 31
    ffmpeg: str = "/usr/bin/ffmpeg"  # caminho absoluto explícito, nada de procurar no PATH


def validar_config_gravacao(cfg: ConfigGravacao) -> None:
    if cfg.formato not in FORMATOS_VIDEO:
        raise ErroGravacao(f"formato de vídeo {cfg.formato!r} inválido; opções: {FORMATOS_VIDEO}")
    if cfg.codificador not in CODIFICADORES_H264:
        raise ErroGravacao(f"codificador {cfg.codificador!r} inválido; opções: {CODIFICADORES_H264}")
    if not 0 <= cfg.qualidade_h264 <= 51:
        raise ErroGravacao(f"qualidade_h264 deve estar em [0, 51], veio {cfg.qualidade_h264}")
    if not 2 <= cfg.qualidade_mjpeg <= 31:
        raise ErroGravacao(f"qualidade_mjpeg deve estar em [2, 31], veio {cfg.qualidade_mjpeg}")
    if not Path(cfg.ffmpeg).is_absolute():
        raise ErroGravacao(f"ffmpeg deve ser caminho absoluto: {cfg.ffmpeg!r}")


def montar_comando(cfg: ConfigGravacao, largura: int, altura: int, fps: float, destino: Path) -> list[str]:
    """Linha de comando do ffmpeg: BGR cru pelo stdin, taxa constante `fps`."""
    entrada = [cfg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{largura}x{altura}",
               "-framerate", f"{fps:g}", "-i", "-", "-an"]
    if cfg.formato == "mkv":
        saida = ["-c:v", "mjpeg", "-q:v", str(cfg.qualidade_mjpeg), "-pix_fmt", "yuvj420p"]
    elif cfg.codificador == "h264_nvenc":
        saida = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(cfg.qualidade_h264), "-pix_fmt", "yuv420p"]
    else:
        saida = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.qualidade_h264), "-pix_fmt", "yuv420p"]
    if cfg.formato == "mp4":
        saida += ["-movflags", "+faststart"]  # índice no início: o arquivo abre/rola rápido em players
    # formato do contêiner explícito: o arquivo temporário tem nome .tmp.<ext>
    return entrada + saida + ["-f", "mp4" if cfg.formato == "mp4" else "matroska", str(destino)]


class RelogioCFR:
    """Quantas vezes escrever cada frame para o vídeo de taxa constante manter o tempo real.

    O frame que chega no instante t (segundos, relógio monotônico) deve cobrir as posições
    até round((t - t0) * fps). Câmera lenta -> frame repetido; câmera rápida -> frame descartado (0).
    """

    def __init__(self, fps: float):
        if fps <= 0:
            raise ValueError(f"fps deve ser positivo, veio {fps}")
        self.fps = fps
        self._t0: float | None = None
        self.escritos = 0

    def vezes(self, t: float) -> int:
        if self._t0 is None:
            self._t0 = t
        alvo = math.floor((t - self._t0) * self.fps + 0.5) + 1  # posições que devem existir até t
        n = max(alvo - self.escritos, 0)
        self.escritos += n
        return n


@dataclass(frozen=True)
class Estatisticas:
    recebidos: int          # frames entregues a escrever()
    escritos: int           # frames no arquivo (inclui repetições)
    repetidos: int          # cópias extras para cobrir buracos (câmera abaixo da taxa)
    descartados_relogio: int  # câmera acima da taxa: frame sobrando
    descartados_fila: int   # ffmpeg/disco não acompanharam: fila cheia
    duracao_s: float        # escritos / fps


class Gravador:
    """Uma gravação. `escrever(frame, t)` para cada frame; `finalizar()` fecha e devolve o arquivo."""

    def __init__(self, cfg: ConfigGravacao, destino: Path, largura: int, altura: int, fps: float,
                 fila: int = FILA_FRAMES):
        validar_config_gravacao(cfg)
        if not Path(cfg.ffmpeg).exists():
            raise ErroGravacao(f"ffmpeg não encontrado em {cfg.ffmpeg} (ajuste [gravacao] ffmpeg na config)")
        if destino.exists():
            raise ErroGravacao(f"já existe {destino}")
        self.cfg, self.destino = cfg, destino
        self.largura, self.altura, self.fps = largura, altura, fps
        self._tmp = destino.with_name(f".{destino.stem}.tmp{destino.suffix}")
        self._relogio = RelogioCFR(fps)
        self._fila: queue.Queue = queue.Queue(maxsize=fila)
        self._recebidos = self._repetidos = self._desc_relogio = self._desc_fila = 0
        self._erro: str | None = None
        self._finalizado = False
        self.inicio = datetime.now().astimezone()  # sobrescrito por iniciar_gravacao
        self.t_inicio = time.monotonic()  # cronômetro (relógio monotônico)
        try:
            self._proc = subprocess.Popen(
                montar_comando(cfg, largura, altura, fps, self._tmp),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise ErroGravacao(f"não foi possível iniciar o ffmpeg ({cfg.ffmpeg}): {e}") from e
        self._thread = threading.Thread(target=self._escritor, name="gravador-ffmpeg", daemon=True)
        self._thread.start()

    # --- produção (thread de quem chama) ---------------------------------------------
    def escrever(self, frame: np.ndarray, t: float | None = None) -> None:
        """Enfileira um frame BGR. Não bloqueia. `t` = instante de chegada (time.monotonic())."""
        if self._finalizado:
            raise ErroGravacao("gravação já finalizada")
        if self._erro:
            raise ErroGravacao(self._erro)
        if frame.shape != (self.altura, self.largura, 3) or frame.dtype != np.uint8:
            raise ErroGravacao(f"frame {frame.shape} {frame.dtype} diferente do esperado "
                               f"({self.altura}, {self.largura}, 3) uint8")
        self._recebidos += 1
        n = self._relogio.vezes(time.monotonic() if t is None else t)
        if n == 0:
            self._desc_relogio += 1
            return
        try:
            self._fila.put_nowait((frame, n))
        except queue.Full:
            self._desc_fila += 1
            self._relogio.escritos -= n  # não entrou: as posições continuam vagas para o próximo
            return
        self._repetidos += n - 1

    # --- consumo (thread própria) ----------------------------------------------------
    def _escritor(self) -> None:
        while True:
            item = self._fila.get()
            if item is _FIM:
                return
            frame, n = item
            dados = np.ascontiguousarray(frame).tobytes()
            try:
                for _ in range(n):
                    self._proc.stdin.write(dados)
            except (BrokenPipeError, OSError) as e:
                self._erro = f"ffmpeg parou de aceitar frames ({e}): {self._stderr()}"
                return

    def _stderr(self) -> str:
        try:
            return (self._proc.stderr.read() or b"").decode(errors="replace").strip()[-800:]
        except (OSError, ValueError):
            return ""

    # --- consulta e fim ----------------------------------------------------------------
    @property
    def erro(self) -> str | None:
        return self._erro

    def estatisticas(self) -> Estatisticas:
        escritos = self._relogio.escritos
        return Estatisticas(self._recebidos, escritos, self._repetidos, self._desc_relogio,
                            self._desc_fila, escritos / self.fps)

    def finalizar(self) -> Path:
        """Espera a fila esvaziar, fecha o ffmpeg e renomeia o temporário. Levanta se algo falhou."""
        if self._finalizado:
            return self.destino
        self._finalizado = True
        self._fila.put(_FIM)  # bloqueante de propósito: o que já entrou na fila vai para o arquivo
        self._thread.join()
        try:
            self._proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            codigo = self._proc.wait(timeout=TEMPO_MAX_FINALIZAR_S)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
            self._tmp.unlink(missing_ok=True)
            raise ErroGravacao(f"ffmpeg não terminou em {TEMPO_MAX_FINALIZAR_S:g} s; gravação descartada")
        if self._erro or codigo != 0 or self._relogio.escritos == 0:
            motivo = self._erro or (f"ffmpeg saiu com código {codigo}: {self._stderr()}" if codigo
                                    else "nenhum frame gravado")
            self._tmp.unlink(missing_ok=True)
            raise ErroGravacao(motivo)
        os.replace(self._tmp, self.destino)
        return self.destino

    def cancelar(self) -> None:
        """Interrompe sem gerar arquivo (ex.: câmera caiu)."""
        self._finalizado = True
        self._proc.kill()
        self._proc.wait()
        try:
            self._fila.put_nowait(_FIM)
        except queue.Full:
            pass
        self._thread.join(timeout=5)
        self._tmp.unlink(missing_ok=True)


def iniciar_gravacao(cfg_arm: ConfigArmazenamento, cfg_grav: ConfigGravacao, meta: MetadadosCaptura,
                     agora: datetime | None = None, fila: int = FILA_FRAMES) -> Gravador:
    """Cria o Gravador no destino das capturas (raiz/repo/subrepo), nome no padrão das fotos."""
    validar_config(cfg_arm)
    agora = agora or datetime.now().astimezone()
    pasta = diretorio_destino(cfg_arm)
    pasta.mkdir(parents=True, exist_ok=True)
    n = meta.modo_negociado
    destino = pasta / f"{nome_base(agora, meta.camera_nome, n.largura, n.altura)}.{cfg_grav.formato}"
    g = Gravador(cfg_grav, destino, n.largura, n.altura, n.fps, fila=fila)
    g.inicio = agora
    return g


def finalizar_com_sidecar(g: Gravador, cfg_arm: ConfigArmazenamento, meta: MetadadosCaptura) -> Path:
    """Fecha a gravação e escreve o JSON ao lado (câmera, modo, controles, estatísticas)."""
    arquivo = g.finalizar()
    est = g.estatisticas()
    escrever_sidecar(arquivo.with_suffix(".json"), {
        "arquivo": arquivo.name,
        "tipo": "video",
        "iniciado_em": g.inicio.isoformat(timespec="milliseconds"),
        "repo": cfg_arm.repo,
        "subrepo": cfg_arm.subrepo,
        "gravacao": asdict(g.cfg),
        **dados_camera(meta),
        "fps_arquivo": g.fps,
        "estatisticas": asdict(est),
    })
    return arquivo


def main() -> None:
    from sdk_elden.camera.captura import Captura, ErroCaptura, ModoCaptura
    from sdk_elden.camera.controles import ControlesCamera
    from sdk_elden.camera.dispositivos import ler_camera
    from sdk_elden.utils.config import ErroConfig, carregar_secao

    ap = argparse.ArgumentParser(description="Grava vídeo de uma câmera num modo explícito")
    ap.add_argument("dispositivo", help="/dev/videoN ou /dev/v4l/by-id/...")
    ap.add_argument("--fourcc", required=True, help="ex.: MJPG, YUYV")
    ap.add_argument("--largura", type=int, required=True)
    ap.add_argument("--altura", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--segundos", type=float, required=True)
    ap.add_argument("--formato", choices=FORMATOS_VIDEO, help="sobrepõe [gravacao] formato da config")
    ap.add_argument("--codificador", choices=CODIFICADORES_H264, help="sobrepõe [gravacao] codificador")
    ap.add_argument("--config", type=Path, default=ARQUIVO_CONFIG, help=f"arquivo TOML (padrão: {ARQUIVO_CONFIG})")
    a = ap.parse_args()
    try:
        cfg_arm = carregar_secao(a.config, SECAO_CONFIG, ConfigArmazenamento)
        cfg_grav = carregar_secao(a.config, SECAO_GRAVACAO, ConfigGravacao)
    except ErroConfig as e:
        raise SystemExit(f"ERRO na config: {e}")
    if a.formato:
        cfg_grav.formato = a.formato
    if a.codificador:
        cfg_grav.codificador = a.codificador

    cam = ler_camera(a.dispositivo)
    modo = ModoCaptura(a.fourcc.upper(), a.largura, a.altura, a.fps)
    try:
        with Captura(a.dispositivo, modo) as cap, ControlesCamera(a.dispositivo) as ctrl:
            meta = MetadadosCaptura(cam.nome, str(cam.caminho), str(cam.caminho_estavel) if cam.caminho_estavel else None,
                                    cam.driver, cam.barramento, modo, cap.negociado, tuple(ctrl.todos()))
            g = iniciar_gravacao(cfg_arm, cfg_grav, meta)
            codec = "mjpeg" if cfg_grav.formato == "mkv" else cfg_grav.codificador
            print(f"gravando {a.segundos:g} s em {g.destino} ({cfg_grav.formato}, {codec})…")
            fim = time.monotonic() + a.segundos
            try:
                while time.monotonic() < fim:
                    frame = cap.ler()
                    g.escrever(frame, time.monotonic())
            except BaseException:
                g.cancelar()
                raise
            arquivo = finalizar_com_sidecar(g, cfg_arm, meta)
    except (ErroCaptura, ErroGravacao) as e:
        raise SystemExit(f"ERRO: {e}")
    est = g.estatisticas()
    print(f"ok: {arquivo}")
    print(f"recebidos={est.recebidos} escritos={est.escritos} repetidos={est.repetidos} "
          f"descartados(relógio)={est.descartados_relogio} descartados(fila)={est.descartados_fila} "
          f"duração={est.duracao_s:.2f} s")


if __name__ == "__main__":
    main()
