"""Modo rajada (burst): capturas automáticas a cada `intervalo_s`, até `quantidade` fotos.

Guiado pela CHEGADA dos frames, não por um timer: a cada horário agendado, a foto é o primeiro
frame que chegar depois dele. Assim nunca se salva o mesmo frame duas vezes e a precisão fica em
~1 intervalo de frame (33 ms a 30 fps).

Agenda ancorada no início (t0, t0+i, t0+2i, ...): não acumula atraso. Se um frame chega tarde
demais e passa por cima de horários (câmera travou), esses horários são PULADOS e contados em
`perdidas`, em vez de disparar várias fotos seguidas para "recuperar".

Salvar é lento (PNG 2560x1440 ~65 ms): as fotos vão para uma FilaTrabalho. Fila cheia = foto
descartada e contada, nunca trava quem captura.
"""
from __future__ import annotations

import argparse
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sdk_elden.camera.armazenamento import (
    ARQUIVO_CONFIG,
    SECAO_CONFIG,
    ConfigArmazenamento,
    MetadadosCaptura,
    salvar_captura,
    slug,
)

SECAO_RAJADA = "rajada"
INTERVALO_MIN_S = 0.05   # 20 fotos/s; abaixo disso o salvamento (PNG ~65 ms) não acompanha
FILA_FOTOS = 16          # 2560x1440 BGR = 11 MB por foto -> ~180 MB no máximo na fila
TEMPO_MAX_FECHAR_S = 30.0


class ErroRajada(Exception):
    pass


@dataclass
class ConfigRajada:
    intervalo_s: float = 1.0
    quantidade: int = 10  # 0 = sem limite (até parar)


def validar_config_rajada(cfg: ConfigRajada) -> None:
    if not INTERVALO_MIN_S <= cfg.intervalo_s <= 24 * 3600:
        raise ErroRajada(f"intervalo_s deve estar em [{INTERVALO_MIN_S}, 86400], veio {cfg.intervalo_s}")
    if cfg.quantidade < 0:
        raise ErroRajada(f"quantidade deve ser >= 0 (0 = sem limite), veio {cfg.quantidade}")


class AgendaRajada:
    """Decide, a cada frame que chega, se ele vira foto. Lógica pura (sem I/O)."""

    def __init__(self, cfg: ConfigRajada):
        validar_config_rajada(cfg)
        self.cfg = cfg
        self._t0: float | None = None
        self._slot = 0          # índice do próximo horário agendado
        self.feitas = 0
        self.perdidas = 0       # horários pulados (nenhum frame chegou dentro deles)

    @property
    def terminou(self) -> bool:
        return self.cfg.quantidade > 0 and self.feitas >= self.cfg.quantidade

    def deve_capturar(self, t: float) -> bool:
        """`t` = instante de chegada do frame (time.monotonic()). O 1º frame sempre vira foto."""
        if self.terminou:
            return False
        if self._t0 is None:
            self._t0 = t
        i = self.cfg.intervalo_s
        slot_atual = math.floor((t - self._t0) / i + 1e-9)  # último horário já alcançado por t
        if slot_atual < self._slot:
            return False
        self.perdidas += slot_atual - self._slot  # horários que passaram sem foto
        self._slot = slot_atual + 1
        self.feitas += 1
        return True

    def proximo_em(self, t: float) -> float | None:
        """Segundos até o próximo horário (None antes de começar ou depois de terminar)."""
        if self._t0 is None or self.terminou:
            return None
        return max(self._t0 + self._slot * self.cfg.intervalo_s - t, 0.0)


def bloco_sidecar(id_rajada: str, indice: int, cfg: ConfigRajada) -> dict:
    """Campos extras do JSON de cada foto da rajada (vai em salvar_captura(extra=...))."""
    return {"rajada": {"id": id_rajada, "indice": indice, "intervalo_s": cfg.intervalo_s,
                       "quantidade": cfg.quantidade}}


def id_rajada(agora: datetime, camera_nome: str) -> str:
    return f"{agora:%Y%m%d_%H%M%S}_{slug(camera_nome)}"


def main() -> None:
    from sdk_elden.camera.captura import Captura, ErroCaptura, ModoCaptura
    from sdk_elden.camera.controles import ControlesCamera
    from sdk_elden.camera.dispositivos import ler_camera
    from sdk_elden.utils.config import ErroConfig, carregar_secao
    from sdk_elden.utils.fila_trabalho import FilaTrabalho

    ap = argparse.ArgumentParser(description="Capturas automáticas em intervalo fixo (modo rajada)")
    ap.add_argument("dispositivo", help="/dev/videoN ou /dev/v4l/by-id/...")
    ap.add_argument("--fourcc", required=True, help="ex.: MJPG, YUYV")
    ap.add_argument("--largura", type=int, required=True)
    ap.add_argument("--altura", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--intervalo", type=float, help="segundos entre fotos (sobrepõe [rajada] intervalo_s)")
    ap.add_argument("--quantidade", type=int, help="nº de fotos; 0 = até Ctrl+C (sobrepõe [rajada] quantidade)")
    ap.add_argument("--config", type=Path, default=ARQUIVO_CONFIG, help=f"arquivo TOML (padrão: {ARQUIVO_CONFIG})")
    a = ap.parse_args()
    try:
        cfg_arm = carregar_secao(a.config, SECAO_CONFIG, ConfigArmazenamento)
        cfg = carregar_secao(a.config, SECAO_RAJADA, ConfigRajada)
    except ErroConfig as e:
        raise SystemExit(f"ERRO na config: {e}")
    if a.intervalo is not None:
        cfg.intervalo_s = a.intervalo
    if a.quantidade is not None:
        cfg.quantidade = a.quantidade
    try:
        agenda = AgendaRajada(cfg)
    except ErroRajada as e:
        raise SystemExit(f"ERRO: {e}")

    cam = ler_camera(a.dispositivo)
    modo = ModoCaptura(a.fourcc.upper(), a.largura, a.altura, a.fps)
    erros: list[str] = []
    trava = threading.Lock()

    def ao_falhar(e: BaseException) -> None:
        with trava:
            erros.append(str(e))

    fila = FilaTrabalho(salvar_captura, FILA_FOTOS, ao_falhar=ao_falhar, nome="rajada-salvar")
    ident = id_rajada(datetime.now().astimezone(), cam.nome)
    limite = "até Ctrl+C" if cfg.quantidade == 0 else f"{cfg.quantidade} fotos"
    try:
        with Captura(a.dispositivo, modo) as cap, ControlesCamera(a.dispositivo) as ctrl:
            print(f"rajada {ident}: a cada {cfg.intervalo_s:g} s, {limite} ({cfg_arm.formato})")
            try:
                while not agenda.terminou:
                    frame = cap.ler()
                    if not agenda.deve_capturar(time.monotonic()):
                        continue
                    meta = MetadadosCaptura(cam.nome, str(cam.caminho),
                                            str(cam.caminho_estavel) if cam.caminho_estavel else None,
                                            cam.driver, cam.barramento, modo, cap.negociado, tuple(ctrl.todos()))
                    fila.enviar(frame, meta, cfg_arm, datetime.now().astimezone(),
                                bloco_sidecar(ident, agenda.feitas, cfg))
                    print(f"\r  {agenda.feitas} fotos", end="", flush=True)
            except KeyboardInterrupt:
                print("\n  interrompido pelo usuário")
    except ErroCaptura as e:
        fila.fechar(TEMPO_MAX_FECHAR_S)
        raise SystemExit(f"ERRO: {e}")
    terminou = fila.fechar(TEMPO_MAX_FECHAR_S)
    print(f"\nsalvas={fila.concluidas} descartadas(fila cheia)={fila.descartadas} falhas={fila.falhas} "
          f"horários perdidos={agenda.perdidas}")
    for e in erros[:5]:
        print(f"  falha: {e}")
    if not terminou:
        raise SystemExit(f"ERRO: salvamento não terminou em {TEMPO_MAX_FECHAR_S:g} s")


if __name__ == "__main__":
    main()
