"""Diálogo de configuração de armazenamento (raiz, repo, subrepo, formato)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
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


class JanelaConfig(QDialog):
    def __init__(self, cfg: ConfigArmazenamento, caminho_arquivo: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações de armazenamento")
        self.setMinimumWidth(560)
        self._cfg = cfg

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
        self.lbl_erro.setStyleSheet("color: #c0392b;")
        self.lbl_erro.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Raiz", linha_raiz)
        form.addRow("Repo", self.cb_repo)
        form.addRow("Subrepo", self.cb_subrepo)
        form.addRow("Formato", self.cb_formato)
        form.addRow("Qualidade JPG", self.sp_qualidade)

        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)

        # rótulos com quebra de linha ficam FORA do QFormLayout: dentro dele a altura
        # não é recalculada quando o texto muda e caminhos longos ficavam cortados
        lbl_arquivo = QLabel(f"<small>Arquivo de config: {caminho_arquivo}</small>")
        lbl_arquivo.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
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

        self.ed_raiz.textChanged.connect(self._preencher_repos)
        self.cb_repo.currentTextChanged.connect(self._preencher_subrepos)
        for sinal in (self.ed_raiz.textChanged, self.cb_repo.currentTextChanged,
                      self.cb_subrepo.currentTextChanged, self.cb_formato.currentTextChanged,
                      self.sp_qualidade.valueChanged):
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

    def _validar(self) -> None:
        self.sp_qualidade.setEnabled(self.cb_formato.currentText() == "jpg")
        cfg = self.config()
        try:
            validar_config(cfg)
        except ErroArmazenamento as e:
            self.lbl_erro.setText(str(e))
            self.lbl_destino.setText("—")
            self.botoes.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            return
        self.lbl_erro.clear()
        destino = diretorio_destino(cfg)
        self.lbl_destino.setText(f"{destino}{'' if destino.exists() else '  (será criada)'}")
        self.botoes.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
