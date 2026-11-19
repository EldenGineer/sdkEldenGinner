"""Navegação por teclado (navegacao.py) numa janela mínima, sem câmera, no plugin offscreen."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sdk_elden.camera.gui.navegacao import JANELA_DUPLO_TAB_MS, GrupoNavegavel, Navegador

ESPERA_MOVER = JANELA_DUPLO_TAB_MS + 150


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class ComRestaurar(QWidget):
    """Imita o EditorControle: ancestral com `restaurar()` (tecla R)."""

    def __init__(self):
        super().__init__()
        self.restaurados = 0
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setValue(50)
        QVBoxLayout(self).addWidget(self.spin)

    def restaurar(self):
        self.restaurados += 1


@pytest.fixture
def tela(app):
    janela = QWidget()
    raiz = QVBoxLayout(janela)
    g1, g2 = GrupoNavegavel("UM"), GrupoNavegavel("DOIS")
    editor = ComRestaurar()
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    g1.corpo.addWidget(editor)
    g1.corpo.addWidget(combo)
    g1.adicionar_parada(editor.spin)
    g1.adicionar_parada(combo)
    caixa, botao, texto = QCheckBox(), QPushButton("ok"), QLineEdit()
    for w in (caixa, botao, texto):
        g2.corpo.addWidget(w)
        g2.adicionar_parada(w)
    raiz.addWidget(g1)
    raiz.addWidget(g2)
    esc_fora, espacos = [], []
    nav = Navegador(janela, lambda: [g1, g2], ao_esc_fora=lambda: esc_fora.append(1),
                    teclas_reservadas={Qt.Key.Key_Space: lambda: espacos.append(1)})
    janela.show()
    janela.activateWindow()
    assert QTest.qWaitForWindowActive(janela)
    ns = type("Tela", (), {})()
    ns.__dict__.update(janela=janela, g1=g1, g2=g2, editor=editor, spin=editor.spin, combo=combo,
                       caixa=caixa, botao=botao, texto=texto, esc_fora=esc_fora, espacos=espacos, nav=nav)
    yield ns
    janela.close()
    janela.deleteLater()


def tecla(t, k, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(QApplication.focusWidget() or t.janela, k, mods)


def foco():
    return QApplication.focusWidget()


def test_tab_simples_move_entre_grupos_apos_a_espera(tela):
    tela.g1.setFocus()
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.g1  # ainda esperando um possível 2º Tab
    QTest.qWait(ESPERA_MOVER)
    assert foco() is tela.g2
    tecla(tela, Qt.Key.Key_Tab)
    QTest.qWait(ESPERA_MOVER)
    assert foco() is tela.g1  # circular


def test_tab_fora_de_grupo_vai_ao_primeiro(tela):
    tela.janela.setFocus()
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.g1


def test_duplo_tab_entra_e_tab_navega_dentro(tela):
    tela.g1.setFocus()
    tecla(tela, Qt.Key.Key_Tab)
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.spin
    assert tela.g1.property("dentro") is True
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.combo
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.spin  # circular dentro do grupo, não escapa para o g2
    tecla(tela, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert foco() is tela.combo


def test_shift_tab_no_nivel_de_grupos_e_imediato(tela):
    tela.g1.setFocus()
    tecla(tela, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert foco() is tela.g2


def test_esc_sai_do_grupo_e_depois_chama_callback(tela):
    tela.combo.setFocus()
    tecla(tela, Qt.Key.Key_Escape)
    assert foco() is tela.g1 and tela.esc_fora == []
    assert tela.g1.property("dentro") is False
    tecla(tela, Qt.Key.Key_Escape)
    assert tela.esc_fora == [1]


def test_w_s_no_spinbox(tela):
    tela.spin.setFocus()
    tecla(tela, Qt.Key.Key_W)
    assert tela.spin.value() == 51
    tecla(tela, Qt.Key.Key_S)
    tecla(tela, Qt.Key.Key_S)
    assert tela.spin.value() == 49


def test_w_s_no_combo_emite_activated(tela):
    """O painel de controles escreve no driver pelo `activated`: precisa disparar pelo teclado."""
    ativados = []
    tela.combo.activated.connect(ativados.append)
    tela.combo.setFocus()
    tecla(tela, Qt.Key.Key_S)
    assert tela.combo.currentText() == "b" and ativados == [1]
    tecla(tela, Qt.Key.Key_W)
    assert tela.combo.currentText() == "a" and ativados == [1, 0]


def test_x_marca_caixa_e_enter_aciona_botao(tela):
    cliques = []
    tela.botao.clicked.connect(lambda: cliques.append(1))
    tela.caixa.setFocus()
    tecla(tela, Qt.Key.Key_X)
    assert tela.caixa.isChecked()
    tecla(tela, Qt.Key.Key_X)
    assert not tela.caixa.isChecked()
    tela.botao.setFocus()
    tecla(tela, Qt.Key.Key_Return)
    assert cliques == [1]


def test_r_chama_restaurar_do_ancestral(tela):
    tela.spin.setFocus()
    tecla(tela, Qt.Key.Key_R)
    assert tela.editor.restaurados == 1


def test_letras_em_campo_de_texto_sao_texto(tela):
    tela.texto.setFocus()
    QTest.keyClicks(tela.texto, "wsxr")
    assert tela.texto.text() == "wsxr"


def test_parada_desabilitada_e_pulada(tela):
    tela.spin.setEnabled(False)
    tela.g1.setFocus()
    tecla(tela, Qt.Key.Key_Tab)
    tecla(tela, Qt.Key.Key_Tab)
    assert foco() is tela.combo


def test_outra_janela_nao_e_afetada(app, tela):
    outra = QWidget()
    a, b = QSpinBox(outra), QSpinBox(outra)
    a.move(0, 0)
    b.move(0, 40)
    outra.show()
    outra.activateWindow()
    assert QTest.qWaitForWindowActive(outra)
    a.setFocus()
    QTest.keyClick(a, Qt.Key.Key_W)
    assert a.value() == 0  # W não vira seta fora da janela do navegador
    outra.close()


# --- tecla reservada (Espaço = capturar na janela principal) ------------------------------
def test_espaco_reservado_em_qualquer_parada(tela):
    """Regressão: no spinbox o Espaço virava texto e a ação reservada não disparava."""
    cliques = []
    tela.botao.clicked.connect(lambda: cliques.append(1))
    for w in (tela.spin, tela.combo, tela.caixa, tela.botao, tela.g1):
        w.setFocus()
        tecla(tela, Qt.Key.Key_Space)
    assert len(tela.espacos) == 5
    assert tela.spin.value() == 50 and tela.combo.currentText() == "a"  # widgets intactos
    assert not tela.caixa.isChecked() and cliques == []


def test_espaco_sem_foco_nenhum(app, tela):
    tela.janela.setFocus()
    w = QApplication.focusWidget()
    if w is not None:
        w.clearFocus()
    QTest.keyClick(tela.janela, Qt.Key.Key_Space)
    assert tela.espacos == [1]


def test_espaco_segurado_conta_uma_vez(app, tela):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    tela.spin.setFocus()
    for repeticao in (False, True, True, True, True):  # 1º aperto + 4 repetições automáticas
        app.sendEvent(tela.spin, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                           Qt.KeyboardModifier.NoModifier, " ", repeticao))
    assert tela.espacos == [1]
    assert tela.spin.value() == 50  # nem as repetições chegaram ao campo


def test_espaco_com_modificador_nao_e_reservado(tela):
    tela.spin.setFocus()
    tecla(tela, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert tela.espacos == []
