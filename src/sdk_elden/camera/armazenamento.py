"""Salvamento de capturas em raiz/<repo>/<subrepo>/ com sidecar JSON.

Cada captura gera dois arquivos com o mesmo nome-base:
    20261119_143012_123_2k_usb_Camera_Redeagle_2560x1440.png
    20261119_143012_123_2k_usb_Camera_Redeagle_2560x1440.json  <- câmera, modo, controles

Regras:
- Nunca sobrescreve: se o nome já existir, ErroArmazenamento.
- Escrita atômica (arquivo temporário + os.replace): sem PNG pela metade se o processo cair.
- cv2.imwrite NÃO lança exceção quando falha (só retorna False, verificado); checamos o retorno.
- PNG 2560x1440 leva ~65 ms (JPG 95 ~8 ms, medido em 2026-11-19); o salvamento é síncrono.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.dispositivos import InfoControle
from sdk_elden.utils.config import DIR_CONFIG

ARQUIVO_CONFIG = DIR_CONFIG / "camera.toml"
SECAO_CONFIG = "armazenamento"
NOME_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FORMATOS = ("png", "jpg")


class ErroArmazenamento(Exception):
    pass


@dataclass
class ConfigArmazenamento:
    raiz: str = str(Path.home() / "capturas")
    repo: str = "geral"
    subrepo: str = "sessao"
    formato: str = "png"
    qualidade_jpg: int = 95


def validar_config(cfg: ConfigArmazenamento) -> None:
    if not Path(cfg.raiz).is_absolute():
        raise ErroArmazenamento(f"raiz deve ser caminho absoluto: {cfg.raiz!r}")
    for campo in ("repo", "subrepo"):
        valor = getattr(cfg, campo)
        if not NOME_VALIDO.match(valor):
            raise ErroArmazenamento(
                f"{campo} {valor!r} inválido: use letras, números, '.', '_' ou '-' (sem '/', sem começar com '.')"
            )
    if cfg.formato not in FORMATOS:
        raise ErroArmazenamento(f"formato {cfg.formato!r} inválido; opções: {FORMATOS}")
    if not 1 <= cfg.qualidade_jpg <= 100:
        raise ErroArmazenamento(f"qualidade_jpg deve estar em [1, 100], veio {cfg.qualidade_jpg}")


def diretorio_destino(cfg: ConfigArmazenamento) -> Path:
    return Path(cfg.raiz) / cfg.repo / cfg.subrepo


def slug(texto: str) -> str:
    """'2k usb Camera Redeagle: 2k usb ' -> '2k_usb_Camera_Redeagle' (só a parte antes do ':')."""
    base = texto.split(":")[0].strip()
    return re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_") or "camera"


@dataclass(frozen=True)
class MetadadosCaptura:
    camera_nome: str
    camera_caminho: str
    camera_caminho_estavel: str | None
    camera_driver: str
    camera_barramento: str
    modo_pedido: ModoCaptura
    modo_negociado: ModoCaptura
    controles: tuple[InfoControle, ...]


def _escrever_atomico_imagem(destino: Path, frame: np.ndarray, params: list[int]) -> None:
    tmp = destino.with_name(f".{destino.stem}.tmp{destino.suffix}")  # extensão define o codec no imwrite
    # imwrite tem DOIS modos de falha (verificados): retorna False (ex.: diretório
    # inexistente) ou lança cv2.error (ex.: imagem vazia). Os dois viram ErroArmazenamento.
    try:
        ok = cv2.imwrite(str(tmp), frame, params)
    except cv2.error as e:
        tmp.unlink(missing_ok=True)
        raise ErroArmazenamento(f"cv2.imwrite rejeitou a imagem para {destino.name}: {str(e).strip().splitlines()[-1]}") from e
    if not ok:
        tmp.unlink(missing_ok=True)
        raise ErroArmazenamento(f"cv2.imwrite falhou ao gravar {destino} (retornou False)")
    os.replace(tmp, destino)


def _escrever_atomico_texto(destino: Path, texto: str) -> None:
    tmp = destino.with_name(f".{destino.name}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, destino)


def salvar_captura(
    frame: np.ndarray, meta: MetadadosCaptura, cfg: ConfigArmazenamento, agora: datetime | None = None
) -> Path:
    """Grava imagem + sidecar JSON. Retorna o caminho da imagem."""
    validar_config(cfg)
    agora = agora or datetime.now().astimezone()
    pasta = diretorio_destino(cfg)
    pasta.mkdir(parents=True, exist_ok=True)

    altura, largura = frame.shape[:2]
    base = f"{agora:%Y%m%d_%H%M%S}_{agora.microsecond // 1000:03d}_{slug(meta.camera_nome)}_{largura}x{altura}"
    imagem = pasta / f"{base}.{cfg.formato}"
    sidecar = pasta / f"{base}.json"
    if imagem.exists() or sidecar.exists():
        raise ErroArmazenamento(f"já existe {imagem.name} (duas capturas no mesmo milissegundo?)")

    params = [cv2.IMWRITE_JPEG_QUALITY, cfg.qualidade_jpg] if cfg.formato == "jpg" else []
    dados = {
        "arquivo": imagem.name,
        "capturado_em": agora.isoformat(timespec="milliseconds"),
        "repo": cfg.repo,
        "subrepo": cfg.subrepo,
        "formato": cfg.formato,
        "qualidade_jpg": cfg.qualidade_jpg if cfg.formato == "jpg" else None,
        "camera": {
            "nome": meta.camera_nome.strip(),
            "caminho": meta.camera_caminho,
            "caminho_estavel": meta.camera_caminho_estavel,
            "driver": meta.camera_driver,
            "barramento": meta.camera_barramento,
        },
        "modo_pedido": asdict(meta.modo_pedido),
        "modo_negociado": asdict(meta.modo_negociado),
        "resolucao_frame": [largura, altura],
        # controles lidos no driver no momento do salvamento (podem diferir em ~1 frame do instante da imagem)
        "controles": {
            c.nome: {"valor": c.valor, "inativo": c.inativo, **({"menu": c.menu.get(c.valor)} if c.menu else {})}
            for c in meta.controles if c.suportado
        },
    }
    _escrever_atomico_imagem(imagem, frame, params)
    _escrever_atomico_texto(sidecar, json.dumps(dados, ensure_ascii=False, indent=2))
    return imagem
