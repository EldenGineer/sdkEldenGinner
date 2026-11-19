import threading
import time

import pytest

from sdk_elden.utils.fila_trabalho import FilaTrabalho


def test_processa_em_ordem_e_fechar_espera_tudo():
    feitos = []
    f = FilaTrabalho(lambda x: (time.sleep(0.01), feitos.append(x))[1], tamanho=10)
    for i in range(10):
        assert f.enviar(i)
    assert f.fechar(5)
    assert feitos == list(range(10)) and f.concluidas == 10


def test_fila_cheia_descarta_sem_bloquear():
    libera = threading.Event()
    f = FilaTrabalho(lambda x: libera.wait(5), tamanho=2)
    resultados = [f.enviar(i) for i in range(6)]  # 1 em execução + 2 na fila; resto descartado
    inicio = time.monotonic()
    assert f.enviar(99) is False
    assert time.monotonic() - inicio < 0.05  # não bloqueou
    assert resultados.count(False) >= 3 and f.descartadas == resultados.count(False) + 1
    libera.set()
    assert f.fechar(5)


def test_falha_vai_para_callback_e_nao_mata_a_thread():
    erros, ok = [], []
    def trabalho(x):
        if x == 1:
            raise ValueError("ruim")
        return x
    f = FilaTrabalho(trabalho, tamanho=5, ao_concluir=ok.append, ao_falhar=erros.append)
    for i in range(3):
        f.enviar(i)
    assert f.fechar(5)
    assert ok == [0, 2] and [str(e) for e in erros] == ["ruim"] and f.falhas == 1


def test_enviar_depois_de_fechar():
    f = FilaTrabalho(lambda: None, tamanho=1)
    f.fechar(5)
    with pytest.raises(RuntimeError):
        f.enviar()


def test_tamanho_invalido():
    with pytest.raises(ValueError):
        FilaTrabalho(lambda: None, tamanho=0)
