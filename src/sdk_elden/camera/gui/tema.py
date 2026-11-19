"""Tema escuro em tons de cinza da GUI (paleta do redesign de 2026-11-19).

Duas camadas, de propósito:
- QPalette no estilo Fusion: cobre o que o QSS não alcança (tooltips, texto desabilitado,
  seleção, menus de combobox).
- QSS: só o que a paleta não expressa (botões alternáveis, botão de captura, painéis,
  títulos de seção).

O estilo Fusion é fixado explicitamente: o estilo padrão varia conforme o tema do desktop
(GTK, KDE...) e mudaria a aparência sem aviso.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- paleta (cinzas neutros; cores só para estado) ---------------------------------
FUNDO = "#121212"          # janela
PAINEL = "#1A1A1A"         # painéis laterais, barras
PREVIEW = "#0D0D0D"        # área atrás do frame (letterbox)
CAMPO = "#242424"          # entradas, itens de lista
BORDA = "#2E2E2E"
BORDA_FORTE = "#3D3D3D"
ATIVO = "#3A3A3A"          # botão alternável ligado / item selecionado
BORDA_ATIVO = "#6B6B6B"
TEXTO = "#E6E6E6"
TEXTO_2 = "#CCCCCC"
TEXTO_MUDO = "#A3A3A3"
TEXTO_DESAB = "#757575"
ACENTO = "#B8B8B8"         # sliders, foco do teclado
AO_VIVO = "#3DD68C"
CAPTURA = "#C42B2B"        # branco sobre esta cor: contraste ~5:1
CAPTURA_HOVER = "#D63A3A"
ERRO = "#FF7B72"           # legível sobre o PAINEL (o #c0392b antigo ficava ~3:1)

FONTE_MONO = "'JetBrains Mono', 'DejaVu Sans Mono', monospace"
ALTERADO = "#F0B35A"       # "diferente do padrão do driver"

# setas dos spinbox/combobox: caminho absoluto do pacote (o QSS não resolve caminho relativo
# ao módulo). Arquivos declarados em package-data no pyproject.toml.
DIR_ICONES = Path(__file__).resolve().parent / "icones"


def _icone(nome: str) -> str:
    return (DIR_ICONES / f"{nome}.svg").as_posix()

QSS = f"""
QMainWindow {{ background: {FUNDO}; }}
QToolTip {{ background: {CAMPO}; color: {TEXTO}; border: 1px solid {BORDA_FORTE}; padding: 4px; }}

QToolBar#barraTopo {{ background: {PAINEL}; border: none; border-bottom: 1px solid {BORDA}; spacing: 6px; padding: 4px 8px; }}
QToolBar#barraTopo QToolButton {{ background: transparent; border: 1px solid {BORDA}; border-radius: 6px; padding: 5px 10px; color: {TEXTO}; }}
QToolBar#barraTopo QToolButton:hover {{ background: {CAMPO}; }}
QToolBar#barraTopo QToolButton:checked {{ background: {ATIVO}; border-color: {BORDA_ATIVO}; }}
QLabel#nomeApp {{ font-weight: 600; padding: 0 6px; }}
QLabel#chipCamera {{ background: {CAMPO}; color: {TEXTO_2}; border-radius: 6px; padding: 4px 10px; }}
QLabel#statusModo {{ color: {TEXTO_MUDO}; font-family: {FONTE_MONO}; }}
QLabel#statusModo[aoVivo="true"] {{ color: {AO_VIVO}; }}
QLabel#statusFps {{ color: {TEXTO_MUDO}; font-family: {FONTE_MONO}; padding-left: 14px; }}

/* Só os contêineres levam fundo; seletor de descendente (ex.: "#painel QWidget") venceria
   o "QPushButton" por especificidade e pintaria botões e listas com a cor do painel. */
QWidget#painelEsquerdo, QWidget#painelDireito, QWidget#conteudoControles {{ background: {PAINEL}; }}
QWidget#painelDireito QScrollArea {{ background: {PAINEL}; }}
QLabel#tituloSecao {{ color: {TEXTO_MUDO}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#infoCamera {{ color: {TEXTO_MUDO}; font-size: 12px; }}
QLabel#lblErro {{ color: {ERRO}; }}
QGroupBox {{ border: 1px solid {BORDA}; border-radius: 6px; margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {TEXTO_MUDO}; }}

QListWidget {{ background: {CAMPO}; border: 1px solid {BORDA}; border-radius: 6px; padding: 2px; }}
QListWidget::item {{ padding: 6px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {ATIVO}; color: {TEXTO}; }}

QPushButton {{ background: {CAMPO}; border: 1px solid {BORDA_FORTE}; border-radius: 6px; padding: 6px 12px; color: {TEXTO}; }}
QPushButton:hover {{ background: {ATIVO}; }}
QPushButton:disabled {{ color: {TEXTO_DESAB}; border-color: {BORDA}; }}
/* botão ↺ de largura fixa (28 px): com o padding acima sobravam 2 px e o símbolo virava um ponto */
QPushButton#btnPadrao {{ padding: 0; }}
/* gravar: neutro parado; vermelho enquanto grava (mesmo vermelho do capturar) */
QPushButton#btnGravar[gravando="true"] {{ background: {CAPTURA}; border: none; color: #FFFFFF; font-weight: 600; }}
QPushButton#btnRajada[ativo="true"] {{ background: {ALTERADO}; border: none; color: {FUNDO}; font-weight: 600; }}
QLabel#lblRajada {{ color: {ALTERADO}; font-family: {FONTE_MONO}; font-weight: 600; padding-left: 14px; }}
QLabel#lblRec {{ color: {ERRO}; font-family: {FONTE_MONO}; font-weight: 600; padding-left: 14px; }}
QPushButton#btnCapturar {{ background: {CAPTURA}; border: none; color: #FFFFFF; font-weight: 600; padding: 10px 18px; }}
QPushButton#btnCapturar:hover {{ background: {CAPTURA_HOVER}; }}
QPushButton#btnCapturar:disabled {{ background: {CAMPO}; color: {TEXTO_DESAB}; }}

QComboBox, QSpinBox {{ background: {CAMPO}; border: 1px solid {BORDA}; border-radius: 6px; padding: 4px 8px; color: {TEXTO}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {TEXTO_DESAB}; }}
QComboBox QAbstractItemView {{ background: {CAMPO}; selection-background-color: {ATIVO}; }}
QSpinBox:focus, QComboBox:focus, QListWidget:focus, QPushButton:focus {{ border: 1px solid {ACENTO}; }}

/* botões de aumentar/diminuir: seta para cima / para baixo */
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border-left: 1px solid {BORDA}; background: {CAMPO}; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; border-bottom: 1px solid {BORDA}; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {ATIVO}; }}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: {BORDA_ATIVO}; }}
QSpinBox::up-arrow {{ image: url({_icone("seta_cima")}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({_icone("seta_baixo")}); width: 10px; height: 10px; }}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{ image: url({_icone("seta_cima_desab")}); }}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {{ image: url({_icone("seta_baixo_desab")}); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({_icone("seta_baixo")}); width: 10px; height: 10px; }}
QComboBox::down-arrow:disabled {{ image: url({_icone("seta_baixo_desab")}); }}

/* grupos navegáveis: foco no quadro = nível de grupos; "dentro" = navegando nas paradas */
QFrame#grupoNav {{ border: 1px solid transparent; border-radius: 6px; }}
QFrame#grupoNav[dentro="true"] {{ border-color: {BORDA_ATIVO}; }}
QFrame#grupoNav:focus {{ border: 1px solid {ACENTO}; background: {CAMPO}; }}
QLabel#lblAlterado {{ color: {ALTERADO}; font-size: 11px; }}

QFrame#barraCaptura {{ background: {PAINEL}; border-top: 1px solid {BORDA}; }}
QLabel#lblDestino {{ color: {TEXTO_2}; font-family: {FONTE_MONO}; }}
QLabel#lblUltima {{ color: {TEXTO_MUDO}; font-size: 12px; }}

QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {BORDA}; }}
QStatusBar {{ background: {PAINEL}; color: {TEXTO_MUDO}; border-top: 1px solid {BORDA}; }}
QStatusBar QLabel {{ color: {TEXTO_MUDO}; }}
"""


def paleta() -> QPalette:
    p = QPalette()
    cores = {
        QPalette.ColorRole.Window: FUNDO,
        QPalette.ColorRole.WindowText: TEXTO,
        QPalette.ColorRole.Base: CAMPO,
        QPalette.ColorRole.AlternateBase: PAINEL,
        QPalette.ColorRole.Text: TEXTO,
        QPalette.ColorRole.Button: CAMPO,
        QPalette.ColorRole.ButtonText: TEXTO,
        QPalette.ColorRole.ToolTipBase: CAMPO,
        QPalette.ColorRole.ToolTipText: TEXTO,
        QPalette.ColorRole.Highlight: ACENTO,
        QPalette.ColorRole.HighlightedText: FUNDO,
        QPalette.ColorRole.PlaceholderText: TEXTO_DESAB,
    }
    for papel, cor in cores.items():
        p.setColor(papel, QColor(cor))
    for papel in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, papel, QColor(TEXTO_DESAB))
    return p


def aplicar_tema(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(paleta())
    app.setStyleSheet(QSS)
