"""Leitura e escrita de controles V4L2 (exposição, ganho, foco, ...).

Usa a camada de baixo nível do linuxpy (ver nota em dispositivos.py).

Princípios:
- Validar ANTES de mandar ao driver (tipo, somente leitura, inativo, faixa, step,
  item de menu) e falhar com mensagem clara, em vez de deixar o driver clampar
  em silêncio ou devolver um errno genérico.
- Depois de escrever, reler o valor no driver e devolver o valor REAL aplicado.
- Mudar um controle pode mudar as flags de outros (ex.: auto_exposure -> Manual
  ativa exposure_time_absolute). Por isso as flags são reconsultadas a cada escrita.
"""
from __future__ import annotations

from pathlib import Path

from linuxpy.video import raw
from linuxpy.video.device import IOC, Device, get_controls_values, ioctl, set_controls_values

from sdk_elden.camera.dispositivos import InfoControle, info_controle, iter_controles_brutos, nome_config


class ErroControle(Exception):
    """Escrita/leitura de controle recusada (pela nossa validação ou pelo driver)."""


class ControlesCamera:
    """Sessão de controle de uma câmera. Abre o nó em leitura/escrita.

    Pode ficar aberta junto com o stream de captura (outro fd): o V4L2 permite
    alterar controles durante o streaming. Formato/resolução NÃO são tratados aqui.
    """

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self._dev = Device(str(self.caminho), read_write=True)
        self._dev.open()
        self._brutos: dict[str, object] = {}
        self._consultar()

    # --- ciclo de vida -------------------------------------------------
    def fechar(self) -> None:
        self._dev.close()

    def __enter__(self) -> ControlesCamera:
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()

    # --- consulta --------------------------------------------------------
    def _consultar(self) -> None:
        self._brutos = {nome_config(c.name.decode()): c for c in iter_controles_brutos(self._dev)}

    def nomes(self) -> list[str]:
        return list(self._brutos)

    def info(self, nome: str) -> InfoControle:
        """Estado atual (valor, flags) consultado agora no driver."""
        return info_controle(self._dev, self._bruto_atualizado(nome))

    def todos(self) -> list[InfoControle]:
        self._consultar()
        return [info_controle(self._dev, c) for c in self._brutos.values()]

    def ler(self, nome: str):
        info = self.info(nome)
        if not info.suportado:
            raise ErroControle(f"{nome}: tipo {info.tipo} não suportado")
        return info.valor

    def _bruto_atualizado(self, nome: str):
        if nome not in self._brutos:
            raise ErroControle(f"{self.caminho}: controle desconhecido '{nome}'. Disponíveis: {', '.join(self._brutos)}")
        # reconsulta para ter flags (inativo etc.) atuais
        ctrl = raw.v4l2_query_ext_ctrl()
        ctrl.id = self._brutos[nome].id
        ioctl(self._dev, IOC.QUERY_EXT_CTRL, ctrl)
        self._brutos[nome] = ctrl
        return ctrl

    # --- escrita ---------------------------------------------------------
    def validar(self, nome: str, valor: int) -> InfoControle:
        """Levanta ErroControle se `valor` não puder ser escrito em `nome`. Retorna o InfoControle."""
        info = self.info(nome)
        validar_valor(info, valor)
        return info

    def escrever(self, nome: str, valor: int):
        """Valida, escreve e devolve o valor relido do driver."""
        self.validar(nome, valor)
        ctrl = self._brutos[nome]
        try:
            set_controls_values(self._dev, ((ctrl, int(valor)),))
        except OSError as erro:
            raise ErroControle(f"{nome}: driver recusou {valor} ({erro.strerror}, errno {erro.errno})") from erro
        return get_controls_values(self._dev, (ctrl,))[0]

    def restaurar_padrao(self, nome: str):
        """Escreve o valor padrão reportado pelo driver.

        Se o padrão do driver for inválido (ex.: Redeagle anuncia auto_exposure
        padrão=0, que não é item do menu), falha explicitamente: não escolhemos outro valor por conta própria.
        """
        info = self.info(nome)
        if info.tipo in ("menu", "intmenu") and info.padrao not in info.menu:
            raise ErroControle(
                f"{nome}: padrão do driver ({info.padrao}) não é item válido do menu {info.menu} "
                f"(quirk de firmware); escolha um valor explicitamente"
            )
        return self.escrever(nome, info.padrao)


def validar_valor(info: InfoControle, valor: int) -> None:
    """Validação pura (sem I/O) de um valor contra os metadados do controle.

    Espelha o que o driver faria. Ex.: o uvcvideo devolve EACCES ao escrever em
    controle inativo (verificado na Redeagle em 2026-11-19).
    """
    nome = info.nome
    if not info.suportado:
        raise ErroControle(f"{nome}: tipo {info.tipo} não suportado")
    if info.somente_leitura:
        raise ErroControle(f"{nome}: controle somente leitura")
    if info.inativo:
        raise ErroControle(
            f"{nome}: controle inativo no momento (depende de outro controle, "
            f"ex.: exposure_time_absolute exige auto_exposure em 'Manual Mode')"
        )
    if isinstance(valor, bool):
        valor = int(valor)
    if not isinstance(valor, int):
        raise ErroControle(f"{nome}: valor deve ser inteiro, recebido {type(valor).__name__}")
    if info.tipo == "bitmask":
        if valor < 0 or valor & ~info.maximo:
            raise ErroControle(f"{nome}: bitmask {valor:#x} fora da máscara {info.maximo:#x}")
        return
    if info.tipo in ("menu", "intmenu"):
        if valor not in info.menu:
            raise ErroControle(f"{nome}: índice {valor} inválido; opções: {info.menu}")
        return
    if not info.minimo <= valor <= info.maximo:
        raise ErroControle(f"{nome}: {valor} fora da faixa [{info.minimo}, {info.maximo}]")
    if info.passo > 1 and (valor - info.minimo) % info.passo:
        raise ErroControle(f"{nome}: {valor} não respeita step={info.passo} a partir de {info.minimo}")

