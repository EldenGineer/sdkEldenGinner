"""Janela principal: lista de câmeras, escolha de modo e preview ao vivo.

As opções dos combos vêm dos modos que o driver anuncia (dispositivos.listar_cameras),
em cascata formato -> resolução -> FPS, a mesma ordem da negociação.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sdk_elden.camera.armazenamento import (
    ARQUIVO_CONFIG,
    SECAO_CONFIG,
    ConfigArmazenamento,
    ErroArmazenamento,
    MetadadosCaptura,
    diretorio_destino,
    salvar_captura,
)
from sdk_elden.camera.captura import ModoCaptura
from sdk_elden.camera.dispositivos import Camera, listar_cameras
from sdk_elden.camera.gui.janela_config import JanelaConfig
from sdk_elden.camera.gui.painel_controles import PainelControles
from sdk_elden.camera.gui.preview import WidgetPreview
from sdk_elden.camera.gui.thread_captura import ThreadCaptura
from sdk_elden.utils.config import ErroConfig, carregar_secao, salvar_secao

TEMPO_MAX_PARADA_MS = 3000  # espera explícita pelo fim da thread ao parar/trocar


class JanelaPrincipal(QMainWindow):
    def __init__(self, caminho_config: Path = ARQUIVO_CONFIG):
        super().__init__()
        self.setWindowTitle("sdkEldenGinner — Câmeras")
        self._cameras: list[Camera] = []
        self._thread: ThreadCaptura | None = None
        self._negociado: ModoCaptura | None = None
        self.ultimo_frame = None  # BGR do último frame recebido
        self.caminho_config = caminho_config
        self.cfg, erro_cfg = self._carregar_config()

        # --- painel esquerdo ---------------------------------------------
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._camera_selecionada)
        btn_atualizar = QPushButton("Atualizar lista")
        btn_atualizar.clicked.connect(self.atualizar_cameras)

        self.cb_formato, self.cb_resolucao, self.cb_fps = QComboBox(), QComboBox(), QComboBox()
        self.cb_formato.currentIndexChanged.connect(self._preencher_resolucoes)
        self.cb_resolucao.currentIndexChanged.connect(self._preencher_fps)
        form = QFormLayout()
        form.addRow("Formato", self.cb_formato)
        form.addRow("Resolução", self.cb_resolucao)
        form.addRow("FPS", self.cb_fps)
        grupo_modo = QGroupBox("Modo")
        grupo_modo.setLayout(form)

        self.btn_abrir = QPushButton("Abrir")
        self.btn_abrir.clicked.connect(self.abrir)
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.clicked.connect(self.parar)
        self.btn_parar.setEnabled(False)
        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_abrir)
        botoes.addWidget(self.btn_parar)

        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # --- captura -----------------------------------------------------------
        self.btn_capturar = QPushButton("Capturar  [Espaço]")
        self.btn_capturar.clicked.connect(self.capturar)
        self.btn_capturar.setEnabled(False)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.capturar)
        btn_config = QPushButton("Configurações…")
        btn_config.clicked.connect(self.abrir_config)
        self.lbl_destino = QLabel()
        self.lbl_destino.setWordWrap(True)
        self.lbl_destino.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grupo_captura = QGroupBox("Captura")
        caixa = QVBoxLayout(grupo_captura)
        caixa.addWidget(self.btn_capturar)
        caixa.addWidget(btn_config)
        caixa.addWidget(self.lbl_destino)
        self._atualizar_destino()

        esquerda = QVBoxLayout()
        esquerda.addWidget(QLabel("Câmeras"))
        esquerda.addWidget(self.lista, 1)
        esquerda.addWidget(btn_atualizar)
        esquerda.addWidget(grupo_modo)
        esquerda.addLayout(botoes)
        esquerda.addWidget(grupo_captura)
        esquerda.addWidget(self.lbl_info)
        painel = QWidget()
        painel.setLayout(esquerda)

        # --- preview -------------------------------------------------------
        self.preview = WidgetPreview()
        self.painel_controles = PainelControles()

        divisor = QSplitter()
        divisor.addWidget(painel)
        divisor.addWidget(self.preview)
        divisor.addWidget(self.painel_controles)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([280, 900, 420])
        self.setCentralWidget(divisor)
        self.resize(1600, 820)

        self.lbl_status_modo = QLabel("parado")
        self.lbl_status_fps = QLabel()
        self.statusBar().addWidget(self.lbl_status_modo, 1)
        self.statusBar().addPermanentWidget(self.lbl_status_fps)

        self.atualizar_cameras()
        if erro_cfg:
            QMessageBox.warning(
                self, "Configuração inválida",
                f"{erro_cfg}\n\nUsando os padrões nesta sessão. O arquivo NÃO será alterado até você salvar em Configurações.",
            )

    # --- configuração e captura ----------------------------------------------
    def _carregar_config(self) -> tuple[ConfigArmazenamento, str | None]:
        try:
            return carregar_secao(self.caminho_config, SECAO_CONFIG, ConfigArmazenamento), None
        except ErroConfig as e:
            return ConfigArmazenamento(), str(e)

    def _atualizar_destino(self) -> None:
        fmt = self.cfg.formato + (f" q{self.cfg.qualidade_jpg}" if self.cfg.formato == "jpg" else "")
        self.lbl_destino.setText(f"→ {diretorio_destino(self.cfg)}  ({fmt})")

    def abrir_config(self) -> None:
        dialogo = JanelaConfig(self.cfg, self.caminho_config, self)
        if dialogo.exec() == JanelaConfig.DialogCode.Accepted:
            self.cfg = dialogo.config()
            salvar_secao(self.caminho_config, SECAO_CONFIG, self.cfg)
            self._atualizar_destino()

    def capturar(self) -> Path | None:
        cam, frame = self.camera_atual(), self.ultimo_frame
        if not self.btn_capturar.isEnabled() or cam is None or frame is None or self._thread is None:
            return None
        meta = MetadadosCaptura(
            camera_nome=cam.nome,
            camera_caminho=str(cam.caminho),
            camera_caminho_estavel=str(cam.caminho_estavel) if cam.caminho_estavel else None,
            camera_driver=cam.driver,
            camera_barramento=cam.barramento,
            modo_pedido=self._thread.modo,
            modo_negociado=self._negociado,
            controles=tuple(self.painel_controles.estado_atual()),
        )
        try:
            caminho = salvar_captura(frame, meta, self.cfg)
        except (ErroArmazenamento, OSError) as e:
            QMessageBox.critical(self, "Falha ao salvar", str(e))
            return None
        self.statusBar().showMessage(f"salvo: {caminho}", 5000)
        return caminho

    # --- câmeras e modos ------------------------------------------------------
    def camera_atual(self) -> Camera | None:
        linha = self.lista.currentRow()
        return self._cameras[linha] if 0 <= linha < len(self._cameras) else None

    def atualizar_cameras(self) -> None:
        self.parar()
        self._cameras = listar_cameras()
        self.lista.clear()
        for cam in self._cameras:
            item = QListWidgetItem(f"{cam.nome}\n{cam.caminho}")
            item.setToolTip(str(cam.caminho_estavel or cam.caminho))
            self.lista.addItem(item)
        if self._cameras:
            self.lista.setCurrentRow(0)
        else:
            self._camera_selecionada(-1)

    def _camera_selecionada(self, _linha: int) -> None:
        self.parar()
        cam = self.camera_atual()
        self.cb_formato.blockSignals(True)
        self.cb_formato.clear()
        if cam:
            for fourcc in dict.fromkeys(m.fourcc for m in cam.modos):  # mantém a ordem do driver
                self.cb_formato.addItem(fourcc)
            self.lbl_info.setText(
                f"<b>{cam.nome}</b><br>driver: {cam.driver}<br>barramento: {cam.barramento}<br>"
                f"estável: {cam.caminho_estavel or '(sem by-id)'}"
            )
        else:
            self.lbl_info.setText("Nenhuma câmera V4L2 de captura encontrada.")
        self.cb_formato.blockSignals(False)
        self._preencher_resolucoes()
        self.btn_abrir.setEnabled(cam is not None)
        # controles ficam disponíveis com ou sem stream (o V4L2 permite os dois; verificado)
        self.painel_controles.definir_camera((cam.caminho_estavel or cam.caminho) if cam else None)

    def _preencher_resolucoes(self) -> None:
        cam, fourcc = self.camera_atual(), self.cb_formato.currentText()
        self.cb_resolucao.blockSignals(True)
        self.cb_resolucao.clear()
        if cam:
            for m in cam.modos:
                if m.fourcc == fourcc:
                    self.cb_resolucao.addItem(f"{m.largura}x{m.altura}", (m.largura, m.altura))
        self.cb_resolucao.blockSignals(False)
        self._preencher_fps()

    def _preencher_fps(self) -> None:
        cam, fourcc, res = self.camera_atual(), self.cb_formato.currentText(), self.cb_resolucao.currentData()
        self.cb_fps.clear()
        if not (cam and res):
            return
        modo = next(m for m in cam.modos if (m.fourcc, m.largura, m.altura) == (fourcc, *res))
        for f in modo.fps:
            self.cb_fps.addItem(f"{float(f):g}", float(f))
        if not modo.fps:  # driver não anunciou intervalos: deixar explícito, não inventar valor
            self.cb_fps.addItem("(não anunciado) 30", 30.0)

    def modo_selecionado(self) -> ModoCaptura | None:
        res, fps = self.cb_resolucao.currentData(), self.cb_fps.currentData()
        if not (res and fps):
            return None
        return ModoCaptura(self.cb_formato.currentText(), res[0], res[1], fps)

    # --- stream ---------------------------------------------------------------
    def abrir(self) -> None:
        cam, modo = self.camera_atual(), self.modo_selecionado()
        if not (cam and modo):
            return
        self.parar()
        self._thread = ThreadCaptura(cam.caminho_estavel or cam.caminho, modo, self)
        self._thread.aberta.connect(self._ao_abrir)
        self._thread.novo_frame.connect(self._ao_frame)
        self._thread.fps_medido.connect(lambda f: self.lbl_status_fps.setText(f"{f:.1f} fps medidos"))
        self._thread.erro.connect(self._ao_erro)
        self._thread.finished.connect(self._ao_terminar)
        self.lbl_status_modo.setText(f"abrindo {modo}…")
        self._habilitar_edicao(False)
        self._thread.start()

    def parar(self) -> None:
        if self._thread is None:
            return
        self._thread.parar()
        if not self._thread.wait(TEMPO_MAX_PARADA_MS):
            # read() bloqueado (câmera travada/desconectada): não matamos a thread à força
            # (terminate() pode corromper o estado do driver/OpenCV); só avisamos.
            QMessageBox.warning(self, "Câmera", "A thread de captura não respondeu em 3 s.")
        self._thread = None
        self._ao_terminar()

    def _habilitar_edicao(self, sim: bool) -> None:
        for w in (self.lista, self.cb_formato, self.cb_resolucao, self.cb_fps, self.btn_abrir):
            w.setEnabled(sim)
        self.btn_parar.setEnabled(not sim)

    def _ao_abrir(self, negociado: ModoCaptura) -> None:
        self._negociado = negociado
        self.lbl_status_modo.setText(f"ao vivo: {negociado}")

    def _ao_frame(self, imagem, frame) -> None:
        self.ultimo_frame = frame
        self.preview.mostrar(imagem)
        if not self.btn_capturar.isEnabled():
            self.btn_capturar.setEnabled(True)  # só com frame do stream ATUAL

    def _ao_erro(self, mensagem: str) -> None:
        QMessageBox.critical(self, "Erro de captura", mensagem)

    def _ao_terminar(self) -> None:
        # descarta o frame antigo: não pode ser salvo depois com metadados de outra câmera/modo
        self.ultimo_frame = None
        self._negociado = None
        self.btn_capturar.setEnabled(False)
        self._habilitar_edicao(True)
        self.btn_abrir.setEnabled(self.camera_atual() is not None)
        self.lbl_status_modo.setText("parado")
        self.lbl_status_fps.clear()

    def closeEvent(self, evento) -> None:
        self.parar()
        self.painel_controles.fechar()
        super().closeEvent(evento)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gerenciador de câmeras V4L2")
    ap.add_argument("--config", type=Path, default=ARQUIVO_CONFIG, help=f"arquivo TOML (padrão: {ARQUIVO_CONFIG})")
    args, resto_qt = ap.parse_known_args()
    app = QApplication([sys.argv[0], *resto_qt])
    janela = JanelaPrincipal(args.config.expanduser().resolve())
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
