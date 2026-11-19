# sdkEldenGinner

Kit de ferramentas pessoal do Eduardo (visão computacional / IA embarcada). Cada ferramenta vira um subpacote de `src/sdk_elden/`.

## Ambiente
- Python 3.12.3, venv pyenv **`sdkEldenGinner`** (definido em `.python-version`)
- Pacote instalado em modo editável: `pip install -e .`
- Dependências: `pyproject.toml`; versões fixadas em `requirements.lock` (`pip freeze`)

## Stack (decidida em 2026-11-19)
| Função | Ferramenta | Nota |
|---|---|---|
| GUI | PySide6 | |
| Captura de frames | opencv-python-headless (`cv2.CAP_V4L2`) | **headless obrigatório**: o opencv-python normal conflita com os plugins Qt do PySide6 |
| Enumeração/controles V4L2 | linuxpy, **somente a camada de baixo nível** | ver "Armadilhas" |
| Config | TOML (`tomllib` + `tomli-w`) | |
| Testes | pytest | marker `hardware` para testes com câmera real |
| Gravação de vídeo | ffmpeg do sistema (`/usr/bin/ffmpeg`, via subprocess) | decidido em 2026-11-19: o opencv-python-headless NÃO tem H.264. Formatos: MP4 H.264 (libx264 padrão, ou h264_nvenc) e MKV MJPG |

Decisão: manter Python, sem C++/Qt6 nativo. O núcleo V4L2 pode virar módulo C++ no futuro, se for rodar dentro de placas embarcadas.

## Comandos
- **Instalar em outra máquina**: `git clone ... && cd sdkEldenGinner && scripts/instalar.sh` (pyenv, padrão) ou `scripts/instalar.sh --venv local` (`.venv/` sem pyenv). `--simular` mostra os passos sem executar; `--atalho` cria a entrada do menu; `--sem-testes`. Idempotente. Nunca roda sudo: imprime `sudo apt install ...` / `sudo usermod -aG video $USER` quando falta algo.
- Testes: `pytest` (só os testes sem hardware: `pytest -m "not hardware"`)
- GUI: `sdk-cam`
- Testes de GUI sem tela: rodam no plugin Qt `offscreen` (definido em `tests/test_gui.py`). A mensagem "This plugin does not support propagateSizeHints()" é ruído desse plugin.
- Listar câmeras/modos/controles: `sdk-cam-listar`
- Rajada (fotos automáticas): `sdk-cam-rajada /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30 --intervalo 0.5 --quantidade 20 [--config arq.toml]` (`--quantidade 0` = até Ctrl+C; antes de reinstalar: `python -m sdk_elden.camera.rajada ...`)
- Gravar vídeo: `sdk-cam-gravar /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30 --segundos 5 [--formato mkv] [--codificador h264_nvenc] [--config arq.toml]` (enquanto o entry point não for reinstalado: `python -m sdk_elden.camera.gravacao ...`)
- Abrir num modo explícito e medir FPS real: `sdk-cam-capturar /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30`
- Depois de adicionar entry point no `pyproject.toml`: `pip install -e .` de novo
- Conferência manual: `v4l2-ctl -d /dev/videoN --list-formats-ext --list-ctrls`

## Configuração e capturas
- Config da ferramenta de câmera: `~/.config/sdk_elden/camera.toml`, seção `[armazenamento]` (caminho fixo; `sdk-cam --config <arq>` para outro). Criado só quando o usuário salva em "Configurações…".
- Padrões: raiz `~/capturas` (absoluto), repo `geral`, subrepo `sessao`, formato `png`, qualidade_jpg 95.
- Capturas: `raiz/<repo>/<subrepo>/<AAAAMMDD_HHMMSS_mmm>_<camera>_<LxA>.<png|jpg>` + `.json` com o mesmo nome (câmera, modo pedido/negociado, controles, horário com fuso).
- Config inválida: aviso na abertura, padrões só nesta sessão e o arquivo **não** é sobrescrito.
- Testes nunca tocam `~/.config` nem `~/capturas` reais (usam `tmp_path`).
- Vídeos: mesma pasta e mesmo padrão de nome das fotos, `.mp4`/`.mkv` + `.json` (`tipo: video`, config de gravação, câmera, controles, estatísticas). Seção `[gravacao]` no `camera.toml`: `formato` (mp4|mkv), `codificador` (libx264|h264_nvenc), `qualidade_h264` (CRF/CQ, 23), `qualidade_mjpeg` (q:v, 3), `ffmpeg` (caminho absoluto).

## Convenções
- Código, comentários e commits em pt-BR.
- Camera é identificada pelo link estável `/dev/v4l/by-id/...`, não por `/dev/videoN`.
- Controles da UI são gerados a partir do que o driver reporta, nunca de uma lista fixa de parâmetros.
- Formato → resolução → FPS, **nesta ordem**, e depois conferir o que o driver negociou (lição de `~/dev/mctech/testes_cam/camera_utils.py`).

## Armadilhas conhecidas
- **linuxpy 0.25.0 `Device.controls` quebra** quando um controle tem tipo fora do enum dele (ex.: `V4L2_CTRL_TYPE_RECT` 0x107 da webcam ACER). Usar `iter_read_controls`/`get_controls_values` com a lista explícita `TIPOS_SUPORTADOS` em `dispositivos.py`.
- linuxpy descarta formatos de pixel desconhecidos (só dá `log.warning`).
- Firmware da Redeagle anuncia modos duplicados (o agrupamento remove). O `auto_exposure` dela tem padrão=0, que não é um item válido do menu (quirk do firmware).
- uvcvideo devolve `EACCES` (errno 13) ao escrever em controle **inativo** (ex.: `exposure_time_absolute` com `auto_exposure` em automático). Para ajustar a exposição: antes `auto_exposure=1` (Manual Mode). `validar_valor` antecipa isso com mensagem clara.
- **Modo inexistente é trocado em silêncio pelo driver** (pedido 1234x567 → 1280x720, sem erro). Por isso `Captura` valida contra os modos anunciados antes de abrir e confere a negociação depois (`estrito=True` por padrão).
- ACER tem `exposure_dynamic_framerate=1`: com pouca luz o FPS real pode cair abaixo do negociado. Use `Captura.medir_fps()` para conferir.
- **Aquecimento após start do stream**: a Redeagle às vezes começa abaixo da taxa (ex.: 22 → 30 fps no 1º segundo), de forma intermitente. `medir_fps` descarta `FRAMES_AQUECIMENTO=30` antes de medir. O FPS da GUI (média móvel de 1 s) mostra esse transiente naturalmente.
- Unidade de `exposure_time_absolute` da Redeagle **não confirmada**: 1000 não derrubou o FPS (no padrão UVC seria 100 ms → ~10 fps). Não assumir a unidade sem medir.
- `cv2.imwrite` tem **dois** modos de falha: retorna `False` (ex.: diretório inexistente) ou lança `cv2.error` (ex.: imagem vazia). `armazenamento` converte os dois em `ErroArmazenamento`.
- Custo de salvar 2560x1440: PNG ~65 ms, JPG q95 ~8 ms. A foto manual é salva na thread da GUI (aceitável); a rajada salva numa `FilaTrabalho` (thread própria).
- **Rajada sustentada 2560x1440 a 20 fotos/s por 10 s** (2026-11-19): PNG salvou 176/200 (24 descartadas por fila cheia, CPU 128%, 580 MB, ~3,3 MB por foto); JPG q95 salvou 200/200 (CPU 52%, 88 MB). PNG aguenta ~15 fotos/s; para rajada rápida, usar JPG. Picos curtos (40 fotos em 2 s) cabem na fila de 16 sem descarte.
- Rajada guiada pela chegada dos frames: com intervalo de 0,05 s e câmera a 30 fps, os intervalos reais alternam entre 33 e 67 ms (média de 50 ms). É esperado; a precisão é de ~1 frame.
- Qt: `QLabel` com quebra de linha dentro de `QFormLayout` não recalcula a altura quando o texto muda (caminhos longos cortados). Deixar esses rótulos fora do form.
- Qt: ao remontar layouts, `takeAt()` não tira o widget da tela. Usar `hide()` antes do `deleteLater()`, senão sobram "fantasmas" até o loop de eventos rodar. **Não usar `setParent(None)`** (era a solução anterior): o widget vira janela de nível superior por um instante e, no plugin `offscreen`, isso **desativava a janela principal** a cada troca de câmera (foco de teclado perdido). Não confirmado se acontece no Wayland/X11 real; `hide()` evita o risco nos dois.
- Controles abertos (`ControlesCamera`) e stream do OpenCV coexistem, inclusive com troca de formato (verificado). Reler todos os controles custa ~0,4 ms.
- **Falha intermitente de `test_captura_real` — causa identificada (2026-11-19)**: `medir_fps` deu 15–18 fps (pedido 30) na Redeagle. O FPS acompanha a luz da cena (brilho médio ~100 → ~18 fps; ~125 → ~27 fps). Com `auto_exposure=3` (Aperture Priority), o firmware alonga o tempo de frame quando a cena está escura, e a Redeagle **não** tem `exposure_dynamic_framerate` para desligar isso. Em manual (`auto_exposure=1`), o FPS ficou em 30 com exposure 78/300/1000/3000. Conclusão: o teste dependia da iluminação do ambiente; não é bug da `Captura`. A fixture `exposicao_fixa` em `tests/test_captura.py` põe a câmera em manual (`EXPOSICAO_TESTE=78`) durante a medição e passou 15/15 rodadas. **Mas isso NÃO resolveu tudo**: mais tarde, 1 falha em 25 execuções da suíte (MJPG 2560×1440, 15,1 fps, já em manual).
- **Queda para 15 fps da Redeagle em exposição manual — causa NÃO identificada (2026-11-19).** Em 25 aberturas seguidas (MJPG 2560×1440, manual, exposure 78 confirmado após cada abertura), 13 ficaram abaixo de 24 fps, piorando com o tempo (as últimas 10 todas em 15,1). **Descartado**: decodificação MJPG (sem decodificar, com `CONVERT_RGB=0` e `retrieve` de 0,1 ms, também deu 15,1; decodificando custa ~6 ms) e disputa de banda com a ACER (mesmo barramento USB 2.0 de 480 Mb/s, mas a ACER não transmite nos testes). Exatamente metade da taxa indica que a câmera passa a entregar 1 frame a cada 2. Hipóteses não testadas: aquecimento/limitação do firmware em uso contínuo, reserva de banda isócrona do UVC. Próximo passo: medir com `usbmon` ou intervalos entre frames por timestamp do buffer V4L2, e testar após a câmera esfriar.
- Redeagle: `gain` estava em 200 (padrão 0) e não muda com a luz, ou seja, não é ganho automático. Origem não confirmada (talvez um ajuste feito pela GUI).
- Bash com `set -o pipefail`: `cmd | grep -q padrão` falha com rc 141 (SIGPIPE) quando o grep acha a linha e sai antes de `cmd` terminar de escrever (reproduzido com `pyenv versions --bare`, 3.12.3 na linha 11 de 24). Capturar a saída numa variável e usar `grep -q ... <<<"$var"`.
- Acesso a `/dev/video*` no desktop vem por ACL da sessão (o `+` em `crw-rw----+`), não do grupo `video` (o usuário não está nele). Por SSH/sem sessão gráfica, só o grupo `video` dá acesso; `instalar.sh` testa leitura+escrita de fato.
- Testes de hardware alteram controles reais da câmera e **restauram os originais** em `finally`.
- Cada câmera UVC expõe 2 nós (captura + metadados). Filtrar por capability `VIDEO_CAPTURE`.
- Wayland: posicionamento de janela é ignorado pelo compositor.
- Qt: um `QShortcut` é processado **antes** de um event filter de KeyPress. Por isso não há `QShortcut` de Esc: o `Navegador` trata o Esc (sai do grupo; fora de grupo, sai do Foco).
- Qt: `QComboBox` emite `activated` também ao trocar o item pelo teclado (↑/↓). O painel escreve no driver por esse sinal (verificado em `test_navegacao.py`).
- Qt: Shift+Tab chega como `Key_Backtab` pela plataforma, mas como `Key_Tab` + Shift em eventos sintéticos (`QTest`). O filtro aceita os dois.
- Testes de GUI: sem tela, um `QMessageBox` modal espera um clique para sempre. Teste que pode abrir um deve trocá-lo por `pytest.fail` (a suíte travava quando a câmera estava ocupada pelo `sdk-cam` aberto).
- Câmera ocupada por outro processo (ex.: `sdk-cam` aberto) faz os testes `hardware` falharem com "em uso por outro processo?". Fechar o `sdk-cam` antes de `pytest`.
- Qt: o `QSplitter` **ignora mudanças de `minimumSizeHint`** de um filho já montado (nem `setSizes` reaplica). Só respeita `setMinimumWidth` explícito. Por isso `PainelControles._ajustar_largura` fixa o mínimo do próprio painel.
- Qt: widgets recém-criados dentro de um pai **já visível** ficam ocultos até o loop de eventos rodar, e o Qt ignora ocultos no `minimumSizeHint` (medido na hora dava 32 px). Medir de novo com `QTimer.singleShot(0, ...)`.
- Qt: o `QScrollArea` não repassa ao layout a largura do conteúdo. Sem rolagem horizontal e sem mínimo medido, a grade é cortada.
- QSS: um seletor de descendente com id (`#painel QWidget`) vence `QPushButton` por especificidade e repinta botões e listas. Pôr fundo só nos contêineres, por objectName.
- QSS: propriedade dinâmica (`[aoVivo="true"]`) só reaplica com `unpolish`/`polish`.
- QSS: fundo em subclasse de `QWidget` exige `WA_StyledBackground`.
- **`QTest.qWait` segura o GIL** (PySide6): uma QThread em Python (ex.: `ThreadCaptura`) quase não roda enquanto o script principal espera com ele (0 frames em 3 s, contra 81 com `time.sleep` + `processEvents`). Nos testes/scripts com câmera, esperar com `time.sleep` + `app.processEvents()`. O app real (`app.exec()`) não tem o problema.
- Qt: widget dentro de `QToolBar` aparece/some pela **QAction devolvida por `addWidget`** (`setVisible`); `show()`/`hide()` no widget não funciona (fica sem geometria). Janela nunca mostrada (`show()`) também não diagrama a barra.
- Rajada: o horário da foto (nome e sidecar) é o da **chegada do frame**, não o do enfileiramento. Com `datetime.now()` no enfileiramento, frames processados em sequência rápida colidiam no mesmo milissegundo do nome e o salvamento recusava ("já existe").
- Barra de captura: destino e "última" ficam na coluna flexível (`QSizePolicy.Ignored`); senão, com rajada/gravar/capturar, o caminho de destino era cortado.
- O instante de cada frame é tomado na `ThreadCaptura`, logo após `ler()` (sinal `novo_frame(QImage, frame, instante)`): tomado na GUI, o atraso da fila de eventos viraria buraco/repetição no vídeo.
- Fechar o vídeo (ffmpeg + `+faststart`, que reescreve o arquivo inteiro) roda numa thread; o `closeEvent` espera explicitamente (`TEMPO_MAX_FINALIZAR_S` + 5 s) para não deixar `.tmp` sem índice.
- opencv-python-headless 5.1: `VideoWriter` grava MJPG/XVID/mp4v/FFV1, mas **não** avc1/H264/X264 (testado). Por isso a gravação usa o ffmpeg do sistema.
- Gravação a taxa fixa com câmera instável: `RelogioCFR` repete ou descarta frames pelo horário de chegada, para o vídeo manter a duração real (sem isso, 15 fps reais gravados como 30 tocariam 2x mais rápido).
- O vídeo começa no 1º frame, que chega ~0,2 s depois de abrir o stream: gravar "5 s" dá ~4,8 s de vídeo (correto). Testes de duração comparam com o intervalo entre o 1º e o último frame.
- Velocidade de codificação 2560×1440 (10 s de `testsrc2`, 2026-11-19): libx264 veryfast 1,6 s; h264_nvenc 1,9 s; libx264 ultrafast 0,8 s; mjpeg 0,8 s. Câmera real, 5 s: libx264 16 MB, nvenc 15 MB, MKV MJPG 30 MB, 0 frames descartados.

## Hardware de teste (máquina do Eduardo)
- `/dev/video0`: ACER HD User Facing (uvcvideo), MJPG/YUYV até 1280x720
- `/dev/video2`: XC-TECH 2k usb Camera Redeagle (uvcvideo), MJPG até 2560x1440@30

## Roadmap — gerenciador de câmeras (uma peça por vez)
1. [x] Esqueleto + `camera/dispositivos.py` + CLI `sdk-cam-listar`
2. [x] `camera/controles.py` (escrita de controles) + testes
3. [x] `camera/captura.py` (negociação + frames) + CLI `sdk-cam-capturar`
4. [x] GUI: janela principal + preview (`sdk-cam`)
5. [x] GUI: painel de controles dinâmico
6. [x] `utils/config.py` + `camera/armazenamento.py` (`raiz/<repo>/<subrepo>/` + sidecar JSON) + janela de config
7. [ ] Registrar no mapa do `~/dev`
8. [x] Redesign: tema cinza (QSS + Fusion), barra superior com Câmeras/Controles/Foco (Ctrl+1/2/F, Esc), modo compacto abaixo de 1200 px, barra de captura sob o preview. Mockup: https://claude.ai/artifact/31aSY5FT5zES6qQ6WD7MRL
9. [x] Painel de controles agrupado (tabela `GRUPOS` por nome + "Outros") com marca "≠ padrão"; setas ↑/↓ nos spinbox; navegação por teclado em toda a janela
10. [x] `camera/gravacao.py` (Gravador via ffmpeg, RelogioCFR, sidecar) + CLI `sdk-cam-gravar`
11. [x] GUI: botão Gravar (Ctrl+R), indicador ● REC na barra superior (tempo + descartes), opções de vídeo em Configurações
12. [x] `camera/rajada.py` (AgendaRajada, bloco `rajada` no sidecar) + `utils/fila_trabalho.py` + CLI `sdk-cam-rajada`
13. [x] GUI: modo rajada (Ctrl+B): intervalo/quantidade na barra de captura (sessão), padrões em Configurações, indicador ◉ RAJADA (contador, próxima, descartes), resumo ao terminar

## Inventário de reaproveitáveis
### Deploy
- `scripts/instalar.sh`: checa sistema (ffmpeg em `/usr/bin/ffmpeg`, pacotes apt, acesso às câmeras), cria o ambiente (pyenv `sdkEldenGinner` com Python 3.12.3, ou `.venv`), instala `requirements.lock` + o pacote (`--no-deps -e`), confere imports e o conflito opencv-python × PySide6, roda os testes sem hardware.

### Transversal (`sdk_elden.utils`)
- `utils.config.carregar_secao(caminho, secao, Dataclass)` / `salvar_secao(caminho, secao, obj)`: TOML ↔ dataclass, com checagem de chaves/tipos, escrita atômica, preservando outras seções. `ErroConfig`. `DIR_CONFIG = ~/.config/sdk_elden`.
- `utils.config.de_dict(Dataclass, dict)`: validação de dict → dataclass (campos str/int/float/bool).
- `utils.fila_trabalho.FilaTrabalho(funcao, tamanho, ao_concluir, ao_falhar)`: uma thread consumidora, FIFO, `enviar()` nunca bloqueia (fila cheia = `descartadas` += 1), `fechar(timeout)` termina o que está na fila. Callbacks rodam na thread consumidora (na GUI, emitir sinal).

### Câmera
- `sdk_elden.camera.dispositivos.listar_cameras()`: lista os nós V4L2 de captura com modos (formato/res/FPS) e controles.
- `sdk_elden.camera.dispositivos.ler_camera(caminho)`: idem para um nó específico.
- `sdk_elden.camera.dispositivos.mapa_by_id()`: `/dev/videoN` → link estável em `/dev/v4l/by-id`.
- `sdk_elden.camera.dispositivos.nome_config(nome)`: nome do driver → nome estilo v4l2-ctl.
- `sdk_elden.camera.dispositivos.iter_controles_brutos(dev)` / `info_controle(dev, ctrl)`: controles brutos → `InfoControle` (valor/padrão/flags lidos agora).
- `sdk_elden.camera.controles.ControlesCamera(caminho)`: sessão de controle (context manager) com `ler`, `escrever` (valida, escreve e relê), `info`, `todos`, `restaurar_padrao`.
- `sdk_elden.camera.controles.validar_valor(info, valor)`: validação pura (faixa, step, menu, bitmask, flags), sem I/O.
- `sdk_elden.camera.controles.ErroControle`: exceção única para recusa nossa ou do driver.
- `sdk_elden.camera.dispositivos.modos_anunciados(caminho)`: só os modos de um nó, sem ler controles.
- `sdk_elden.camera.captura.ModoCaptura`: formato + resolução + FPS pedidos/negociados.
- `sdk_elden.camera.captura.Captura(caminho, modo, buffers=2, estrito=True)`: stream com negociação validada, `ler()` (BGR), `medir_fps(n)`, context manager.
- `sdk_elden.camera.captura.validar_modo(modo, anunciados)` / `divergencias(pedido, negociado)`: checagens puras.
- `sdk_elden.camera.gui.preview.WidgetPreview`: desenha o QImage mais recente com letterbox (`mostrar`, `limpar`, `area_imagem`).
- `sdk_elden.camera.gui.thread_captura.ThreadCaptura(caminho, modo)`: QThread dona da `Captura`; sinais `aberta`, `novo_frame(QImage, ndarray BGR)`, `fps_medido`, `erro`; `parar()`.
- `sdk_elden.camera.gui.thread_captura.frame_para_qimage(frame)`: BGR → QImage (`Format_BGR888`, cópia independente).
- `sdk_elden.camera.gui.janela_principal.JanelaPrincipal`: janela principal; `ultimo_frame` guarda o último BGR recebido.
- `sdk_elden.camera.gui.painel_controles.PainelControles`: painel dinâmico (`definir_camera`, `reler`, `fechar`); relê todos os controles após cada escrita.
- `sdk_elden.camera.armazenamento.salvar_captura(frame, MetadadosCaptura, ConfigArmazenamento)`: grava imagem + sidecar JSON (atômico, nunca sobrescreve). Também: `validar_config`, `diretorio_destino`, `slug`, `ErroArmazenamento`.
- `sdk_elden.camera.gui.janela_config.JanelaConfig(cfg, caminho_arquivo)`: diálogo de raiz/repo/subrepo/formato com validação ao vivo; `subpastas(pasta)` sugere nomes existentes.
- `sdk_elden.camera.gui.tema`: paleta cinza (constantes `FUNDO`, `PAINEL`, `TEXTO`...), `QSS`, `paleta()`, `aplicar_tema(app)` (fixa o estilo Fusion). Cores por objectName (`btnCapturar`, `tituloSecao`, `painelEsquerdo`...).
- `JanelaPrincipal.acao_cameras` / `acao_controles` / `acao_foco`: QActions alternáveis dos painéis. Modo compacto: `LARGURA_COMPACTA=1200`, age só ao cruzar o limite e restaura o estado anterior.
- `sdk_elden.camera.gui.navegacao.GrupoNavegavel(titulo)` / `Navegador(janela, grupos, ao_esc_fora)`: navegação em dois níveis. Tab entre grupos (espera `JANELA_DUPLO_TAB_MS=250` para distinguir do duplo Tab, decisão do usuário), Tab Tab entra, Tab/Shift+Tab dentro, Esc sai, W/S = ↑/↓, X marca caixa, Enter aciona botão, R chama `restaurar()` do ancestral. Paradas registradas explicitamente (`adicionar_parada`). Só age na janela dona; letras em `QLineEdit` continuam texto.
- `sdk_elden.camera.gui.painel_controles.agrupar(infos)` / `GRUPOS` / `ORDEM_GRUPOS`: agrupamento por nome (controle fora da tabela vai para "Outros", nunca some). `atalhos(info)` / `descricao(info)`: textos do tooltip. Cada controle tem uma parada só (`EditorControle.entrada`); slider e ↺ ficam fora do Tab.
- `sdk_elden.camera.gui.tema.DIR_ICONES`: setas SVG (`icones/`, em package-data) usadas no QSS por caminho absoluto.
- `sdk_elden.camera.gravacao.Gravador(cfg, destino, largura, altura, fps, fila=8)`: `escrever(frame, t)` (não bloqueia; fila cheia = descarte contado), `finalizar()` (arquivo .tmp → final), `cancelar()`, `estatisticas()`, `erro`. `iniciar_gravacao(cfg_arm, cfg_grav, meta)` / `finalizar_com_sidecar(g, cfg_arm, meta)`. `RelogioCFR(fps).vezes(t)`, `montar_comando(...)`, `ConfigGravacao`, `ErroGravacao`.
- `sdk_elden.camera.armazenamento.nome_base(agora, camera_nome, l, a)` / `dados_camera(meta)` / `escrever_sidecar(destino, dados)`: partes comuns de foto e vídeo.
- `JanelaPrincipal.iniciar_gravacao()` / `parar_gravacao()` / `alternar_gravacao()` / `gravando` / `rec_visivel`: gravação na GUI; para sozinha ao parar o stream, trocar de câmera ou fechar a janela. `JanelaConfig(..., cfg_grav=)` + `config_gravacao()`: seção de vídeo.
- `sdk_elden.camera.rajada.AgendaRajada(ConfigRajada)`: `deve_capturar(t)` por frame que chega (agenda ancorada em t0, sem repetir frame, `perdidas` conta horários pulados), `terminou`, `proximo_em(t)`. `bloco_sidecar(id, indice, cfg)` / `id_rajada(agora, camera)`. `ConfigRajada(intervalo_s, quantidade)`, seção `[rajada]` no `camera.toml`, `INTERVALO_MIN_S=0.05`.
- `salvar_captura(..., extra=dict)`: campos extras no sidecar (recusa sobrescrever os padrão).
- `sdk_elden.camera.gui.controlador_rajada.ControladorRajada`: `iniciar(cfg_arm, cfg_rajada, camera_nome, meta=callable)`, `ao_frame(frame, instante)`, `parar()`, `texto_status()`, `fechar(timeout)`; sinais `foto_salva(Path)`, `falhou(str)`, `parou()`, `terminou(ResumoRajada)`. O horário de cada foto é o da chegada do frame (relógio de parede do 1º frame + delta monotônico).
- `sdk_elden.camera.gui.janela_config.campos_rajada()`: par (intervalo, quantidade) com os limites de `rajada.py`, usado na barra e em Configurações.
- `PainelControles.estado_atual()`: controles lidos agora (usado no sidecar).
- `sdk_elden.camera.gui.painel_controles.EditorControle(info, ao_escrever, ao_restaurar)`: widget de 1 controle conforme o tipo (slider+spin, checkbox, combo, hex); `atualizar(info)` sem disparar escrita.
