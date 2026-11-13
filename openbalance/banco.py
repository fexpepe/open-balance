"""Banco SQLite local. Guarda o JSON bruto da Pluggy + os ajustes feitos por você.

O histórico só cresce: transações mais antigas que a janela do Open Finance (12 meses)
continuam aqui depois de cada sincronização.

Arquivos importados (OFX, CSV…) são convertidos para o mesmo formato da Pluggy e ficam
nas mesmas tabelas; o item deles tem origem = 'importacao'.
"""

import json
import sqlite3
from pathlib import Path

from .config import ARQUIVO_BANCO

CATEGORIAS_PADRAO = Path(__file__).with_name("categorias_padrao.json")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS itens (
    id TEXT PRIMARY KEY, instituicao TEXT, status TEXT, atualizado_em TEXT,
    consentimento_expira TEXT, bruto TEXT
);
CREATE TABLE IF NOT EXISTS contas (
    id TEXT PRIMARY KEY, item_id TEXT, tipo TEXT, saldo REAL, bruto TEXT
);
CREATE TABLE IF NOT EXISTS transacoes (
    id TEXT PRIMARY KEY, conta_id TEXT, data TEXT, bruto TEXT
);
CREATE INDEX IF NOT EXISTS ix_transacoes_conta_data ON transacoes (conta_id, data);
CREATE TABLE IF NOT EXISTS faturas (
    id TEXT PRIMARY KEY, conta_id TEXT, vencimento TEXT, total REAL, bruto TEXT
);
CREATE TABLE IF NOT EXISTS investimentos (
    id TEXT PRIMARY KEY, item_id TEXT, saldo REAL, bruto TEXT
);
CREATE TABLE IF NOT EXISTS categorias (
    id TEXT PRIMARY KEY, descricao TEXT, descricao_pt TEXT, pai_id TEXT, propria INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS historico_saldos (
    data TEXT, ref_id TEXT, tipo TEXT, saldo REAL, PRIMARY KEY (data, ref_id)
);
CREATE TABLE IF NOT EXISTS ajustes (
    transacao_id TEXT PRIMARY KEY, categoria_id TEXT, natureza TEXT, oculto INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS regras (
    id INTEGER PRIMARY KEY AUTOINCREMENT, padrao TEXT NOT NULL, categoria_id TEXT,
    natureza TEXT, criada_em TEXT
);
CREATE TABLE IF NOT EXISTS sincronizacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT, fim TEXT, ok INTEGER, resumo TEXT
);
CREATE TABLE IF NOT EXISTS rotinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT, fim TEXT, ok INTEGER, etapas TEXT
);
CREATE TABLE IF NOT EXISTS importacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, criada_em TEXT, arquivo TEXT, formato TEXT, tipo TEXT,
    conta_id TEXT, inicio TEXT, fim TEXT, novas INTEGER, existentes INTEGER, resumo TEXT
);
CREATE TABLE IF NOT EXISTS formatos_arquivo (
    assinatura TEXT PRIMARY KEY, mapeamento TEXT, tipo TEXT, conta_id TEXT, atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS preferencias (
    chave TEXT PRIMARY KEY, valor TEXT
);
"""


def conectar(caminho=ARQUIVO_BANCO):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # timeout: com outra conexão gravando (sincronização, tarefa agendada), espera a vez em vez de dar "database is locked".
    conexao = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode=WAL")
    conexao.executescript(ESQUEMA)
    migrar(conexao)
    return conexao


def arquivo(conexao):
    """Arquivo do banco desta conexão (para abrir outra conexão no mesmo banco)."""
    return Path(conexao.execute("PRAGMA database_list").fetchone()[2])


def migrar(conexao):
    """Colunas adicionadas depois da primeira versão do banco."""
    colunas = {r["name"] for r in conexao.execute("PRAGMA table_info(categorias)")}
    if "propria" not in colunas:
        with conexao:
            conexao.execute("ALTER TABLE categorias ADD COLUMN propria INTEGER NOT NULL DEFAULT 0")
    colunas = {r["name"] for r in conexao.execute("PRAGMA table_info(itens)")}
    if "origem" not in colunas:
        with conexao:
            conexao.execute("ALTER TABLE itens ADD COLUMN origem TEXT NOT NULL DEFAULT 'pluggy'")
    semear_categorias(conexao)


def semear_categorias(conexao):
    """Sem Pluggy, as categorias vêm da lista padrão (a mesma árvore que a Pluggy usa)."""
    if conexao.execute("SELECT 1 FROM categorias WHERE propria = 0 LIMIT 1").fetchone():
        return
    padrao = json.loads(CATEGORIAS_PADRAO.read_text(encoding="utf-8"))
    with conexao:
        conexao.executemany(
            "INSERT OR IGNORE INTO categorias (id, descricao, descricao_pt, pai_id, propria) VALUES (?, ?, ?, ?, 0)",
            [(c["id"], c["descricao"], c["descricao_pt"], c["pai_id"]) for c in padrao])


def preferencia(conexao, chave, padrao=None):
    linha = conexao.execute("SELECT valor FROM preferencias WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def gravar_preferencia(conexao, chave, valor):
    with conexao:
        if valor in (None, ""):
            conexao.execute("DELETE FROM preferencias WHERE chave = ?", (chave,))
        else:
            conexao.execute("INSERT OR REPLACE INTO preferencias (chave, valor) VALUES (?, ?)", (chave, str(valor)))


def bruto(linha):
    return json.loads(linha["bruto"])


def para_json(obj):
    return json.dumps(obj, ensure_ascii=False)
