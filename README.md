# sdkEldenGinner

Kit de ferramentas para visão computacional e IA embarcada em Linux. A primeira ferramenta é o
**sdk-cam**, um gerenciador de câmeras V4L2 com interface gráfica (PySide6) e comandos de terminal.

## O que faz

- **Lista câmeras, modos e controles** exatamente como o driver anuncia (nada de lista fixa de parâmetros).
- **Abre a câmera num modo explícito** (formato → resolução → FPS) e **confere o que o driver negociou**: modo
  inexistente vira erro, em vez de ser trocado em silêncio pelo driver.
- **Painel de controles gerado do driver**, agrupado (Imagem, Exposição e ganho, Cor, Foco e enquadramento,
  Outros), com marca "≠ padrão", restaurar padrão e aviso de controle inativo (ex.: exposição em automático).
- **Fotos** PNG ou JPG, cada uma com um **JSON ao lado** (câmera, modo pedido/negociado, controles no instante).
- **Vídeo** MP4 (H.264 via libx264 ou NVENC) ou MKV (MJPG), pelo ffmpeg do sistema. A **duração é real** mesmo
  quando a câmera entrega menos FPS que o negociado (frames repetidos para cobrir os buracos).
- **Modo rajada**: fotos automáticas a cada N segundos, até uma quantidade ou até parar.
- **Navegação completa por teclado** e tema escuro.

## Requisitos

- Linux com V4L2 (testado no Ubuntu 26.04, câmeras UVC).
- Python 3.12 (validado no 3.12.3).
- `ffmpeg` em `/usr/bin/ffmpeg` (só para gravar vídeo; fotos e rajada funcionam sem ele).
- Debian/Ubuntu: `sudo apt install ffmpeg v4l-utils libxcb-cursor0 libegl1 libgl1 libxkbcommon0`.
- Acesso a `/dev/video*`: no desktop costuma vir da sessão gráfica; por SSH ou sem sessão gráfica, o usuário
  precisa estar no grupo `video` (`sudo usermod -aG video $USER` e entrar de novo).

## Instalação

```bash
git clone https://github.com/EldenGineer/sdkEldenGinner.git
cd sdkEldenGinner
scripts/instalar.sh                # com pyenv: virtualenv "sdkEldenGinner" (Python 3.12.3)
scripts/instalar.sh --venv local   # sem pyenv: cria .venv/ no repositório
```

O script checa o sistema, cria o ambiente, instala as versões exatas do `requirements.lock`, confere a
instalação e roda os testes sem hardware. Ele **nunca usa sudo**: se faltar algo, imprime o comando.
Pode rodar de novo à vontade (não refaz o que já está pronto).

| Opção | Efeito |
|---|---|
| `--simular` | mostra os passos sem executar nada |
| `--atalho` | cria a entrada `sdk-cam` no menu de aplicativos |
| `--sem-testes` | pula os testes no final |

> Use `opencv-python-headless`, nunca o `opencv-python` comum: ele traz plugins Qt que conflitam com o
> PySide6. O script barra esse caso.

## Uso

### Interface gráfica

```bash
sdk-cam                       # config em ~/.config/sdk_elden/camera.toml
sdk-cam --config outra.toml
```

Escolha a câmera, o formato, a resolução e o FPS, clique em **Abrir** e use a barra de captura:
foto, vídeo ou rajada.

#### Atalhos

| Tecla | Ação |
|---|---|
| **Espaço** | captura uma foto (vale com o foco em qualquer lugar) |
| Ctrl+R | inicia/para a gravação de vídeo |
| Ctrl+B | inicia/para a rajada |
| Ctrl+1 / Ctrl+2 | mostra/oculta o painel de câmeras / de controles |
| Ctrl+F | modo foco (oculta os dois painéis); Esc sai |
| Tab | próximo grupo (Câmeras, Modo, Captura, grupos de controles) |
| Tab Tab | entra no grupo |
| Tab / Shift+Tab (dentro do grupo) | próximo / anterior |
| Esc | sai do grupo |
| W / S | igual a ↑ / ↓ (números, menus, lista de câmeras) |
| X | marca/desmarca caixa |
| Enter | aciona o botão em foco |
| R | restaura o padrão do controle em foco |

Os atalhos de cada controle também aparecem no tooltip. Abaixo de 1200 px de largura, os painéis se ocultam
sozinhos (e voltam ao alargar a janela).

### Terminal

```bash
sdk-cam-listar                                   # câmeras, modos e controles

# abre num modo explícito e mede o FPS real
sdk-cam-capturar /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30

# grava 10 s de vídeo
sdk-cam-gravar /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30 --segundos 10
sdk-cam-gravar ... --formato mkv              # MKV MJPG
sdk-cam-gravar ... --codificador h264_nvenc   # GPU NVIDIA

# rajada: 1 foto a cada 0,5 s, 20 fotos (--quantidade 0 = até Ctrl+C)
sdk-cam-rajada /dev/video2 --fourcc MJPG --largura 2560 --altura 1440 --fps 30 --intervalo 0.5 --quantidade 20
```

O dispositivo pode ser `/dev/videoN` ou o link estável em `/dev/v4l/by-id/...` (recomendado: não muda ao
reconectar a câmera).

## Arquivos gerados

Tudo vai para `<raiz>/<repo>/<subrepo>/` (padrão: `~/capturas/geral/sessao/`), com o nome
`AAAAMMDD_HHMMSS_mmm_<camera>_<LxA>` e um `.json` de mesmo nome ao lado:

```
20261119_143012_123_2k_usb_Camera_Redeagle_2560x1440.png
20261119_143012_123_2k_usb_Camera_Redeagle_2560x1440.json
```

O JSON traz a câmera (nome, caminho, link estável, driver, barramento), o modo pedido e o negociado e os
controles lidos no driver. Nas fotos da rajada há também um bloco `rajada` (id, índice, intervalo); nos
vídeos, `tipo: "video"`, a configuração de gravação e as estatísticas (frames recebidos, gravados, repetidos,
descartados, duração).

Nada é sobrescrito, e os arquivos são escritos de forma atômica (sem arquivo pela metade se o processo cair).

## Configuração

`~/.config/sdk_elden/camera.toml`, criado só quando você salva em **Configurações** na GUI. Seções e padrões:

```toml
[armazenamento]
raiz = "/home/<usuario>/capturas"   # caminho absoluto
repo = "geral"
subrepo = "sessao"
formato = "png"                     # png | jpg
qualidade_jpg = 95

[gravacao]
formato = "mp4"                     # mp4 (H.264) | mkv (MJPG)
codificador = "libx264"             # libx264 | h264_nvenc
qualidade_h264 = 23                 # CRF/CQ: menor = melhor e maior
qualidade_mjpeg = 3                 # 2 (melhor) a 31
ffmpeg = "/usr/bin/ffmpeg"

[rajada]
intervalo_s = 1.0                   # mínimo 0,05
quantidade = 10                     # 0 = até parar
```

Config inválida não é sobrescrita: a GUI avisa e usa os padrões só naquela sessão.

## Desenvolvimento

```bash
pytest                       # tudo (os testes "hardware" usam câmeras reais)
pytest -m "not hardware"     # só os que não precisam de câmera
```

- Os testes de GUI rodam sem tela (plugin Qt `offscreen`).
- Testes de hardware alteram controles reais da câmera e **restauram os valores originais** no final.
- Feche o `sdk-cam` antes dos testes de hardware: uma câmera só aceita um stream por vez.
- Dependências fixadas em `requirements.lock`; decisões de projeto e armadilhas conhecidas em `CLAUDE.md`.

```
src/sdk_elden/
├── camera/
│   ├── dispositivos.py    # enumeração V4L2 (modos, controles)
│   ├── controles.py       # leitura/escrita validada de controles
│   ├── captura.py         # stream com negociação conferida
│   ├── armazenamento.py   # fotos + JSON
│   ├── gravacao.py        # vídeo via ffmpeg
│   ├── rajada.py          # agenda do modo rajada
│   └── gui/               # janela, painéis, tema, navegação por teclado
└── utils/
    ├── config.py          # TOML <-> dataclass
    └── fila_trabalho.py   # trabalho em segundo plano sem travar quem chama
```

## Limitações conhecidas

- Testado com duas câmeras UVC (uma webcam integrada e uma câmera USB 2K). Outros drivers podem anunciar
  controles ou formatos que ainda não foram exercitados.
- Algumas câmeras reduzem o FPS sozinhas com pouca luz ou em uso contínuo. Numa delas, a causa de quedas para
  15 fps em exposição manual **ainda não foi identificada**. A gravação mantém a duração real mesmo assim.
- Fotos PNG em 2560×1440 levam ~65 ms cada: a rajada aguenta ~15 fotos/s em PNG. Para mais que isso, use JPG.
- Segurar o Espaço tira uma foto só (a repetição do teclado é ignorada); para sequência, use a rajada.
- No Wayland, a posição da janela é decidida pelo compositor.

## Licença

Ainda não definida.
