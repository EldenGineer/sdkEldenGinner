"""Navegação por teclado em dois níveis: grupos e, dentro de cada grupo, as paradas.

Nível de grupos (o foco está no quadro do grupo):
    Tab          próximo grupo (depois de JANELA_DUPLO_TAB_MS, ver abaixo)
    Tab Tab      entra no grupo (foco na primeira parada)
    Shift+Tab    grupo anterior (imediato)
    Esc          callback `ao_esc_fora` (na janela principal: sai do modo Foco)

Dentro de um grupo (o foco está numa parada):
    Tab / Shift+Tab   próxima / parada anterior, circular
    Esc               volta ao nível de grupos
    W / S             mesmo que ↑ / ↓ em spinbox, slider, combobox e lista
    X                 marca/desmarca caixa de seleção
    Enter             aciona o botão em foco
    R                 `restaurar()` do ancestral que tiver esse método (EditorControle)

Duplo Tab: o 1º Tab NÃO move na hora; espera JANELA_DUPLO_TAB_MS. Se vier um 2º Tab nesse
intervalo, entra no grupo; senão, move para o próximo. Custo aceito (decisão do usuário,
2026-11-19): cada Tab entre grupos tem esse atraso.

As paradas de cada grupo são registradas EXPLICITAMENTE (`adicionar_parada`), em vez de
descobertas pela cadeia de foco do Qt: a ordem e o que conta como parada ficam sob controle.
"""
from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

JANELA_DUPLO_TAB_MS = 250

DICA_GRUPO = "Tab: próximo grupo · Tab Tab: entrar · Shift+Tab: grupo anterior"
DICA_DENTRO = "Tab/Shift+Tab: próximo/anterior · Esc: sair do grupo"


class GrupoNavegavel(QFrame):
    """Quadro com título opcional; o conteúdo vai em `corpo` e as paradas são registradas."""

    def __init__(self, titulo: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("grupoNav")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # clique dentro do grupo não foca o quadro
        self.setToolTip(DICA_GRUPO)
        self._paradas: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
        self.lbl_titulo = None
        if titulo:
            self.lbl_titulo = QLabel(titulo)
            self.lbl_titulo.setObjectName("tituloSecao")
            layout.addWidget(self.lbl_titulo)
        self.corpo = QVBoxLayout()
        self.corpo.setSpacing(6)
        layout.addLayout(self.corpo)

    def adicionar_parada(self, widget: QWidget) -> None:
        self._paradas.append(widget)

    def paradas(self) -> list[QWidget]:
        """Paradas utilizáveis agora (visíveis e habilitadas), na ordem de registro."""
        return [w for w in self._paradas if w.isVisibleTo(self) and w.isEnabled()]

    def contem(self, widget: QWidget | None) -> bool:
        return widget is not None and any(w is widget or w.isAncestorOf(widget) for w in self._paradas)

    def marcar_ativo(self, sim: bool) -> None:
        """Destaque de 'estou dentro deste grupo' (o foco está numa parada dele)."""
        if self.property("dentro") == sim:
            return
        self.setProperty("dentro", sim)
        self.style().unpolish(self)
        self.style().polish(self)


class Navegador(QObject):
    """Filtro de teclado de UMA janela. Instalado na QApplication, ignora eventos de outras
    janelas (diálogos seguem com o Tab normal do Qt)."""

    def __init__(self, janela: QWidget, grupos: Callable[[], Iterable[GrupoNavegavel]],
                 ao_esc_fora: Callable[[], None] | None = None):
        super().__init__(janela)
        self._janela = janela
        self._grupos = grupos
        self._ao_esc_fora = ao_esc_fora
        self._timer_tab = QTimer(self)
        self._timer_tab.setSingleShot(True)
        self._timer_tab.setInterval(JANELA_DUPLO_TAB_MS)
        self._timer_tab.timeout.connect(lambda: self._mover_grupo(+1))
        app = QApplication.instance()
        app.installEventFilter(self)
        app.focusChanged.connect(self._ao_mudar_foco)

    # --- consultas -----------------------------------------------------------------
    def grupos(self) -> list[GrupoNavegavel]:
        return [g for g in self._grupos() if g.isVisible()]

    def grupo_de(self, widget: QWidget | None) -> GrupoNavegavel | None:
        """Grupo cuja parada contém o widget (None se o widget não está dentro de nenhum)."""
        return next((g for g in self.grupos() if g.contem(widget)), None)

    # --- ações ---------------------------------------------------------------------
    def entrar(self, grupo: GrupoNavegavel) -> bool:
        paradas = grupo.paradas()
        if not paradas:
            return False  # tudo desabilitado (ex.: modo travado com stream aberto): fica no grupo
        paradas[0].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def _mover_grupo(self, passo: int) -> None:
        grupos = self.grupos()
        if not grupos:
            return
        atual = QApplication.focusWidget()
        if atual in grupos:
            alvo = grupos[(grupos.index(atual) + passo) % len(grupos)]
        else:
            alvo = grupos[0] if passo > 0 else grupos[-1]
        alvo.setFocus(Qt.FocusReason.TabFocusReason)

    def _mover_dentro(self, grupo: GrupoNavegavel, atual: QWidget, passo: int) -> None:
        paradas = grupo.paradas()
        if not paradas:
            grupo.setFocus()
            return
        i = next((k for k, w in enumerate(paradas) if w is atual or w.isAncestorOf(atual)), -1)
        paradas[(i + passo) % len(paradas)].setFocus(Qt.FocusReason.TabFocusReason)

    def _ao_mudar_foco(self, _antigo, novo) -> None:
        dentro = self.grupo_de(novo)
        for g in self._grupos():
            g.marcar_ativo(g is dentro)

    # --- filtro --------------------------------------------------------------------
    def eventFilter(self, obj, evento) -> bool:
        if evento.type() != QEvent.Type.KeyPress or not isinstance(obj, QWidget):
            return False
        if obj.window() is not self._janela:
            return False
        foco = QApplication.focusWidget()
        if obj is not foco:
            return False  # o mesmo evento passa por pais/proxies: tratar uma vez só
        return self._tecla(evento, foco)

    def _tecla(self, ev: QKeyEvent, foco: QWidget) -> bool:
        tecla, mods = ev.key(), ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        grupo_foco = foco if isinstance(foco, GrupoNavegavel) else None
        grupo_dentro = None if grupo_foco else self.grupo_de(foco)

        # Shift+Tab chega como Key_Backtab pela plataforma, mas como Tab+Shift em eventos sintéticos
        if tecla == Qt.Key.Key_Backtab or (tecla == Qt.Key.Key_Tab and mods & Qt.KeyboardModifier.ShiftModifier):
            self._timer_tab.stop()
            if grupo_dentro:
                self._mover_dentro(grupo_dentro, foco, -1)
            else:
                self._mover_grupo(-1)
            return True
        if tecla == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
            if grupo_dentro:
                self._mover_dentro(grupo_dentro, foco, +1)
            elif grupo_foco and self._timer_tab.isActive():
                self._timer_tab.stop()
                self.entrar(grupo_foco)
            elif grupo_foco:
                self._timer_tab.start()
            else:
                self._mover_grupo(+1)  # foco fora de qualquer grupo: vai direto ao 1º
            return True
        if tecla == Qt.Key.Key_Escape and mods == Qt.KeyboardModifier.NoModifier:
            if grupo_dentro:
                grupo_dentro.setFocus(Qt.FocusReason.OtherFocusReason)
            elif self._ao_esc_fora:
                self._ao_esc_fora()
            return True

        if mods != Qt.KeyboardModifier.NoModifier or isinstance(foco, QLineEdit):
            return False  # Ctrl+... são atalhos da janela; em campo de texto, letras são texto
        if tecla in (Qt.Key.Key_W, Qt.Key.Key_S) and isinstance(
                foco, (QAbstractSpinBox, QAbstractSlider, QComboBox, QListWidget)):
            if isinstance(foco, QComboBox) and foco.isEditable():
                return False
            seta = Qt.Key.Key_Up if tecla == Qt.Key.Key_W else Qt.Key.Key_Down
            QApplication.sendEvent(foco, QKeyEvent(QEvent.Type.KeyPress, seta, Qt.KeyboardModifier.NoModifier))
            return True
        if tecla == Qt.Key.Key_X and isinstance(foco, QCheckBox):
            foco.click()
            return True
        if tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and isinstance(foco, QAbstractButton):
            foco.click()
            return True
        if tecla == Qt.Key.Key_R:
            dono = foco
            while dono is not None and not hasattr(dono, "restaurar"):
                dono = dono.parentWidget()
            if dono is not None:
                dono.restaurar()
                return True
        return False
