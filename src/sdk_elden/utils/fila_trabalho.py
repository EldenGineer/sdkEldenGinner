"""Fila de trabalho com UMA thread consumidora e tamanho limitado.

Para tirar trabalho lento (ex.: salvar PNG de 2560x1440, ~65 ms) de uma thread que não pode
travar (GUI, laço de captura). `enviar()` nunca bloqueia: com a fila cheia, a tarefa é
DESCARTADA e contada em `descartadas` (melhor perder uma foto contada do que travar a janela).

Os callbacks `ao_concluir` / `ao_falhar` rodam NA THREAD CONSUMIDORA. Para tocar em widgets Qt,
emita um sinal neles (sinal entre threads vira evento na thread da GUI).

Uma tarefa por vez e na ordem de envio (FIFO): os arquivos saem na ordem das capturas.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable

_FIM = object()


class FilaTrabalho:
    def __init__(self, funcao: Callable[..., Any], tamanho: int,
                 ao_concluir: Callable[[Any], None] | None = None,
                 ao_falhar: Callable[[BaseException], None] | None = None,
                 nome: str = "fila-trabalho"):
        if tamanho < 1:
            raise ValueError(f"tamanho da fila deve ser >= 1, veio {tamanho}")
        self._funcao = funcao
        self._ao_concluir = ao_concluir
        self._ao_falhar = ao_falhar
        self._fila: queue.Queue = queue.Queue(maxsize=tamanho)
        self._fechada = False
        self.enviadas = self.concluidas = self.falhas = self.descartadas = 0
        self._thread = threading.Thread(target=self._consumir, name=nome, daemon=True)
        self._thread.start()

    def enviar(self, *args, **kwargs) -> bool:
        """Enfileira `funcao(*args, **kwargs)`. False = descartada (fila cheia). Não bloqueia."""
        if self._fechada:
            raise RuntimeError("fila já fechada")
        try:
            self._fila.put_nowait((args, kwargs))
        except queue.Full:
            self.descartadas += 1
            return False
        self.enviadas += 1
        return True

    def pendentes(self) -> int:
        return self._fila.qsize()

    def _consumir(self) -> None:
        while True:
            item = self._fila.get()
            if item is _FIM:
                return
            args, kwargs = item
            try:
                resultado = self._funcao(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 - repassada ao chamador pelo callback, não engolida
                self.falhas += 1
                if self._ao_falhar:
                    self._ao_falhar(e)
                continue
            self.concluidas += 1
            if self._ao_concluir:
                self._ao_concluir(resultado)

    def fechar(self, timeout: float) -> bool:
        """Termina o que já está na fila e encerra a thread. True = terminou dentro do `timeout`."""
        if not self._fechada:
            self._fechada = True
            self._fila.put(_FIM)  # bloqueante de propósito: tudo que entrou antes será processado
        self._thread.join(timeout)
        return not self._thread.is_alive()
