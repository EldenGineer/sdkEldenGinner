"""Painel de controles V4L2 gerado a partir do que o driver reporta.

Nada de lista fixa de parâmetros: cada câmera mostra exatamente os controles que
anuncia, com a faixa, o step e os itens de menu dela. A tabela GRUPOS só decide EM QUE
GRUPO um controle anunciado aparece; controle fora da tabela vai para "Outros" (nunca some).

Depois de QUALQUER escrita, o estado de todos os controles é relido (custa ~0,4 ms
na Redeagle), porque um controle pode ativar ou desativar outros. Ex.: auto_exposure em
'Manual Mode' ativa exposure_time_absolute.

Teclado (ver navegacao.py): cada controle tem UMA parada (spinbox, combo ou caixa); o slider
e o botão ↺ ficam fora do Tab para não triplicar as paradas. R restaura o padrão.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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
from sdk_elden.camera.gui.navegacao import DICA_DENTRO, GrupoNavegavel

INT32_MAX = 2**31 - 1  # limite de QSpinBox/QSlider

# nome do controle (estilo v4l2-ctl) -> grupo. Decisão do usuário (2026-11-19): tabela por
# nome + "Outros", em vez da classe V4L2 (User/Camera), que é grossa demais para navegar.
GRUPOS: dict[str, str] = {
    **dict.fromkeys(("brightness", "contrast", "saturation", "hue", "gamma", "sharpness"), "Imagem"),
    **dict.fromkeys(("auto_exposure", "exposure_time_absolute", "exposure_dynamic_framerate", "gain",
                     "backlight_compensation", "power_line_frequency"), "Exposição e ganho"),
    **dict.fromkeys(("white_balance_automatic", "white_balance_temperature"), "Cor"),
    **dict.fromkeys(("focus_automatic_continuous", "focus_absolute", "zoom_absolute", "pan_absolute",
                     "tilt_absolute"), "Foco e enquadramento"),
}
OUTROS = "Outros"
ORDEM_GRUPOS = ("Imagem", "Exposição e ganho", "Cor", "Foco e enquadramento", OUTROS)


def agrupar(infos: list[InfoControle]) -> list[tuple[str, list[InfoControle]]]:
    """Controles por grupo, na ORDEM_GRUPOS; dentro do grupo, a ordem do driver. Grupo vazio some."""
    por_grupo: dict[str, list[InfoControle]] = {g: [] for g in ORDEM_GRUPOS}
    for info in infos:
        por_grupo[GRUPOS.get(info.nome, OUTROS)].append(info)
    return [(g, lista) for g, lista in por_grupo.items() if lista]


def cabe_em_int32(info: InfoControle) -> bool:
    return -INT32_MAX - 1 <= info.minimo and info.maximo <= INT32_MAX


def descricao(info: InfoControle) -> str:
    return f"tipo={info.tipo} min={info.minimo} max={info.maximo} step={info.passo} padrão={info.padrao}"


def atalhos(info: InfoControle) -> str:
    """Atalhos de teclado do controle, conforme o widget que ele usa."""
    if info.tipo == "bool":
        proprios = "X: marcar/desmarcar"
    elif info.tipo in ("menu", "intmenu"):
        proprios = "W/S ou ↑/↓: opção anterior/próxima"
    elif info.tipo == "bitmask":
        proprios = "W/S ou ↑/↓: ±1 · digite em hexadecimal"
    else:
        proprios = f"W/S ou ↑/↓: ±{max(info.passo, 1)} · PgUp/PgDn: passo maior · digite e Enter"
    return f"{proprios} · R: restaurar padrão\n{DICA_DENTRO}"


class EditorControle(QWidget):
    """Widget de um controle. Emite a escrita por callback; recebe estado via `atualizar`."""

    def __init__(self, info: InfoControle, ao_escrever, ao_restaurar):
        super().__init__()
        self.info = info
        self._ao_escrever = ao_escrever
        self._ao_restaurar = ao_restaurar
        self.rotulo: QLabel | None = None  # rótulo externo (do painel), recebe o mesmo tooltip
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._entrada = None  # widget que carrega o valor (e é a parada do teclado)
        self._slider = None
        self._lbl_alterado = None

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
            # `activated` também é emitido ao trocar o item pelo teclado (↑/↓, W/S); verificado em teste
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
                self._slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # parada única: o spinbox
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

        if self._entrada is not None:
            self._lbl_alterado = QLabel("≠ padrão")
            self._lbl_alterado.setObjectName("lblAlterado")
            layout.addWidget(self._lbl_alterado)
        if info.suportado and not info.somente_leitura:
            btn = QPushButton("↺")
            btn.setObjectName("btnPadrao")  # padding zerado no tema: o padrão de botão não cabe em 28 px
            btn.setFixedWidth(28)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # pelo teclado: tecla R
            btn.clicked.connect(self.restaurar)
            layout.addWidget(btn)
            self._btn_padrao = btn
        else:
            self._btn_padrao = None
        self.atualizar(info)

    @property
    def entrada(self) -> QWidget | None:
        """Widget de parada do teclado (None se o controle não é editável aqui)."""
        return self._entrada

    def restaurar(self) -> None:
        if self._btn_padrao is not None and self._btn_padrao.isEnabled():
            self._ao_restaurar(self.info.nome)

    def _escrever(self, valor) -> None:
        if valor != self.info.valor:
            self._ao_escrever(self.info.nome, int(valor))

    def alterado(self) -> bool:
        """Valor atual diferente do padrão do driver."""
        return self.info.suportado and self.info.valor is not None and self.info.valor != self.info.padrao

    def atualizar(self, info: InfoControle) -> None:
        """Reflete o estado do driver sem disparar escrita."""
        self.info = info
        editavel = info.suportado and not info.somente_leitura and not info.inativo
        motivo = (
            "somente leitura" if info.somente_leitura
            else "inativo: depende de outro controle (ex.: exposição manual exige auto_exposure = Manual Mode)"
            if info.inativo else ""
        )
        dica = "\n".join(p for p in (motivo, descricao(info), atalhos(info)) if p)
        if self.rotulo is not None:
            self.rotulo.setToolTip(dica)
        for w in (self._entrada, self._slider, self._btn_padrao):
            if w is None:
                continue
            w.blockSignals(True)
            w.setEnabled(editavel)
            w.setToolTip(f"Restaurar padrão do driver ({info.padrao}) — tecla R" if w is self._btn_padrao else dica)
            w.blockSignals(False)
        if self._lbl_alterado is not None:
            self._lbl_alterado.setVisible(self.alterado())
            self._lbl_alterado.setToolTip(f"diferente do padrão do driver ({info.padrao})")
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
        self._grupos: list[GrupoNavegavel] = []

        self._lista = QVBoxLayout()  # grupos, um abaixo do outro
        self._lista.setContentsMargins(0, 0, 0, 0)
        self._lista.setSpacing(8)
        conteudo = self._conteudo = QWidget()
        conteudo.setObjectName("conteudoControles")  # fundo vem do tema (tema.py)
        conteudo.setLayout(self._lista)
        rolagem = self._rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        # sem rolagem horizontal: a grade é obrigada a caber na largura e os sliders encolhem
        # (com rolagem, o botão ↺ ficava cortado fora da área visível)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(conteudo)

        self.btn_reler = QPushButton("Reler do driver")
        self.btn_reler.setToolTip("Útil se outro programa (ex.: v4l2-ctl) mudou os controles")
        self.btn_reler.clicked.connect(self.reler)
        self.lbl_erro = QLabel()
        self.lbl_erro.setWordWrap(True)
        self.lbl_erro.setObjectName("lblErro")  # cor no tema: legível no fundo escuro

        self.lbl_titulo = QLabel("CONTROLES")
        self.lbl_titulo.setObjectName("tituloSecao")
        layout = QVBoxLayout(self)
        layout.addWidget(self.lbl_titulo)
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

    def grupos(self) -> list[GrupoNavegavel]:
        """Grupos de navegação por teclado, na ordem da tela."""
        return list(self._grupos)

    def _montar(self) -> None:
        while self._lista.count():
            item = self._lista.takeAt(0)
            if w := item.widget():
                # takeAt só tira do layout; o widget segue filho/visível até o deleteLater
                # rodar no loop de eventos. hide() o tira da tela na hora. NÃO usar
                # setParent(None): o widget vira janela de nível superior por um instante e,
                # no plugin offscreen, isso desativava a janela principal (foco de teclado perdido).
                w.hide()
                w.deleteLater()
        self._editores.clear()
        self._grupos.clear()
        self.btn_reler.setEnabled(self._controles is not None)
        if self._controles is None:
            self._lista.addWidget(QLabel("nenhuma câmera selecionada"))
            self._lista.addStretch(1)
            self.lbl_titulo.setText("CONTROLES")
            return
        self.lbl_erro.clear()
        rotulos: list[QLabel] = []
        for nome_grupo, infos in agrupar(self._controles.todos()):
            grupo = GrupoNavegavel(nome_grupo.upper())
            grade = QGridLayout()
            grade.setColumnStretch(1, 1)
            grade.setVerticalSpacing(6)
            for linha, info in enumerate(infos):
                rotulo = QLabel(info.nome)
                editor = EditorControle(info, self._escrever, self._restaurar)
                editor.rotulo = rotulo
                editor.atualizar(info)  # aplica o tooltip (com atalhos) também no rótulo
                grade.addWidget(rotulo, linha, 0)
                grade.addWidget(editor, linha, 1)
                if editor.entrada is not None:
                    grupo.adicionar_parada(editor.entrada)
                self._editores[info.nome] = editor
                rotulos.append(rotulo)
            grupo.corpo.addLayout(grade)
            self._lista.addWidget(grupo)
            self._grupos.append(grupo)
        self._lista.addStretch(1)
        # mesma largura de rótulo em todos os grupos: as colunas dos editores ficam alinhadas
        largura = max((r.sizeHint().width() for r in rotulos), default=0)
        for r in rotulos:
            r.setMinimumWidth(largura)
        self._atualizar_titulo()
        # medir só no próximo ciclo: com o painel já visível, os widgets recém-criados ficam
        # ocultos até o loop de eventos rodar, e o Qt ignora ocultos no minimumSizeHint
        # (medido na hora dava 32 px com a Redeagle)
        self._ajustar_largura()
        QTimer.singleShot(0, self._ajustar_largura)

    def _atualizar_titulo(self) -> None:
        alterados = sum(e.alterado() for e in self._editores.values())
        texto = f"CONTROLES · {len(self._editores)}"
        if alterados:
            texto += f" · {alterados} ≠ padrão"
        self.lbl_titulo.setText(texto)

    def _ajustar_largura(self) -> None:
        """Largura mínima = a da grade montada agora (os controles mudam por câmera).

        O QScrollArea não repassa a largura do conteúdo ao layout; sem isto o splitter
        dava menos espaço que a grade precisa e os botões ↺ ficavam cortados.
        """
        barra = self._rolagem.verticalScrollBar().sizeHint().width()
        moldura = 2 * self._rolagem.frameWidth()
        self._rolagem.setMinimumWidth(self._conteudo.minimumSizeHint().width() + barra + moldura)
        # o QSplitter ignora mudanças de minimumSizeHint de um filho já montado (nem
        # setSizes reaplica); um mínimo EXPLÍCITO no painel ele respeita
        self.setMinimumWidth(0)
        self.setMinimumWidth(self.minimumSizeHint().width())

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
        self._atualizar_titulo()

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
