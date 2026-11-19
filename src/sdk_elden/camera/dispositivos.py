"""Enumeração de câmeras V4L2 via linuxpy (ioctls diretos, sem parsing de texto).

Tudo aqui é consultado no próprio dispositivo (QUERYCAP, ENUM_FMT, ENUM_FRAMESIZES,
ENUM_FRAMEINTERVALS, QUERY_EXT_CTRL); nada é presumido.

Limitações conhecidas do linuxpy 0.25.0 (verificadas em 2026-11-19):
- Formatos de pixel que ele não conhece são descartados com log.warning. Por isso
  o CLI exibe os warnings, para isso não passar batido.
- A API de alto nível de controles (`Device.controls`) quebra inteira se algum
  controle tiver um tipo fora do enum dele (ex.: V4L2_CTRL_TYPE_RECT = 0x107, que a
  webcam ACER expõe via uvcvideo). Por isso usamos a camada de baixo nível
  (iter_read_controls / get_controls_values) com uma lista EXPLÍCITA de tipos
  suportados. Os outros tipos aparecem como `suportado=False`, sem sumir e sem derrubar o resto.
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from linuxpy.video import raw
from linuxpy.video.device import (
    IOC,
    Capability,
    ControlFlag,
    Device,
    FrameIntervalType,
    get_controls_values,
    iter_read,
    iter_read_controls,
    iter_video_capture_files,
)

DIR_BY_ID = Path("/dev/v4l/by-id")

# Valores de V4L2_CTRL_TYPE_* (linux/videodev2.h). Lista explícita do que sabemos
# ler/escrever como escalar; mantida aqui (e não no enum do linuxpy) de propósito.
TIPOS_SUPORTADOS = {
    0x1: "int",
    0x2: "bool",
    0x3: "menu",
    0x5: "int64",
    0x8: "bitmask",
    0x9: "intmenu",
}
TIPO_CTRL_CLASS = 0x6  # cabeçalho de classe ("User Controls"), não é controle
TIPOS_MENU = {0x3, 0x9}


@dataclass(frozen=True)
class ModoFrame:
    """Uma combinação formato + resolução + FPS que o driver anuncia."""

    fourcc: str
    largura: int
    altura: int
    fps: tuple[Fraction, ...]  # taxas discretas; vazio se o driver não informou


@dataclass(frozen=True)
class InfoControle:
    """Metadados de um controle V4L2 (somente leitura; escrita fica em controles.py)."""

    id: int
    nome: str                # mesmo padrão de nome do v4l2-ctl (ex.: exposure_time_absolute)
    tipo: str                # "int", "bool", "menu"... ou "0x107" se não suportado
    suportado: bool
    minimo: int
    maximo: int
    passo: int
    padrao: object
    valor: object
    inativo: bool
    somente_leitura: bool
    menu: dict[int, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Camera:
    caminho: Path            # /dev/videoN
    caminho_estavel: Path | None  # /dev/v4l/by-id/... (sobrevive a replug/reboot)
    nome: str                # card reportado pelo driver
    driver: str
    barramento: str
    modos: tuple[ModoFrame, ...]
    controles: tuple[InfoControle, ...]


def mapa_by_id(dir_by_id: Path = DIR_BY_ID) -> dict[Path, Path]:
    """Mapeia /dev/videoN -> link estável em /dev/v4l/by-id."""
    if not dir_by_id.is_dir():
        return {}
    mapa = {}
    for link in sorted(dir_by_id.iterdir()):
        alvo = Path(os.path.realpath(link))
        mapa.setdefault(alvo, link)
    return mapa


def _fourcc(pixel_format) -> str:
    v = int(pixel_format)
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))


def _ler_modos(dev: Device) -> tuple[ModoFrame, ...]:
    agrupado: dict[tuple[str, int, int], list[Fraction]] = {}
    for ft in dev.info.frame_types:
        chave = (_fourcc(ft.pixel_format), ft.width, ft.height)
        lista = agrupado.setdefault(chave, [])
        if ft.type == FrameIntervalType.DISCRETE and ft.max_fps:
            lista.append(Fraction(ft.max_fps))
    return tuple(
        ModoFrame(f, w, h, tuple(sorted(set(fps), reverse=True)))
        for (f, w, h), fps in sorted(agrupado.items(), key=lambda kv: (kv[0][0], -kv[0][1] * kv[0][2]))
    )


def nome_config(nome_driver: str) -> str:
    """'Exposure Time, Absolute' -> 'exposure_time_absolute' (mesma regra do v4l2-ctl/linuxpy)."""
    res = nome_driver.lower().replace("(", "").replace(")", "")
    return res.replace(", ", "_").replace(" ", "_")


def _ler_menu(dev: Device, ctrl) -> dict[int, object]:
    qmenu = raw.v4l2_querymenu()
    qmenu.id = ctrl.id
    itens = {}
    # ignore_einval: o driver pode pular índices no meio do intervalo
    for item in iter_read(dev, IOC.QUERYMENU, qmenu, start=ctrl.minimum, stop=ctrl.maximum + 1, ignore_einval=True):
        itens[item.index] = item.name.decode() if ctrl.type == 0x3 else item.value
    return itens


def iter_controles_brutos(dev: Device):
    """Structs v4l2_query_ext_ctrl dos controles reais (sem cabeçalhos de classe nem desabilitados)."""
    for ctrl in iter_read_controls(dev):
        if ctrl.type == TIPO_CTRL_CLASS or ControlFlag.DISABLED in ControlFlag(ctrl.flags):
            continue
        yield ctrl


def info_controle(dev: Device, ctrl) -> InfoControle:
    """Monta InfoControle a partir da struct bruta, lendo valor/padrão atuais no driver."""
    flags = ControlFlag(ctrl.flags)
    suportado = ctrl.type in TIPOS_SUPORTADOS
    legivel = suportado and ControlFlag.WRITE_ONLY not in flags
    return InfoControle(
        id=ctrl.id,
        nome=nome_config(ctrl.name.decode()),
        tipo=TIPOS_SUPORTADOS.get(ctrl.type, hex(ctrl.type)),
        suportado=suportado,
        minimo=ctrl.minimum,
        maximo=ctrl.maximum,
        passo=ctrl.step,
        padrao=get_controls_values(dev, (ctrl,), raw.ControlWhichValue.DEF_VAL)[0] if legivel else None,
        valor=get_controls_values(dev, (ctrl,))[0] if legivel else None,
        inativo=ControlFlag.INACTIVE in flags,
        somente_leitura=ControlFlag.READ_ONLY in flags,
        menu=_ler_menu(dev, ctrl) if ctrl.type in TIPOS_MENU else {},
    )


def _ler_controles(dev: Device) -> tuple[InfoControle, ...]:
    return tuple(info_controle(dev, c) for c in iter_controles_brutos(dev))


def ler_camera(caminho: Path, by_id: dict[Path, Path] | None = None) -> Camera:
    """Abre o nó só para leitura de metadados (não inicia stream)."""
    by_id = mapa_by_id() if by_id is None else by_id
    with Device(str(caminho), read_write=False) as dev:
        info = dev.info
        if Capability.VIDEO_CAPTURE not in info.device_capabilities:
            raise ValueError(f"{caminho} não é um nó de captura de vídeo")
        return Camera(
            caminho=Path(caminho),
            caminho_estavel=by_id.get(Path(os.path.realpath(caminho))),
            nome=info.card,
            driver=info.driver,
            barramento=info.bus_info,
            modos=_ler_modos(dev),
            controles=_ler_controles(dev),
        )


def modos_anunciados(caminho: str | Path) -> tuple[ModoFrame, ...]:
    """Só os modos (formato/res/FPS) de um nó, sem ler controles. Não inicia stream."""
    with Device(str(caminho), read_write=False) as dev:
        return _ler_modos(dev)


def listar_cameras() -> list[Camera]:
    """Retorna só os nós com capability VIDEO_CAPTURE (descarta nós de metadados)."""
    by_id = mapa_by_id()
    caminhos = sorted(iter_video_capture_files(), key=lambda p: int(str(p).removeprefix("/dev/video")))
    return [ler_camera(c, by_id) for c in caminhos]


def _fmt_fps(fps: tuple[Fraction, ...]) -> str:
    if not fps:
        return "fps não informado"
    return ", ".join(f"{float(f):g}" for f in fps) + " fps"


def formatar(cam: Camera) -> str:
    linhas = [
        f"{cam.caminho}  —  {cam.nome}",
        f"  estável : {cam.caminho_estavel or '(sem link em /dev/v4l/by-id)'}",
        f"  driver  : {cam.driver}   barramento: {cam.barramento}",
        "  modos:",
    ]
    linhas += [f"    {m.fourcc} {m.largura}x{m.altura}  [{_fmt_fps(m.fps)}]" for m in cam.modos]
    linhas.append("  controles:")
    for c in cam.controles:
        if not c.suportado:
            linhas.append(f"    {c.nome:<28} {c.tipo:<8} (tipo não suportado — ignorado)")
            continue
        extra = f" menu={c.menu}" if c.menu else f" min={c.minimo} max={c.maximo} step={c.passo}"
        flag = "".join(f for f, on in ((" (inativo)", c.inativo), (" (somente leitura)", c.somente_leitura)) if on)
        linhas.append(f"    {c.nome:<28} {c.tipo:<8} valor={c.valor} padrão={c.padrao}{extra}{flag}")
    return "\n".join(linhas)


def main() -> None:
    argparse.ArgumentParser(description="Lista câmeras V4L2, modos e controles").parse_args()
    logging.basicConfig(level=logging.WARNING, format="AVISO linuxpy: %(message)s")
    cameras = listar_cameras()
    if not cameras:
        print("Nenhum nó V4L2 de captura encontrado.")
        return
    print("\n\n".join(formatar(c) for c in cameras))


if __name__ == "__main__":
    main()
