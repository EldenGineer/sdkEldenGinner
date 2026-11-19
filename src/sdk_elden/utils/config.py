"""Configuração em TOML mapeada para dataclasses.

Uso: cada ferramenta define um dataclass (campos str/int/float/bool) e uma seção
no arquivo TOML. Chave desconhecida ou tipo errado gera ErroConfig com o nome do
campo: o erro aparece em vez de ser ignorado em silêncio. Chave ausente usa o padrão do dataclass.

Local padrão: DIR_CONFIG (~/.config/sdk_elden), um caminho fixo e explícito, sem busca
em vários lugares.
"""
from __future__ import annotations

import dataclasses
import os
import tomllib
from pathlib import Path
from typing import TypeVar, get_type_hints

import tomli_w

DIR_CONFIG = Path.home() / ".config" / "sdk_elden"

T = TypeVar("T")


class ErroConfig(Exception):
    pass


def de_dict(classe: type[T], dados: dict, origem: str = "") -> T:
    """dict (de uma seção TOML) -> dataclass, com checagem de chaves e tipos."""
    tipos = get_type_hints(classe)
    nomes = {f.name for f in dataclasses.fields(classe)}
    desconhecidas = set(dados) - nomes
    if desconhecidas:
        raise ErroConfig(f"{origem}: chave(s) desconhecida(s) {sorted(desconhecidas)}; válidas: {sorted(nomes)}")
    for chave, valor in dados.items():
        esperado = tipos[chave]
        # bool é subclasse de int em Python: checar explicitamente para não aceitar true num campo int
        ok = isinstance(valor, esperado) and not (esperado is not bool and isinstance(valor, bool))
        if esperado is float and isinstance(valor, int) and not isinstance(valor, bool):
            ok = True  # TOML escreve 30 para 30.0
        if not ok:
            raise ErroConfig(f"{origem}: '{chave}' deve ser {esperado.__name__}, veio {type(valor).__name__} ({valor!r})")
    return classe(**dados)


def carregar_secao(caminho: Path, secao: str, classe: type[T]) -> T:
    """Lê uma seção do TOML. Se o arquivo ou a seção não existirem, devolve os padrões do dataclass."""
    if not caminho.exists():
        return classe()
    try:
        with caminho.open("rb") as f:
            dados = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErroConfig(f"{caminho}: TOML inválido: {e}") from e
    return de_dict(classe, dados.get(secao, {}), f"{caminho} [{secao}]")


def salvar_secao(caminho: Path, secao: str, objeto) -> None:
    """Grava/atualiza só a seção indicada, preservando as outras. Escrita atômica (tmp + rename)."""
    dados = {}
    if caminho.exists():
        with caminho.open("rb") as f:
            dados = tomllib.load(f)
    dados[secao] = dataclasses.asdict(objeto)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f".{caminho.name}.tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(dados, f)
    os.replace(tmp, caminho)
