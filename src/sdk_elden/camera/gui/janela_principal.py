"""Janela principal: lista de câmeras, escolha de modo e preview ao vivo.

As opções dos combos vêm dos modos que o driver anuncia (dispositivos.listar_cameras),
em cascata formato -> resolução -> FPS, a mesma ordem da negociação.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolBar,
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
from sdk_elden.camera.gravacao import (
    SECAO_GRAVACAO,
    TEMPO_MAX_FINALIZAR_S,
    ConfigGravacao,
    ErroGravacao,
    Gravador,
    finalizar_com_sidecar,
    iniciar_gravacao,
)
from sdk_elden.camera.gui.janela_config import JanelaConfig
from sdk_elden.camera.gui.navegacao import DICA_DENTRO, GrupoNavegavel, Navegador
from sdk_elden.camera.gui.tema import aplicar_tema
from sdk_elden.camera.gui.painel_controles import PainelControles
from sdk_elden.camera.gui.preview import WidgetPreview
from sdk_elden.camera.gui.thread_captura import ThreadCaptura
from sdk_elden.utils.config import ErroConfig, carregar_secao, salvar_secao

TEMPO_MAX_PARADA_MS = 3000  # espera explícita pelo fim da thread ao parar/trocar
LARGURA_COMPACTA = 1200     # abaixo disto (px) os painéis se ocultam ao cruzar o limite
LARGURA_MIN_ESQUERDO = 240
INTERVALO_REC_MS = 500     # atualização do indicador ● REC


class _SinaisGravacao(QObject):
    """Ponte da thread que finaliza o vídeo para a GUI (sinal entre threads = fila de eventos)."""
    finalizada = Signal(object, object)  # Path do vídeo (ou None), mensagem de erro (ou None)


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
        self.cfg_grav, erro_grav = self._carregar_config_gravacao()
        erro_cfg = "\n".join(e for e in (erro_cfg, erro_grav) if e) or None
        self._gravador: Gravador | None = None
        self._grav_contexto: tuple | None = None  # (cfg_arm, meta) da gravação em curso, p/ o sidecar
        self._finalizacoes: list[threading.Thread] = []
        self._sinais_grav = _SinaisGravacao(self)
        self._sinais_grav.finalizada.connect(self._ao_finalizar_gravacao)

        # estado dos painéis: o que estava visível antes de entrar no foco / no modo compacto
        self._antes_foco: tuple[bool, bool] | None = None
        self._antes_compacta: tuple[bool, bool] | None = None
        self._compacta = False

        # --- painel esquerdo ---------------------------------------------
        # cada bloco é um GrupoNavegavel: Tab passa entre blocos, Tab Tab entra (navegacao.py)
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._camera_selecionada)
        self.lista.setToolTip(f"W/S ou ↑/↓: câmera anterior/próxima\n{DICA_DENTRO}")
        btn_atualizar = QPushButton("Atualizar lista")
        btn_atualizar.clicked.connect(self.atualizar_cameras)
        btn_atualizar.setToolTip(f"Enter: atualizar\n{DICA_DENTRO}")
        self.grupo_cameras = GrupoNavegavel("CÂMERAS")
        self.grupo_cameras.corpo.addWidget(self.lista, 1)
        self.grupo_cameras.corpo.addWidget(btn_atualizar)
        for w in (self.lista, btn_atualizar):
            self.grupo_cameras.adicionar_parada(w)

        self.cb_formato, self.cb_resolucao, self.cb_fps = QComboBox(), QComboBox(), QComboBox()
        self.cb_formato.currentIndexChanged.connect(self._preencher_resolucoes)
        self.cb_resolucao.currentIndexChanged.connect(self._preencher_fps)
        form = QFormLayout()
        form.addRow("Formato", self.cb_formato)
        form.addRow("Resolução", self.cb_resolucao)
        form.addRow("FPS", self.cb_fps)
        for cb in (self.cb_formato, self.cb_resolucao, self.cb_fps):
            cb.setToolTip(f"W/S ou ↑/↓: opção anterior/próxima · travado com o stream aberto\n{DICA_DENTRO}")

        self.btn_abrir = QPushButton("Abrir")
        self.btn_abrir.clicked.connect(self.abrir)
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.clicked.connect(self.parar)
        self.btn_parar.setEnabled(False)
        for b in (self.btn_abrir, self.btn_parar):
            b.setToolTip(f"Enter: acionar\n{DICA_DENTRO}")
        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_abrir)
        botoes.addWidget(self.btn_parar)
        self.grupo_modo = GrupoNavegavel("MODO")
        self.grupo_modo.corpo.addLayout(form)
        self.grupo_modo.corpo.addLayout(botoes)
        for w in (self.cb_formato, self.cb_resolucao, self.cb_fps, self.btn_abrir, self.btn_parar):
            self.grupo_modo.adicionar_parada(w)  # desabilitados são pulados (ex.: com stream aberto)

        self.lbl_info = QLabel()
        self.lbl_info.setObjectName("infoCamera")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        esquerda = QVBoxLayout()
        esquerda.addWidget(self.grupo_cameras, 1)
        esquerda.addWidget(self.grupo_modo)
        esquerda.addWidget(self.lbl_info)
        self.painel_esquerdo = QWidget()
        self.painel_esquerdo.setObjectName("painelEsquerdo")
        self.painel_esquerdo.setLayout(esquerda)
        self.painel_esquerdo.setMinimumWidth(LARGURA_MIN_ESQUERDO)

        # --- centro: preview + barra de captura -------------------------------
        self.preview = WidgetPreview()
        self.btn_capturar = QPushButton("Capturar  [Espaço]")
        self.btn_capturar.setObjectName("btnCapturar")
        self.btn_capturar.clicked.connect(self.capturar)
        self.btn_capturar.setEnabled(False)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.capturar)
        titulo_destino = QLabel("DESTINO")
        titulo_destino.setObjectName("tituloSecao")
        self.lbl_destino = QLabel()
        self.lbl_destino.setObjectName("lblDestino")
        self.lbl_destino.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # caminho longo não pode empurrar o botão para fora: o rótulo cede largura (texto
        # completo no tooltip). Fica fora de QFormLayout de propósito (ver CLAUDE.md).
        self.lbl_destino.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_ultima = QLabel()
        self.lbl_ultima.setObjectName("lblUltima")
        coluna_destino = QVBoxLayout()
        coluna_destino.setSpacing(2)
        coluna_destino.addWidget(titulo_destino)
        coluna_destino.addWidget(self.lbl_destino)
        self.btn_capturar.setToolTip(f"Espaço (de qualquer lugar) ou Enter\n{DICA_DENTRO}")
        self.btn_gravar = QPushButton("Gravar  [Ctrl+R]")
        self.btn_gravar.setObjectName("btnGravar")
        self.btn_gravar.clicked.connect(self.alternar_gravacao)
        self.btn_gravar.setEnabled(False)
        self.btn_gravar.setToolTip(f"Ctrl+R (de qualquer lugar) ou Enter: inicia/para a gravação de vídeo\n{DICA_DENTRO}")
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.alternar_gravacao)
        self.grupo_captura = GrupoNavegavel()  # sem título: a barra já mostra "DESTINO"
        linha_captura = QHBoxLayout()
        linha_captura.addLayout(coluna_destino, 1)
        linha_captura.addWidget(self.lbl_ultima)
        linha_captura.addWidget(self.btn_gravar)
        linha_captura.addWidget(self.btn_capturar)
        self.grupo_captura.corpo.addLayout(linha_captura)
        self.grupo_captura.adicionar_parada(self.btn_gravar)
        self.grupo_captura.adicionar_parada(self.btn_capturar)
        barra_captura = QFrame()
        barra_captura.setObjectName("barraCaptura")
        caixa_barra = QHBoxLayout(barra_captura)
        caixa_barra.setContentsMargins(8, 4, 8, 4)
        caixa_barra.addWidget(self.grupo_captura)
        self._atualizar_destino()

        centro = QWidget()
        coluna_centro = QVBoxLayout(centro)
        coluna_centro.setContentsMargins(0, 0, 0, 0)
        coluna_centro.setSpacing(0)
        coluna_centro.addWidget(self.preview, 1)
        coluna_centro.addWidget(barra_captura)

        # --- painel direito: controles ------------------------------------------
        self.painel_controles = PainelControles()
        self.painel_controles.setObjectName("painelDireito")
        # subclasse de QWidget só pinta o fundo do QSS com este atributo
        self.painel_controles.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # largura mínima do painel de controles: ele mesmo mede a grade (varia por câmera)

        divisor = QSplitter()
        divisor.setChildrenCollapsible(False)  # ocultar é pelos botões; arrastar até zero confundia o estado
        divisor.addWidget(self.painel_esquerdo)
        divisor.addWidget(centro)
        divisor.addWidget(self.painel_controles)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([280, 900, 380])
        self.setCentralWidget(divisor)

        self._montar_barra_topo()
        self.statusBar().addPermanentWidget(QLabel(
            "Tab: grupos · Tab Tab: entrar · Esc: sair · W/S: ajustar · X: marcar · R: padrão · "
            "Ctrl+R: gravar · Ctrl+1/2: painéis · Ctrl+F: foco"))
        # Esc: dentro de um grupo sai dele; fora, sai do modo Foco (não há QShortcut de Esc:
        # ele seria processado antes do filtro e o "sair do grupo" nunca aconteceria)
        self.navegador = Navegador(self, self._grupos_navegacao,
                                   ao_esc_fora=lambda: self.acao_foco.setChecked(False))
        self.resize(1600, 820)

        self.atualizar_cameras()
        if erro_cfg:
            QMessageBox.warning(
                self, "Configuração inválida",
                f"{erro_cfg}\n\nUsando os padrões nesta sessão. O arquivo NÃO será alterado até você salvar em Configurações.",
            )

    # --- barra superior e painéis ---------------------------------------------
    def _montar_barra_topo(self) -> None:
        barra = QToolBar("Barra principal")
        barra.setObjectName("barraTopo")
        barra.setMovable(False)
        barra.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)  # o menu padrão permite sumir com a barra

        self.acao_cameras = self._acao_alternavel("Câmeras", "Ctrl+1", "Mostrar/ocultar o painel de câmeras")
        self.acao_cameras.toggled.connect(lambda v: self._mostrar_painel(self.painel_esquerdo, v))
        self.acao_controles = self._acao_alternavel("Controles", "Ctrl+2", "Mostrar/ocultar o painel de controles")
        self.acao_controles.toggled.connect(lambda v: self._mostrar_painel(self.painel_controles, v))
        self.acao_foco = self._acao_alternavel("Foco", "Ctrl+F", "Oculta os dois painéis (Esc sai)", ligada=False)
        self.acao_foco.toggled.connect(self._alternar_foco)
        acao_config = QAction("Configurações…", self)
        acao_config.setToolTip("Configurações de armazenamento")
        acao_config.triggered.connect(self.abrir_config)

        nome = QLabel("sdk-cam")
        nome.setObjectName("nomeApp")
        self.lbl_camera = QLabel()
        self.lbl_camera.setObjectName("chipCamera")
        self.lbl_status_modo = QLabel("parado")
        self.lbl_status_modo.setObjectName("statusModo")
        self.lbl_status_fps = QLabel()
        self.lbl_status_fps.setObjectName("statusFps")

        barra.addAction(self.acao_cameras)
        barra.addWidget(nome)
        barra.addWidget(self.lbl_camera)
        barra.addWidget(self._espaco())
        barra.addWidget(self.lbl_status_modo)
        barra.addWidget(self.lbl_status_fps)
        self.lbl_rec = QLabel()
        self.lbl_rec.setObjectName("lblRec")
        # widget dentro de QToolBar: mostrar/ocultar pela AÇÃO que o addWidget devolve;
        # show()/hide() no próprio widget não funciona (ele nem é posicionado)
        self._acao_rec = barra.addWidget(self.lbl_rec)
        self._acao_rec.setVisible(False)
        self._timer_rec = QTimer(self)
        self._timer_rec.setInterval(INTERVALO_REC_MS)
        self._timer_rec.timeout.connect(self._atualizar_rec)
        barra.addWidget(self._espaco())
        barra.addAction(self.acao_foco)
        barra.addAction(self.acao_controles)
        barra.addAction(acao_config)
        self.addToolBar(barra)

    def _grupos_navegacao(self) -> list[GrupoNavegavel]:
        """Ordem do Tab entre grupos: esquerda, captura, controles (ocultos são pulados)."""
        return [self.grupo_cameras, self.grupo_modo, self.grupo_captura, *self.painel_controles.grupos()]

    def _acao_alternavel(self, texto: str, atalho: str, dica: str, ligada: bool = True) -> QAction:
        acao = QAction(texto, self)
        acao.setCheckable(True)
        acao.setChecked(ligada)
        acao.setShortcut(QKeySequence(atalho))
        acao.setToolTip(f"{dica} — {atalho}")
        return acao

    @staticmethod
    def _espaco() -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return w

    def _mostrar_painel(self, painel: QWidget, visivel: bool) -> None:
        painel.setVisible(visivel)
        if visivel and self.acao_foco.isChecked():
            # abrir um painel durante o foco encerra o foco sem reabrir o outro
            self._antes_foco = None
            self.acao_foco.blockSignals(True)
            self.acao_foco.setChecked(False)
            self.acao_foco.blockSignals(False)

    def _paineis_visiveis(self) -> tuple[bool, bool]:
        return self.acao_cameras.isChecked(), self.acao_controles.isChecked()

    def _definir_paineis(self, esquerdo: bool, direito: bool) -> None:
        self.acao_cameras.setChecked(esquerdo)  # toggled -> _mostrar_painel
        self.acao_controles.setChecked(direito)

    def _alternar_foco(self, ligado: bool) -> None:
        if ligado:
            self._antes_foco = self._paineis_visiveis()
            self._definir_paineis(False, False)
            return
        anterior, self._antes_foco = self._antes_foco, None
        if anterior is None or not any(anterior):
            anterior = (True, True)  # entrou no foco com tudo já oculto: sair mostra os dois
        self._definir_paineis(*anterior)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        compacta = self.width() < LARGURA_COMPACTA
        if compacta == self._compacta:
            return  # só age ao CRUZAR o limite; dentro do modo, os botões continuam valendo
        self._compacta = compacta
        if compacta:
            self._antes_compacta = self._paineis_visiveis()
            self._definir_paineis(False, False)
        else:
            anterior, self._antes_compacta = self._antes_compacta, None
            if anterior is not None and not self.acao_foco.isChecked():
                self._definir_paineis(*anterior)

    def _marcar_ao_vivo(self, sim: bool) -> None:
        self.lbl_status_modo.setProperty("aoVivo", sim)
        # propriedade dinâmica não reaplica o QSS sozinha
        self.lbl_status_modo.style().unpolish(self.lbl_status_modo)
        self.lbl_status_modo.style().polish(self.lbl_status_modo)

    # --- configuração e captura ----------------------------------------------
    def _carregar_config(self) -> tuple[ConfigArmazenamento, str | None]:
        try:
            return carregar_secao(self.caminho_config, SECAO_CONFIG, ConfigArmazenamento), None
        except ErroConfig as e:
            return ConfigArmazenamento(), str(e)

    def _carregar_config_gravacao(self) -> tuple[ConfigGravacao, str | None]:
        try:
            return carregar_secao(self.caminho_config, SECAO_GRAVACAO, ConfigGravacao), None
        except ErroConfig as e:
            return ConfigGravacao(), str(e)

    def _atualizar_destino(self) -> None:
        fmt = self.cfg.formato + (f" q{self.cfg.qualidade_jpg}" if self.cfg.formato == "jpg" else "")
        g = self.cfg_grav
        video = f"{g.formato} " + ("mjpeg" if g.formato == "mkv" else g.codificador)
        texto = f"{diretorio_destino(self.cfg)}  ·  foto {fmt}  ·  vídeo {video}"
        self.lbl_destino.setText(texto)
        self.lbl_destino.setToolTip(texto)

    def abrir_config(self) -> None:
        dialogo = JanelaConfig(self.cfg, self.caminho_config, self, cfg_grav=self.cfg_grav)
        if dialogo.exec() == JanelaConfig.DialogCode.Accepted:
            self.cfg = dialogo.config()
            self.cfg_grav = dialogo.config_gravacao()  # vale para a PRÓXIMA gravação
            salvar_secao(self.caminho_config, SECAO_CONFIG, self.cfg)
            salvar_secao(self.caminho_config, SECAO_GRAVACAO, self.cfg_grav)
            self._atualizar_destino()

    def capturar(self) -> Path | None:
        cam, frame = self.camera_atual(), self.ultimo_frame
        if not self.btn_capturar.isEnabled() or cam is None or frame is None or self._thread is None:
            return None
        meta = self._metadados(cam)
        try:
            caminho = salvar_captura(frame, meta, self.cfg)
        except (ErroArmazenamento, OSError) as e:
            QMessageBox.critical(self, "Falha ao salvar", str(e))
            return None
        self.statusBar().showMessage(f"salvo: {caminho}", 5000)
        self.lbl_ultima.setText(f"última: {caminho.name}")
        self.lbl_ultima.setToolTip(str(caminho))
        return caminho

    def _metadados(self, cam: Camera) -> MetadadosCaptura:
        return MetadadosCaptura(
            camera_nome=cam.nome,
            camera_caminho=str(cam.caminho),
            camera_caminho_estavel=str(cam.caminho_estavel) if cam.caminho_estavel else None,
            camera_driver=cam.driver,
            camera_barramento=cam.barramento,
            modo_pedido=self._thread.modo,
            modo_negociado=self._negociado,
            controles=tuple(self.painel_controles.estado_atual()),
        )

    # --- gravação de vídeo ------------------------------------------------------
    @property
    def rec_visivel(self) -> bool:
        return self._acao_rec.isVisible()

    @property
    def gravando(self) -> bool:
        return self._gravador is not None

    def alternar_gravacao(self) -> None:
        if self.gravando:
            self.parar_gravacao()
        elif self.btn_gravar.isEnabled():
            self.iniciar_gravacao()

    def iniciar_gravacao(self) -> Path | None:
        cam = self.camera_atual()
        if self.gravando or cam is None or self._thread is None or self._negociado is None:
            return None
        meta = self._metadados(cam)
        try:
            g = iniciar_gravacao(self.cfg, self.cfg_grav, meta)
        except (ErroGravacao, ErroArmazenamento, OSError) as e:
            QMessageBox.critical(self, "Falha ao iniciar gravação", str(e))
            return None
        self._gravador, self._grav_contexto = g, (self.cfg, meta)
        self._marcar_gravando(True)
        self._atualizar_rec()
        self._timer_rec.start()
        return g.destino

    def parar_gravacao(self) -> None:
        """Encerra a gravação. O fechamento do arquivo (ffmpeg + faststart) roda numa thread:
        num vídeo longo o +faststart reescreve o arquivo inteiro e travaria a GUI."""
        g, ctx = self._gravador, self._grav_contexto
        if g is None:
            return
        self._gravador = self._grav_contexto = None
        self._timer_rec.stop()
        self._marcar_gravando(False)
        self.lbl_rec.setText("salvando vídeo…")
        self._acao_rec.setVisible(True)

        def finalizar() -> None:
            try:
                arquivo = finalizar_com_sidecar(g, *ctx)
            except (ErroGravacao, OSError) as e:
                self._sinais_grav.finalizada.emit(None, str(e))
                return
            self._sinais_grav.finalizada.emit(arquivo, None)

        t = threading.Thread(target=finalizar, name="finaliza-video")
        self._finalizacoes.append(t)
        t.start()

    def _ao_finalizar_gravacao(self, arquivo, erro) -> None:
        self._finalizacoes = [t for t in self._finalizacoes if t.is_alive()]
        if not self.gravando:
            self._acao_rec.setVisible(False)
        if erro:
            QMessageBox.critical(self, "Falha na gravação", erro)
            return
        self.statusBar().showMessage(f"vídeo salvo: {arquivo}", 8000)
        self.lbl_ultima.setText(f"última: {arquivo.name}")
        self.lbl_ultima.setToolTip(str(arquivo))

    def _abortar_gravacao(self, motivo: str) -> None:
        """ffmpeg morreu no meio: não há o que salvar; descarta e avisa."""
        g, self._gravador, self._grav_contexto = self._gravador, None, None
        self._timer_rec.stop()
        self._marcar_gravando(False)
        self._acao_rec.setVisible(False)
        if g is not None:
            g.cancelar()
        QMessageBox.critical(self, "Gravação interrompida", motivo)

    def _atualizar_rec(self) -> None:
        g = self._gravador
        if g is None:
            return
        est = g.estatisticas()
        seg = int(time.monotonic() - g.t_inicio)
        texto = f"● REC {seg // 60:02d}:{seg % 60:02d}"
        if est.descartados_fila:
            texto += f" · {est.descartados_fila} descartados"
        self.lbl_rec.setText(texto)
        self.lbl_rec.setToolTip(f"{g.destino}\nrecebidos {est.recebidos} · gravados {est.escritos} · "
                                f"repetidos {est.repetidos} (câmera abaixo da taxa) · descartados {est.descartados_fila} (fila cheia)")
        self._acao_rec.setVisible(True)

    def _marcar_gravando(self, sim: bool) -> None:
        self.btn_gravar.setText("Parar  [Ctrl+R]" if sim else "Gravar  [Ctrl+R]")
        self.btn_gravar.setProperty("gravando", sim)
        self.btn_gravar.style().unpolish(self.btn_gravar)
        self.btn_gravar.style().polish(self.btn_gravar)

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
            self.lbl_camera.setText(f"{cam.nome}  ·  {cam.caminho}")
            self.lbl_info.setText(
                f"<b>{cam.nome}</b><br>driver: {cam.driver}<br>barramento: {cam.barramento}<br>"
                f"estável: {cam.caminho_estavel or '(sem by-id)'}"
            )
        else:
            self.lbl_camera.setText("nenhuma câmera")
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
        self._marcar_ao_vivo(True)

    def _ao_frame(self, imagem, frame, instante: float) -> None:
        self.ultimo_frame = frame
        self.preview.mostrar(imagem)
        if self._gravador is not None:
            try:
                self._gravador.escrever(frame, instante)
            except ErroGravacao as e:
                self._abortar_gravacao(str(e))
        if not self.btn_capturar.isEnabled():
            self.btn_capturar.setEnabled(True)  # só com frame do stream ATUAL
            self.btn_gravar.setEnabled(True)

    def _ao_erro(self, mensagem: str) -> None:
        QMessageBox.critical(self, "Erro de captura", mensagem)

    def _ao_terminar(self) -> None:
        # stream acabou (parar, troca de câmera, erro): fecha o vídeo com o que foi gravado
        self.parar_gravacao()
        # descarta o frame antigo: não pode ser salvo depois com metadados de outra câmera/modo
        self.ultimo_frame = None
        self._negociado = None
        self.btn_capturar.setEnabled(False)
        self.btn_gravar.setEnabled(False)
        self._habilitar_edicao(True)
        self.btn_abrir.setEnabled(self.camera_atual() is not None)
        self.lbl_status_modo.setText("parado")
        self._marcar_ao_vivo(False)
        self.lbl_status_fps.clear()

    def closeEvent(self, evento) -> None:
        self.parar()  # também encerra a gravação
        # espera explícita pelo fechamento dos vídeos: sair antes deixaria um .tmp sem índice
        for t in self._finalizacoes:
            t.join(TEMPO_MAX_FINALIZAR_S + 5)
            if t.is_alive():
                QMessageBox.warning(self, "Gravação", "O vídeo ainda não terminou de ser salvo; o arquivo pode ficar incompleto.")
        self.painel_controles.fechar()
        super().closeEvent(evento)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gerenciador de câmeras V4L2")
    ap.add_argument("--config", type=Path, default=ARQUIVO_CONFIG, help=f"arquivo TOML (padrão: {ARQUIVO_CONFIG})")
    args, resto_qt = ap.parse_known_args()
    app = QApplication([sys.argv[0], *resto_qt])
    aplicar_tema(app)
    janela = JanelaPrincipal(args.config.expanduser().resolve())
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
