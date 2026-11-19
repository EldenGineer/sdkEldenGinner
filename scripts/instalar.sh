#!/usr/bin/env bash
# Instalação do sdkEldenGinner numa máquina nova (ou reinstalação; é idempotente).
#
#   git clone git@github.com:EldenGineer/sdkEldenGinner.git && cd sdkEldenGinner
#   scripts/instalar.sh                 # pyenv + virtualenv "sdkEldenGinner" (convenção do projeto)
#   scripts/instalar.sh --venv local    # sem pyenv: .venv/ dentro do repositório
#   scripts/instalar.sh --simular       # só mostra o que faria
#
# Regras (CLAUDE.md do projeto):
# - valores explícitos: versão do Python e nome do ambiente fixos aqui; o tipo de ambiente é
#   escolhido por opção, nunca "cai" sozinho de pyenv para venv;
# - versões das dependências vêm do requirements.lock (pip não resolve nada por conta própria);
# - nunca roda sudo: pacotes de sistema e grupo de usuário são só checados e o comando é impresso.
set -euo pipefail

PYTHON_VERSAO="3.12.3"
NOME_AMBIENTE="sdkEldenGinner"
FFMPEG="/usr/bin/ffmpeg"                                   # mesmo padrão de [gravacao] ffmpeg
PACOTES_APT=(ffmpeg v4l-utils libxcb-cursor0 libegl1 libgl1 libxkbcommon0)  # Debian/Ubuntu

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODO="pyenv"; SIMULAR=0; TESTES=1; ATALHO=0
AVISOS=()

uso() {
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    cat <<EOF

Opções:
  --venv pyenv|local   tipo de ambiente (padrão: pyenv)
  --sem-testes         não roda a suíte sem hardware no final
  --atalho             cria ~/.local/share/applications/sdk-cam.desktop
  --simular            mostra os passos sem executar nada
  -h, --help           esta ajuda
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv) MODO="${2:-}"; shift 2 ;;
        --sem-testes) TESTES=0; shift ;;
        --atalho) ATALHO=1; shift ;;
        --simular) SIMULAR=1; shift ;;
        -h|--help) uso; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; uso >&2; exit 2 ;;
    esac
done
[[ "$MODO" == "pyenv" || "$MODO" == "local" ]] || { echo "--venv deve ser 'pyenv' ou 'local', veio '$MODO'" >&2; exit 2; }

passo() { printf '\n==> %s\n' "$*"; }
ok()    { printf '    ok: %s\n' "$*"; }
aviso() { printf '    AVISO: %s\n' "$*"; AVISOS+=("$*"); }
erro()  { printf '\nERRO: %s\n' "$*" >&2; exit 1; }
rodar() {  # executa (ou só mostra, em --simular)
    printf '    $ %s\n' "$*"
    [[ $SIMULAR -eq 1 ]] || "$@"
}

# --- 1. sistema -----------------------------------------------------------------------------
passo "Sistema"
[[ "$(uname -s)" == "Linux" ]] || erro "só Linux (V4L2). Sistema: $(uname -s)"
ok "Linux $(uname -r)"

if [[ -x "$FFMPEG" ]]; then
    ok "ffmpeg em $FFMPEG"
else
    aviso "ffmpeg não encontrado em $FFMPEG: gravação de vídeo não funciona (fotos e rajada sim). Ajuste [gravacao] ffmpeg se estiver em outro lugar."
fi
command -v v4l2-ctl >/dev/null && ok "v4l2-ctl (conferência manual de câmeras)" \
    || aviso "v4l2-ctl ausente (opcional, só para conferência manual)"

if command -v dpkg >/dev/null; then
    faltando=()
    for p in "${PACOTES_APT[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || faltando+=("$p"); done
    if [[ ${#faltando[@]} -eq 0 ]]; then
        ok "pacotes do sistema: ${PACOTES_APT[*]}"
    else
        aviso "pacotes faltando: ${faltando[*]}. Rode: sudo apt install ${faltando[*]}"
    fi
else
    aviso "sem dpkg (distro não Debian/Ubuntu): confira à mão o equivalente de: ${PACOTES_APT[*]}"
fi

# --- 2. ambiente Python ---------------------------------------------------------------------
passo "Ambiente Python ($MODO, Python $PYTHON_VERSAO)"
if [[ "$MODO" == "pyenv" ]]; then
    command -v pyenv >/dev/null || erro "pyenv não encontrado. Instale o pyenv + pyenv-virtualenv, ou use --venv local."
    # saída capturada ANTES do grep: com pipefail, um pipe para "grep -q" falha (rc 141) quando o
    # grep acha a linha e sai antes de o pyenv terminar de escrever (SIGPIPE). Reproduzido aqui:
    # 3.12.3 na linha 11 de 24 de "pyenv versions --bare".
    comandos_pyenv="$(pyenv commands)"
    versoes_pyenv="$(pyenv versions --bare)"
    grep -qx virtualenv <<<"$comandos_pyenv" || erro "plugin pyenv-virtualenv ausente (https://github.com/pyenv/pyenv-virtualenv)"
    if ! grep -qx "$PYTHON_VERSAO" <<<"$versoes_pyenv"; then
        # compilar o Python leva minutos e precisa de libs de build: não fazemos em silêncio
        erro "Python $PYTHON_VERSAO não instalado no pyenv. Rode: pyenv install $PYTHON_VERSAO (e repita este script)"
    fi
    DIR_AMBIENTE="$(pyenv root)/versions/$NOME_AMBIENTE"
    if [[ -d "$DIR_AMBIENTE" ]]; then
        ok "virtualenv '$NOME_AMBIENTE' já existe ($DIR_AMBIENTE)"
    else
        rodar pyenv virtualenv "$PYTHON_VERSAO" "$NOME_AMBIENTE"
    fi
    # .python-version (versionado no repositório) já seleciona o ambiente ao entrar na pasta
    [[ "$(cat "$RAIZ/.python-version")" == "$NOME_AMBIENTE" ]] || aviso ".python-version não aponta para $NOME_AMBIENTE"
else
    PY_SISTEMA="python${PYTHON_VERSAO%.*}"                 # python3.12, explícito
    command -v "$PY_SISTEMA" >/dev/null || erro "$PY_SISTEMA não encontrado no PATH (necessário para --venv local)"
    # EXECUTAR, não só achar o nome: um shim do pyenv aparece no PATH mas falha fora de uma pasta
    # cujo .python-version aponte para um 3.12 ("pyenv: python3.12: command not found")
    if ! info="$("$PY_SISTEMA" -c 'import platform, sys; print(platform.python_version(), sys.executable)' 2>&1)"; then
        erro "$PY_SISTEMA está no PATH mas não executa:
$info"
    fi
    versao="${info%% *}"
    ok "$PY_SISTEMA = ${info#* } ($versao)"
    [[ "$versao" == "$PYTHON_VERSAO" ]] || aviso "$PY_SISTEMA é $versao (o projeto foi validado em $PYTHON_VERSAO)"
    DIR_AMBIENTE="$RAIZ/.venv"
    if [[ -x "$DIR_AMBIENTE/bin/python" ]]; then
        ok ".venv já existe"
    else
        rodar "$PY_SISTEMA" -m venv "$DIR_AMBIENTE"
    fi
fi
PY="$DIR_AMBIENTE/bin/python"                             # caminho explícito, sem depender de shims

# --- 3. dependências --------------------------------------------------------------------------
passo "Dependências (versões do requirements.lock)"
rodar "$PY" -m pip install --upgrade pip
rodar "$PY" -m pip install -r "$RAIZ/requirements.lock"
rodar "$PY" -m pip install --no-deps -e "$RAIZ"          # editável: 'git pull' atualiza o código

if [[ $SIMULAR -eq 0 ]]; then
    # opencv-python (não headless) traz plugins Qt que conflitam com o PySide6 (CLAUDE.md)
    if "$PY" -m pip show opencv-python >/dev/null 2>&1; then
        erro "opencv-python (não headless) instalado no ambiente: conflita com o PySide6. Rode: $PY -m pip uninstall opencv-python"
    fi
    "$PY" - <<'EOF' || erro "importação falhou (ver mensagem acima)"
from importlib.metadata import version
import cv2, PySide6, linuxpy, tomli_w  # noqa: F401
import sdk_elden.camera.gui.janela_principal  # noqa: F401
print(f"    ok: sdk-elden {version('sdk-elden')}, OpenCV {cv2.__version__}, PySide6 {PySide6.__version__}")
EOF
fi

# --- 4. câmeras -------------------------------------------------------------------------------
passo "Acesso às câmeras"
# testa leitura+escrita de fato: no desktop o acesso costuma vir por ACL da sessão (não do grupo
# video); por SSH/sem sessão gráfica, só o grupo video dá acesso
shopt -s nullglob
nos=(/dev/video*)
if [[ ${#nos[@]} -eq 0 ]]; then
    aviso "nenhum /dev/video* (câmera desconectada?)"
else
    sem_acesso=()
    for n in "${nos[@]}"; do [[ -r "$n" && -w "$n" ]] || sem_acesso+=("$n"); done
    if [[ ${#sem_acesso[@]} -eq 0 ]]; then
        ok "${#nos[@]} nós V4L2 acessíveis: ${nos[*]}"
    else
        aviso "sem acesso a: ${sem_acesso[*]}. Rode: sudo usermod -aG video $USER (e entre de novo na sessão)"
    fi
fi

# --- 5. testes --------------------------------------------------------------------------------
if [[ $TESTES -eq 1 ]]; then
    passo "Testes sem hardware"
    rodar "$PY" -m pip install pytest                   # já vem do lock; garante em instalações antigas
    (cd "$RAIZ" && rodar "$PY" -m pytest -q -m "not hardware")
fi

# --- 6. atalho no menu ------------------------------------------------------------------------
if [[ $ATALHO -eq 1 ]]; then
    passo "Atalho no menu de aplicativos"
    destino="$HOME/.local/share/applications/sdk-cam.desktop"
    conteudo="[Desktop Entry]
Type=Application
Name=sdk-cam
Comment=Gerenciador de câmeras V4L2 (sdkEldenGinner)
Exec=$DIR_AMBIENTE/bin/sdk-cam
Icon=camera-web
Terminal=false
Categories=Video;Utility;"
    printf '    escrevendo %s\n' "$destino"
    if [[ $SIMULAR -eq 0 ]]; then
        mkdir -p "$(dirname "$destino")"
        printf '%s\n' "$conteudo" > "$destino"
    fi
fi

# --- resumo -----------------------------------------------------------------------------------
passo "Resumo"
[[ $SIMULAR -eq 1 ]] && echo "    (simulação: nada foi executado)"
echo "    ambiente: $DIR_AMBIENTE"
echo "    comandos: sdk-cam, sdk-cam-listar, sdk-cam-capturar, sdk-cam-gravar, sdk-cam-rajada"
[[ "$MODO" == "local" ]] && echo "    (modo local: ative com 'source .venv/bin/activate' ou use $DIR_AMBIENTE/bin/sdk-cam)"
if [[ ${#AVISOS[@]} -gt 0 ]]; then
    echo "    ${#AVISOS[@]} aviso(s):"
    for a in "${AVISOS[@]}"; do echo "      - $a"; done
else
    echo "    sem avisos"
fi
