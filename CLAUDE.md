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

Decisão: manter Python, sem C++/Qt6 nativo. O núcleo V4L2 pode virar módulo C++ no futuro, se for rodar dentro de placas embarcadas.

## Comandos
- Testes: `pytest` (só os testes sem hardware: `pytest -m "not hardware"`)
- GUI: `sdk-cam`
- Testes de GUI sem tela: rodam no plugin Qt `offscreen` (definido em `tests/test_gui.py`). A mensagem "This plugin does not support propagateSizeHints()" é ruído desse plugin.
- Listar câmeras/modos/controles: `sdk-cam-listar`
- Abrir num modo explícito e medir FPS real: `sdk-cam-capturar /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30`
- Depois de adicionar entry point no `pyproject.toml`: `pip install -e .` de novo
- Conferência manual: `v4l2-ctl -d /dev/videoN --list-formats-ext --list-ctrls`

## Configuração e capturas
- Config da ferramenta de câmera: `~/.config/sdk_elden/camera.toml`, seção `[armazenamento]` (caminho fixo; `sdk-cam --config <arq>` para outro). Criado só quando o usuário salva em "Configurações…".
- Padrões: raiz `~/capturas` (absoluto), repo `geral`, subrepo `sessao`, formato `png`, qualidade_jpg 95.
- Capturas: `raiz/<repo>/<subrepo>/<AAAAMMDD_HHMMSS_mmm>_<camera>_<LxA>.<png|jpg>` + `.json` com o mesmo nome (câmera, modo pedido/negociado, controles, horário com fuso).
- Config inválida: aviso na abertura, padrões só nesta sessão e o arquivo **não** é sobrescrito.
- Testes nunca tocam `~/.config` nem `~/capturas` reais (usam `tmp_path`).

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
- Custo de salvar 2560x1440: PNG ~65 ms, JPG q95 ~8 ms. O salvamento é síncrono na thread da GUI (aceitável para captura manual; para rajada, mover para uma thread).
- Qt: `QLabel` com quebra de linha dentro de `QFormLayout` não recalcula a altura quando o texto muda (caminhos longos cortados). Deixar esses rótulos fora do form.
- Qt: ao remontar layouts, `takeAt()` não tira o widget da tela. É preciso `setParent(None)` antes do `deleteLater()`, senão sobram "fantasmas" até o loop de eventos rodar.
- Controles abertos (`ControlesCamera`) e stream do OpenCV coexistem, inclusive com troca de formato (verificado). Reler todos os controles custa ~0,4 ms.
- **Falha intermitente de `test_captura_real` — causa identificada (2026-11-19)**: `medir_fps` deu 15–18 fps (pedido 30) na Redeagle. O FPS acompanha a luz da cena (brilho médio ~100 → ~18 fps; ~125 → ~27 fps). Com `auto_exposure=3` (Aperture Priority), o firmware alonga o tempo de frame quando a cena está escura, e a Redeagle **não** tem `exposure_dynamic_framerate` para desligar isso. Em manual (`auto_exposure=1`), o FPS ficou em 30 com exposure 78/300/1000/3000. Conclusão: o teste depende da iluminação do ambiente; não é bug da `Captura`.
- Redeagle: `gain` estava em 200 (padrão 0) e não muda com a luz, ou seja, não é ganho automático. Origem não confirmada (talvez um ajuste feito pela GUI).
- Testes de hardware alteram controles reais da câmera e **restauram os originais** em `finally`.
- Cada câmera UVC expõe 2 nós (captura + metadados). Filtrar por capability `VIDEO_CAPTURE`.
- Wayland: posicionamento de janela é ignorado pelo compositor.

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

## Inventário de reaproveitáveis
### Transversal (`sdk_elden.utils`)
- `utils.config.carregar_secao(caminho, secao, Dataclass)` / `salvar_secao(caminho, secao, obj)`: TOML ↔ dataclass, com checagem de chaves/tipos, escrita atômica, preservando outras seções. `ErroConfig`. `DIR_CONFIG = ~/.config/sdk_elden`.
- `utils.config.de_dict(Dataclass, dict)`: validação de dict → dataclass (campos str/int/float/bool).

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
- `PainelControles.estado_atual()`: controles lidos agora (usado no sidecar).
- `sdk_elden.camera.gui.painel_controles.EditorControle(info, ao_escrever, ao_restaurar)`: widget de 1 controle conforme o tipo (slider+spin, checkbox, combo, hex); `atualizar(info)` sem disparar escrita.
