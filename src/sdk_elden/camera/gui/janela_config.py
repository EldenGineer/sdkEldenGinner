"""Diálogo de configuração: armazenamento (raiz, repo, subrepo, formato da foto) e gravação de vídeo."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from sdk_elden.camera.gravacao import (
    CODIFICADORES_H264,
    FORMATOS_VIDEO,
    ConfigGravacao,
    ErroGravacao,
    validar_config_gravacao,
)
from sdk_elden.camera.rajada import INTERVALO_MIN_S, ConfigRajada, ErroRajada, validar_config_rajada
from sdk_elden.camera.armazenamento import (
    FORMATOS,
    ConfigArmazenamento,
    ErroArmazenamento,
    diretorio_destino,
    validar_config,
)


def subpastas(pasta: Path) -> list[str]:
    """Nomes das subpastas existentes (para sugerir repos/subrepos já usados)."""
    if not pasta.is_dir():
        return []
    return sorted(p.name for p in pasta.iterdir() if p.is_dir() and not p.name.startswith("."))


def campos_rajada() -> tuple[QDoubleSpinBox, QSpinBox]:
    """Intervalo (s) e quantidade (0 = sem limite), com os limites de camera/rajada.py.
    Usados na janela de configuração e na barra de captura (mesmos limites nos dois)."""
    intervalo = QDoubleSpinBox()
    intervalo.setDecimals(2)
    intervalo.setRange(INTERVALO_MIN_S, 86400)
    intervalo.setSingleStep(0.1)
    intervalo.setSuffix(" s")
    intervalo.setToolTip(f"Tempo entre fotos da rajada (mínimo {INTERVALO_MIN_S:g} s). "
                         "PNG 2560x1440 aguenta ~15 fotos/s; mais rápido que isso, use JPG.")
    quantidade = QSpinBox()
    quantidade.setRange(0, 1_000_000)
    quantidade.setSpecialValueText("∞")  # 0 = até parar
    quantidade.setSuffix(" fotos")
    quantidade.setToolTip("Fotos da rajada; 0 (∞) = até parar")
    return intervalo, quantidade


class JanelaConfig(QDialog):
    def __init__(self, cfg: ConfigArmazenamento, caminho_arquivo: Path, parent=None,
                 cfg_grav: ConfigGravacao | None = None, cfg_rajada: ConfigRajada | None = None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(560)
        self._cfg = cfg
        self._cfg_grav = cfg_grav or ConfigGravacao()
        self._cfg_rajada = cfg_rajada or ConfigRajada()

        self.ed_raiz = QLineEdit(cfg.raiz)
        btn_raiz = QPushButton("…")
        btn_raiz.setFixedWidth(32)
        btn_raiz.clicked.connect(self._escolher_raiz)
        linha_raiz = QHBoxLayout()
        linha_raiz.addWidget(self.ed_raiz, 1)
        linha_raiz.addWidget(btn_raiz)

        # combos editáveis: sugerem pastas existentes, mas aceitam nome novo
        self.cb_repo = QComboBox(editable=True)
        self.cb_subrepo = QComboBox(editable=True)
        self.cb_formato = QComboBox()
        self.cb_formato.addItems(FORMATOS)
        self.sp_qualidade = QSpinBox()
        self.sp_qualidade.setRange(1, 100)

        self.lbl_destino = QLabel()
        self.lbl_destino.setWordWrap(True)
        self.lbl_erro = QLabel()
        self.lbl_erro.setObjectName("lblErro")  # cor do tema (o #c0392b fixo ficava ~3:1 no fundo escuro)
        self.lbl_erro.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Raiz", linha_raiz)
        form.addRow("Repo", self.cb_repo)
        form.addRow("Subrepo", self.cb_subrepo)
        form.addRow("Formato", self.cb_formato)
        form.addRow("Qualidade JPG", self.sp_qualidade)

        # --- vídeo ---------------------------------------------------------------
        g = self._cfg_grav
        self.cb_video_formato = QComboBox()
        self.cb_video_formato.addItem("MP4 (H.264)", "mp4")
        self.cb_video_formato.addItem("MKV (MJPG, cada frame um JPEG)", "mkv")
        self.cb_codificador = QComboBox()
        self.cb_codificador.addItem("libx264 (CPU)", "libx264")
        self.cb_codificador.addItem("h264_nvenc (GPU NVIDIA)", "h264_nvenc")
        assert [self.cb_video_formato.itemData(i) for i in range(2)] == list(FORMATOS_VIDEO)
        assert [self.cb_codificador.itemData(i) for i in range(2)] == list(CODIFICADORES_H264)
        self.sp_qualidade_h264 = QSpinBox()
        self.sp_qualidade_h264.setRange(0, 51)
        self.sp_qualidade_h264.setToolTip("CRF (libx264) / CQ (nvenc): menor = melhor e arquivo maior. 23 é o padrão.")
        self.sp_qualidade_mjpeg = QSpinBox()
        self.sp_qualidade_mjpeg.setRange(2, 31)
        self.sp_qualidade_mjpeg.setToolTip("-q:v do mjpeg: 2 = melhor e arquivo maior, 31 = pior.")
        form_video = QFormLayout()
        form_video.addRow("Formato", self.cb_video_formato)
        form_video.addRow("Codificador", self.cb_codificador)
        form_video.addRow("Qualidade H.264", self.sp_qualidade_h264)
        form_video.addRow("Qualidade MJPG", self.sp_qualidade_mjpeg)

        # --- rajada (valores padrão; a barra de captura ajusta só para a sessão) -----
        self.sp_intervalo, self.sp_quantidade = campos_rajada()
        form_rajada = QFormLayout()
        form_rajada.addRow("Intervalo", self.sp_intervalo)
        form_rajada.addRow("Quantidade", self.sp_quantidade)

        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)

        # rótulos com quebra de linha ficam FORA do QFormLayout: dentro dele a altura
        # não é recalculada quando o texto muda e caminhos longos ficavam cortados
        lbl_arquivo = QLabel(f"<small>Arquivo de config: {caminho_arquivo}</small>")
        lbl_arquivo.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Fotos</b>"))
        layout.addLayout(form)
        layout.addWidget(QLabel("<b>Vídeo</b> (ffmpeg do sistema; mesma pasta das fotos)"))
        layout.addLayout(form_video)
        layout.addWidget(QLabel("<b>Rajada</b> (padrões; a barra de captura ajusta só para a sessão)"))
        layout.addLayout(form_rajada)
        layout.addWidget(QLabel("<b>Destino das capturas</b>"))
        layout.addWidget(self.lbl_destino)
        layout.addWidget(lbl_arquivo)
        layout.addWidget(self.lbl_erro)
        layout.addWidget(self.botoes)

        self._preencher_repos()
        self.cb_repo.setCurrentText(cfg.repo)
        self._preencher_subrepos()
        self.cb_subrepo.setCurrentText(cfg.subrepo)
        self.cb_formato.setCurrentText(cfg.formato)
        self.sp_qualidade.setValue(cfg.qualidade_jpg)
        self.cb_video_formato.setCurrentIndex(self.cb_video_formato.findData(g.formato))
        self.cb_codificador.setCurrentIndex(self.cb_codificador.findData(g.codificador))
        self.sp_qualidade_h264.setValue(g.qualidade_h264)
        self.sp_qualidade_mjpeg.setValue(g.qualidade_mjpeg)
        self.sp_intervalo.setValue(self._cfg_rajada.intervalo_s)
        self.sp_quantidade.setValue(self._cfg_rajada.quantidade)

        self.ed_raiz.textChanged.connect(self._preencher_repos)
        self.cb_repo.currentTextChanged.connect(self._preencher_subrepos)
        for sinal in (self.ed_raiz.textChanged, self.cb_repo.currentTextChanged,
                      self.cb_subrepo.currentTextChanged, self.cb_formato.currentTextChanged,
                      self.sp_qualidade.valueChanged, self.cb_video_formato.currentIndexChanged,
                      self.cb_codificador.currentIndexChanged, self.sp_intervalo.valueChanged,
                      self.sp_quantidade.valueChanged):
            sinal.connect(self._validar)
        self._validar()

    def _escolher_raiz(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Raiz das capturas", self.ed_raiz.text())
        if pasta:
            self.ed_raiz.setText(pasta)

    def _preencher_repos(self) -> None:
        atual = self.cb_repo.currentText()
        self.cb_repo.blockSignals(True)
        self.cb_repo.clear()
        self.cb_repo.addItems(subpastas(Path(self.ed_raiz.text())))
        self.cb_repo.setCurrentText(atual)
        self.cb_repo.blockSignals(False)
        self._preencher_subrepos()

    def _preencher_subrepos(self) -> None:
        atual = self.cb_subrepo.currentText()
        self.cb_subrepo.blockSignals(True)
        self.cb_subrepo.clear()
        self.cb_subrepo.addItems(subpastas(Path(self.ed_raiz.text()) / self.cb_repo.currentText()))
        self.cb_subrepo.setCurrentText(atual)
        self.cb_subrepo.blockSignals(False)

    def config(self) -> ConfigArmazenamento:
        return replace(
            self._cfg,
            raiz=self.ed_raiz.text().strip(),
            repo=self.cb_repo.currentText().strip(),
            subrepo=self.cb_subrepo.currentText().strip(),
            formato=self.cb_formato.currentText(),
            qualidade_jpg=self.sp_qualidade.value(),
        )

    def config_gravacao(self) -> ConfigGravacao:
        return replace(
            self._cfg_grav,
            formato=self.cb_video_formato.currentData(),
            codificador=self.cb_codificador.currentData(),
            qualidade_h264=self.sp_qualidade_h264.value(),
            qualidade_mjpeg=self.sp_qualidade_mjpeg.value(),
        )

    def config_rajada(self) -> ConfigRajada:
        return replace(self._cfg_rajada, intervalo_s=self.sp_intervalo.value(), quantidade=self.sp_quantidade.value())

    def _validar(self) -> None:
        self.sp_qualidade.setEnabled(self.cb_formato.currentText() == "jpg")
        mp4 = self.cb_video_formato.currentData() == "mp4"
        for w in (self.cb_codificador, self.sp_qualidade_h264):
            w.setEnabled(mp4)  # MKV é sempre MJPG
        self.sp_qualidade_mjpeg.setEnabled(not mp4)
        cfg = self.config()
        try:
            validar_config(cfg)
            validar_config_gravacao(self.config_gravacao())
            validar_config_rajada(self.config_rajada())
        except (ErroArmazenamento, ErroGravacao, ErroRajada) as e:
            self.lbl_erro.setText(str(e))
            self.lbl_destino.setText("—")
            self.botoes.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            return
        self.lbl_erro.clear()
        destino = diretorio_destino(cfg)
        self.lbl_destino.setText(f"{destino}{'' if destino.exists() else '  (será criada)'}")
        self.botoes.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
