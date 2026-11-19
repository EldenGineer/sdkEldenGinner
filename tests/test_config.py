from dataclasses import dataclass

import pytest

from sdk_elden.utils.config import ErroConfig, carregar_secao, de_dict, salvar_secao


@dataclass
class Exemplo:
    nome: str = "x"
    n: int = 1
    taxa: float = 1.5
    ligado: bool = False


def test_arquivo_inexistente_usa_padroes(tmp_path):
    assert carregar_secao(tmp_path / "nao.toml", "s", Exemplo) == Exemplo()


def test_ida_e_volta_preserva_outras_secoes(tmp_path):
    arq = tmp_path / "sub" / "c.toml"
    salvar_secao(arq, "outra", Exemplo(nome="fica"))
    salvar_secao(arq, "s", Exemplo(nome="a", n=2, taxa=3.0, ligado=True))
    assert carregar_secao(arq, "s", Exemplo) == Exemplo("a", 2, 3.0, True)
    assert carregar_secao(arq, "outra", Exemplo).nome == "fica"
    assert not list(arq.parent.glob(".*.tmp"))  # sem lixo da escrita atômica


def test_chave_desconhecida(tmp_path):
    with pytest.raises(ErroConfig, match="desconhecida"):
        de_dict(Exemplo, {"nomee": "typo"})


@pytest.mark.parametrize("dados", [{"n": "1"}, {"n": True}, {"ligado": 1}, {"nome": 3}])
def test_tipo_errado(dados):
    with pytest.raises(ErroConfig, match="deve ser"):
        de_dict(Exemplo, dados)


def test_int_aceito_em_float():
    assert de_dict(Exemplo, {"taxa": 30}).taxa == 30


def test_toml_quebrado(tmp_path):
    arq = tmp_path / "c.toml"
    arq.write_text("[s\nnome = ")
    with pytest.raises(ErroConfig, match="TOML inválido"):
        carregar_secao(arq, "s", Exemplo)
