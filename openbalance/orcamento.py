"""Orçamento mensal de gastos por categoria (ou por grupo de categorias).

Como o gasto do mês é contado (o mesmo critério do resto do painel):
  - só transações de natureza "despesa" (investimento, transferência entre contas suas, pagamento de fatura e
    empréstimo ficam de fora); estorno no cartão abate o gasto;
  - compra no cartão conta no mês da data do lançamento, não no mês da fatura;
  - compra parcelada: cada parcela conta no mês da sua data (a TV de 10× pesa 1/10 por mês).

Um limite no grupo (ex.: "Alimentação") cobre todas as subcategorias dele. Um limite numa subcategoria vale só
para ela; se o grupo também tiver limite, os dois são acompanhados.

O limite inicial sugerido é a mediana do gasto dos últimos 6 meses fechados (mês sem gasto conta como zero).
"""

import statistics
from collections import defaultdict
from datetime import date

from . import regras

MESES_BASE = 6
LIMITE_VALOR = 10_000_000


def garantir_tabela(conexao):
    with conexao:
        conexao.execute("CREATE TABLE IF NOT EXISTS orcamentos (categoria_id TEXT PRIMARY KEY, limite REAL NOT NULL, "
                        "atualizado_em TEXT)")


def carregar(conexao):
    garantir_tabela(conexao)
    return {r["categoria_id"]: r["limite"] for r in conexao.execute("SELECT categoria_id, limite FROM orcamentos")}


def _impacto(t):
    return -t["valor"] if t["entrada"] else t["valor"]


def _meses_fechados(transacoes, hoje_iso):
    """Últimos meses completos com dados. O primeiro mês só vale se os dados começam nos primeiros dias dele."""
    datas = [t["data"] for t in transacoes if t["data"] <= hoje_iso]
    if not datas:
        return []
    primeiro = min(datas)
    inicio = primeiro[:7] if int(primeiro[8:10]) <= 5 else _mes_seguinte(primeiro[:7])
    meses, mes = [], inicio
    while mes < hoje_iso[:7]:
        meses.append(mes)
        mes = _mes_seguinte(mes)
    return meses[-MESES_BASE:]


def _mes_seguinte(mes):
    ano, m = int(mes[:4]), int(mes[5:7])
    return f"{ano + m // 12}-{m % 12 + 1:02d}"


def sugestoes(transacoes, categorias, hoje):
    """Mediana mensal do gasto por categoria e por grupo nos últimos meses fechados."""
    meses = _meses_fechados(transacoes, hoje.isoformat())
    if not meses:
        return {}, []
    validos = set(meses)
    por_chave = defaultdict(lambda: defaultdict(float))
    for t in transacoes:
        if t["natureza"] != regras.DESPESA or t["oculto"] or t["data"][:7] not in validos:
            continue
        v = _impacto(t)
        grupo = (categorias.get(t["categoriaId"]) or {}).get("grupo") or regras.CAT_OUTROS
        por_chave[t["categoriaId"]][t["data"][:7]] += v
        if grupo != t["categoriaId"]:
            por_chave[grupo][t["data"][:7]] += v
    resultado = {}
    for chave, por_mes in por_chave.items():
        mediana = statistics.median(max(0.0, por_mes.get(m, 0.0)) for m in meses)
        if mediana > 0:
            resultado[chave] = round(mediana, 2)
    return resultado, meses


def montar(conexao, transacoes, categorias, hoje=None):
    hoje = hoje or date.today()
    medianas, meses = sugestoes(transacoes, categorias, hoje)
    return {"limites": carregar(conexao), "sugestoes": medianas, "mesesBase": meses}


def salvar(conexao, corpo):
    """{"limites": {categoriaId: valor | null}}: grava os valores informados; null ou zero remove o limite."""
    limites = corpo.get("limites")
    if not isinstance(limites, dict) or len(limites) > 500:
        raise ValueError("limites do orçamento inválidos")
    garantir_tabela(conexao)
    agora = date.today().isoformat()
    with conexao:
        for cat_id, valor in limites.items():
            cat_id = str(cat_id)[:40]
            if valor in (None, "", 0):
                conexao.execute("DELETE FROM orcamentos WHERE categoria_id = ?", (cat_id,))
                continue
            valor = round(float(valor), 2)
            if not 0 < valor <= LIMITE_VALOR:
                raise ValueError("o limite precisa ser maior que zero")
            if not cat_id:
                raise ValueError("categoria inválida")
            conexao.execute("INSERT OR REPLACE INTO orcamentos (categoria_id, limite, atualizado_em) VALUES (?, ?, ?)",
                            (cat_id, valor, agora))
    return {"ok": True, "limites": carregar(conexao)}
