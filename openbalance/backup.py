"""Cópia de segurança diária do banco, na pasta backup ao lado dele (dados/backup).

Uma por dia, na primeira vez que o Open Balance abre ou sincroniza. Ficam as 7 cópias mais recentes,
mais a última de cada uma das 5 semanas e dos 6 meses mais recentes; as outras são apagadas.
Arquivos que não seguem o nome open-balance-AAAAMMDD.zip (cópias feitas à mão) nunca são apagados.

Para restaurar: feche o Open Balance, extraia o open-balance.db do .zip e ponha no lugar de dados/open-balance.db
(apague junto o open-balance.db-wal e o open-balance.db-shm, se existirem).
"""

import re
import sqlite3
import zipfile
from contextlib import closing
from datetime import date, datetime

from .banco import arquivo

RECENTES, SEMANAS, MESES = 7, 5, 6


def backup_do_dia(conexao, hoje=None):
    """Faz a cópia de hoje, se ainda não existir, e apaga as que saíram da rotação. Devolve o arquivo novo ou None."""
    hoje = hoje or date.today()
    banco = arquivo(conexao)
    pasta = banco.parent / "backup"
    destino = pasta / f"{banco.stem}-{hoje:%Y%m%d}.zip"
    if destino.exists():
        return None
    pasta.mkdir(parents=True, exist_ok=True)
    temporario, parcial = pasta / f"{banco.stem}.copiando", destino.with_suffix(".parcial")
    try:
        # API de backup do SQLite: cópia consistente mesmo com o painel aberto.
        with closing(sqlite3.connect(temporario)) as copia:
            conexao.backup(copia)
            copia.execute("PRAGMA journal_mode=DELETE")  # um arquivo só, sem -wal ao lado
        with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as pacote:
            pacote.write(temporario, banco.name)
        parcial.replace(destino)  # só ganha o nome final depois de completo
    finally:
        temporario.unlink(missing_ok=True)
        parcial.unlink(missing_ok=True)
    rotacionar(pasta, banco.stem)
    return destino


def rotacionar(pasta, nome_banco):
    padrao = re.compile(rf"{re.escape(nome_banco)}-(\d{{8}})\.zip")
    copias = {}
    for caminho in pasta.glob(f"{nome_banco}-*.zip"):
        encontrado = padrao.fullmatch(caminho.name)
        if encontrado:
            try:
                copias[datetime.strptime(encontrado[1], "%Y%m%d").date()] = caminho
            except ValueError:
                continue
    for data in set(copias) - manter(copias):
        copias[data].unlink()


def manter(datas):
    """Datas de cópia que ficam: as mais recentes e a última de cada semana e de cada mês."""
    ordenadas = sorted(datas, reverse=True)
    ultima_da_semana, ultima_do_mes = {}, {}
    for d in ordenadas:  # da mais nova para a mais antiga: a primeira vista em cada período é a última dele
        ultima_da_semana.setdefault(tuple(d.isocalendar())[:2], d)
        ultima_do_mes.setdefault((d.year, d.month), d)
    return (set(ordenadas[:RECENTES]) | set(list(ultima_da_semana.values())[:SEMANAS])
            | set(list(ultima_do_mes.values())[:MESES]))
