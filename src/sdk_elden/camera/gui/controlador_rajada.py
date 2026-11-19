"""Controlador do modo rajada na GUI: agenda (camera/rajada.py) + salvamento numa FilaTrabalho.

A janela chama `ao_frame(frame, instante)` para cada frame do stream; o controlador decide se
vira foto e manda salvar fora da thread da GUI. Os resultados voltam por sinais Qt (a FilaTrabalho
chama os callbacks na thread dela; emitir sinal entrega na thread da GUI).

Fim da rajada (quantidade atingida ou `parar()`): a fila termina o que já recebeu numa thread
própria e só então `terminou` é emitido com o resumo. `fechar(timeout)` espera isso (closeEvent).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal

from sdk_elden.camera.armazenamento import ConfigArmazenamento, MetadadosCaptura, salvar_captura
from sdk_elden.camera.rajada import (
    FILA_FOTOS,
    AgendaRajada,
    ConfigRajada,
    bloco_sidecar,
    id_rajada,
)
from sdk_elden.utils.fila_trabalho import FilaTrabalho


@dataclass(frozen=True)
class ResumoRajada:
    id: str
    feitas: int          # fotos decididas pela agenda
    salvas: int
    descartadas: int     # fila cheia (salvamento não acompanhou)
    falhas: int
    perdidas: int        # horários sem frame novo
    primeira_falha: str | None


class ControladorRajada(QObject):
    foto_salva = Signal(object)    # Path
    falhou = Signal(str)           # erro de uma foto (a rajada continua)
    parou = Signal()               # rajada encerrada agora (quantidade atingida ou parar()); ainda salvando
    terminou = Signal(object)      # ResumoRajada, depois que tudo foi salvo

    def __init__(self, parent=None, tamanho_fila: int = FILA_FOTOS):
        super().__init__(parent)
        self._tamanho_fila = tamanho_fila
        self._agenda: AgendaRajada | None = None
        self._fila: FilaTrabalho | None = None
        self._id = ""
        self._cfg_arm: ConfigArmazenamento | None = None
        self._meta: Callable[[], MetadadosCaptura] | None = None
        self._primeira_falha: str | None = None
        self._origem: tuple[datetime, float] | None = None  # (relógio de parede, instante) do 1º frame
        self._fechamentos: list[threading.Thread] = []

    @property
    def ativo(self) -> bool:
        return self._agenda is not None

    def iniciar(self, cfg_arm: ConfigArmazenamento, cfg: ConfigRajada, camera_nome: str,
                meta: Callable[[], MetadadosCaptura]) -> None:
        """`meta` é chamada a cada foto: os controles no sidecar são os do instante da foto."""
        if self.ativo:
            return
        self._agenda = AgendaRajada(cfg)  # valida a config (ErroRajada)
        self._cfg_arm, self._meta = cfg_arm, meta
        self._id = id_rajada(datetime.now().astimezone(), camera_nome)
        self._primeira_falha = None
        self._origem = None
        self._fila = FilaTrabalho(salvar_captura, self._tamanho_fila,
                                  ao_concluir=self.foto_salva.emit, ao_falhar=self._ao_falhar,
                                  nome="rajada-salvar")

    def _ao_falhar(self, erro: BaseException) -> None:  # thread da fila
        if self._primeira_falha is None:
            self._primeira_falha = str(erro)
        self.falhou.emit(str(erro))

    def ao_frame(self, frame: np.ndarray, instante: float) -> None:
        agenda, fila = self._agenda, self._fila
        if agenda is None or not agenda.deve_capturar(instante):
            return
        # horário da foto = o da CHEGADA do frame (não o do enfileiramento): fiel ao frame no nome e
        # no sidecar, e frames distintos nunca colidem no mesmo milissegundo do nome do arquivo
        if self._origem is None:
            self._origem = (datetime.now().astimezone(), instante)
        parede0, inst0 = self._origem
        fila.enviar(frame, self._meta(), self._cfg_arm, parede0 + timedelta(seconds=instante - inst0),
                    bloco_sidecar(self._id, agenda.feitas, agenda.cfg))
        if agenda.terminou:
            self.parar()

    def parar(self) -> None:
        """Encerra a rajada; o que já está na fila continua sendo salvo (numa thread)."""
        agenda, fila = self._agenda, self._fila
        if agenda is None:
            return
        self._agenda = self._fila = None
        self.parou.emit()
        ident, primeira = self._id, lambda: self._primeira_falha

        def concluir() -> None:
            fila.fechar(timeout=None)  # espera sem limite AQUI; o limite fica em fechar() abaixo
            self.terminou.emit(ResumoRajada(ident, agenda.feitas, fila.concluidas, fila.descartadas,
                                            fila.falhas, agenda.perdidas, primeira()))

        t = threading.Thread(target=concluir, name="rajada-fim")
        self._fechamentos.append(t)
        t.start()

    def texto_status(self) -> str:
        """'◉ RAJADA 7/20 · próxima 0,4 s · 2 descartadas' (vazio se inativa)."""
        agenda, fila = self._agenda, self._fila
        if agenda is None:
            return ""
        total = agenda.cfg.quantidade or "∞"
        texto = f"◉ RAJADA {agenda.feitas}/{total}"
        proxima = agenda.proximo_em(time.monotonic())
        if proxima is not None and agenda.cfg.intervalo_s >= 1:
            texto += f" · próxima {proxima:.1f} s".replace(".", ",")
        if fila.descartadas:
            texto += f" · {fila.descartadas} descartadas"
        return texto

    def fechar(self, timeout: float) -> bool:
        """Para e espera os salvamentos pendentes. True = tudo salvo dentro do `timeout`."""
        self.parar()
        limite = time.monotonic() + timeout
        for t in self._fechamentos:
            t.join(max(limite - time.monotonic(), 0))
        self._fechamentos = [t for t in self._fechamentos if t.is_alive()]
        return not self._fechamentos
