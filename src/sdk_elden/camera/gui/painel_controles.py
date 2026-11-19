"""Painel de controles V4L2 gerado a partir do que o driver reporta.

Nada de lista fixa de parâmetros: cada câmera mostra exatamente os controles que
anuncia, com a faixa, o step e os itens de menu dela.

Depois de QUALQUER escrita, o estado de todos os controles é relido (custa ~0,4 ms
na Redeagle), porque um controle pode ativar ou desativar outros. Ex.: auto_exposure em
'Manual Mode' ativa exposure_time_absolute.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sdk_elden.camera.controles import ControlesCamera, ErroControle
from sdk_elden.camera.dispositivos import InfoControle

INT32_MAX = 2**31 - 1  # limite de QSpinBox/QSlider


def cabe_em_int32(info: InfoControle) -> bool:
    return -INT32_MAX - 1 <= info.minimo and info.maximo <= INT32_MAX


class EditorControle(QWidget):
    """Widget de um controle. Emite a escrita por callback; recebe estado via `atualizar`."""

    def __init__(self, info: InfoControle, ao_escrever, ao_restaurar):
        super().__init__()
        self.info = info
        self._ao_escrever = ao_escrever
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._entrada = None  # widget que carrega o valor
        self._slider = None

        if not info.suportado:
            layout.addWidget(QLabel(f"tipo {info.tipo} não suportado"))
        elif info.tipo == "bool":
            self._entrada = QCheckBox()
            self._entrada.toggled.connect(lambda v: self._escrever(int(v)))
            layout.addWidget(self._entrada)
            layout.addStretch()
        elif info.tipo in ("menu", "intmenu"):
            self._entrada = QComboBox()
            for indice, rotulo in info.menu.items():
                self._entrada.addItem(str(rotulo), indice)
            self._entrada.activated.connect(lambda _i: self._escrever(self._entrada.currentData()))
            layout.addWidget(self._entrada, 1)
        elif cabe_em_int32(info):  # int, int64 pequeno, bitmask
            self._entrada = QSpinBox()
            self._entrada.setRange(info.minimo, info.maximo)
            self._entrada.setKeyboardTracking(False)  # escreve ao confirmar, não a cada dígito
            if info.tipo == "bitmask":
                self._entrada.setDisplayIntegerBase(16)
                self._entrada.setPrefix("0x")
            else:
                self._entrada.setSingleStep(max(info.passo, 1))
                self._slider = QSlider(Qt.Orientation.Horizontal)
                self._slider.setRange(info.minimo, info.maximo)
                self._slider.setSingleStep(max(info.passo, 1))
                self._slider.setPageStep(max(info.passo, (info.maximo - info.minimo) // 10, 1))
                # sincronia nos dois sentidos; setValue com o mesmo valor não reemite, então não há loop
                self._slider.valueChanged.connect(self._entrada.setValue)
                self._entrada.valueChanged.connect(self._slider.setValue)
                layout.addWidget(self._slider, 1)
            self._entrada.valueChanged.connect(self._escrever)
            layout.addWidget(self._entrada)
        else:
            layout.addWidget(QLabel(f"faixa [{info.minimo}, {info.maximo}] excede int32: não editável aqui"))

        if info.suportado and not info.somente_leitura:
            btn = QPushButton("↺")
            btn.setToolTip(f"Restaurar padrão do driver ({info.padrao})")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda: ao_restaurar(info.nome))
            layout.addWidget(btn)
            self._btn_padrao = btn
        else:
            self._btn_padrao = None
        self.atualizar(info)

    def _escrever(self, valor) -> None:
        if valor != self.info.valor:
            self._ao_escrever(self.info.nome, int(valor))

    def atualizar(self, info: InfoControle) -> None:
        """Reflete o estado do driver sem disparar escrita."""
        self.info = info
        editavel = info.suportado and not info.somente_leitura and not info.inativo
        motivo = (
            "somente leitura" if info.somente_leitura
            else "inativo: depende de outro controle (ex.: exposição manual exige auto_exposure = Manual Mode)"
            if info.inativo else ""
        )
        for w in (self._entrada, self._slider, self._btn_padrao):
            if w is None:
                continue
            w.blockSignals(True)
            w.setEnabled(editavel)
            w.setToolTip(motivo)
            w.blockSignals(False)
        if self._entrada is None or info.valor is None:
            return
        for w in (self._entrada, self._slider):
            if w is None:
                continue
            w.blockSignals(True)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(info.valor))
            elif isinstance(w, QComboBox):
                idx = w.findData(info.valor)
                if idx < 0:  # valor atual fora do menu anunciado (quirk): mostrar, não esconder
                    w.addItem(f"{info.valor} (fora do menu)", info.valor)
                    idx = w.count() - 1
                w.setCurrentIndex(idx)
            else:
                w.setValue(info.valor)
            w.blockSignals(False)


class PainelControles(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._controles: ControlesCamera | None = None
        self._editores: dict[str, EditorControle] = {}

        self._grade = QGridLayout()
        self._grade.setColumnStretch(1, 1)
        conteudo = QWidget()
        conteudo.setLayout(self._grade)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(conteudo)

        self.btn_reler = QPushButton("Reler do driver")
        self.btn_reler.setToolTip("Útil se outro programa (ex.: v4l2-ctl) mudou os controles")
        self.btn_reler.clicked.connect(self.reler)
        self.lbl_erro = QLabel()
        self.lbl_erro.setWordWrap(True)
        self.lbl_erro.setStyleSheet("color: #c0392b;")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Controles</b>"))
        layout.addWidget(rolagem, 1)
        layout.addWidget(self.btn_reler)
        layout.addWidget(self.lbl_erro)
        self.definir_camera(None)

    # --- ciclo de vida ----------------------------------------------------------
    def definir_camera(self, caminho: str | Path | None) -> None:
        self.fechar()
        if caminho is not None:
            try:
                self._controles = ControlesCamera(caminho)
            except OSError as e:
                self.lbl_erro.setText(f"não foi possível abrir controles de {caminho}: {e.strerror}")
        self._montar()

    def fechar(self) -> None:
        if self._controles is not None:
            self._controles.fechar()
            self._controles = None
        self._montar()

    def _montar(self) -> None:
        while self._grade.count():
            item = self._grade.takeAt(0)
            if w := item.widget():
                # takeAt só tira do layout; o widget segue filho/visível até o deleteLater
                # rodar no loop de eventos. setParent(None) o remove da tela na hora.
                w.setParent(None)
                w.deleteLater()
        self._editores.clear()
        self.btn_reler.setEnabled(self._controles is not None)
        if self._controles is None:
            self._grade.addWidget(QLabel("nenhuma câmera selecionada"), 0, 0)
            return
        self.lbl_erro.clear()
        for linha, info in enumerate(self._controles.todos()):
            rotulo = QLabel(info.nome)
            rotulo.setToolTip(f"tipo={info.tipo} min={info.minimo} max={info.maximo} "
                              f"step={info.passo} padrão={info.padrao}")
            editor = EditorControle(info, self._escrever, self._restaurar)
            self._grade.addWidget(rotulo, linha, 0)
            self._grade.addWidget(editor, linha, 1)
            self._editores[info.nome] = editor
        self._grade.setRowStretch(len(self._editores), 1)

    # --- operações ----------------------------------------------------------------
    def estado_atual(self) -> list[InfoControle]:
        """Controles lidos agora no driver (vazio se não houver câmera)."""
        return self._controles.todos() if self._controles is not None else []

    def reler(self) -> None:
        if self._controles is None:
            return
        for info in self._controles.todos():
            if info.nome in self._editores:
                self._editores[info.nome].atualizar(info)

    def _escrever(self, nome: str, valor: int) -> None:
        self._executar(lambda: self._controles.escrever(nome, valor))

    def _restaurar(self, nome: str) -> None:
        self._executar(lambda: self._controles.restaurar_padrao(nome))

    def _executar(self, operacao) -> None:
        try:
            operacao()
            self.lbl_erro.clear()
        except ErroControle as e:
            self.lbl_erro.setText(str(e))
        self.reler()  # sempre: mostra o valor REAL (inclusive após recusa) e as flags novas
