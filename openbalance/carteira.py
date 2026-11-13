"""Carteira de investimentos — o que Investidor10, Kinvo, Status Invest e Gorila mostram,
calculado com os dados da Pluggy, do extrato e de índices públicos.

    custo e lucro por ativo     movimentações da Pluggy (compras/vendas) ou valor aplicado do título
    proventos (renda mensal)    movimentações INTEREST + rendimentos do extrato sem ativo identificado
    proventos a receber         anunciados na B3 (b3.py) × quantidade na data com; FIIs sem anúncio, pelo último rendimento
    vencimentos e indexadores   dados de cada título
    % do CDI / IPCA no período  CDI e IPCA mensais (Ipeadata; API do Banco Central como reserva)
    meta de alocação            metas que você define por classe
    evolução do patrimônio      fica em historico.py (valor reconstruído dia a dia pelas cotações)

Posições importadas por arquivo (sem movimentações nem valor aplicado) entram com custo desconhecido.
"""

import calendar
import csv
import io
import json
import re
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import b3, regras
from .banco import bruto, para_json
from .pluggy import ErroApi

ESQUEMA = """
CREATE TABLE IF NOT EXISTS movimentos_investimento (
    id TEXT PRIMARY KEY, investimento_id TEXT, item_id TEXT, codigo TEXT, data TEXT, bruto TEXT
);
CREATE INDEX IF NOT EXISTS ix_movimentos_codigo ON movimentos_investimento (codigo, data);
CREATE TABLE IF NOT EXISTS indices (serie TEXT, mes TEXT, valor REAL, PRIMARY KEY (serie, mes));
CREATE TABLE IF NOT EXISTS indices_status (serie TEXT PRIMARY KEY, atualizado_em TEXT, fonte TEXT);
CREATE TABLE IF NOT EXISTS metas_alocacao (classe TEXT PRIMARY KEY, percentual REAL NOT NULL);
CREATE TABLE IF NOT EXISTS precos_tesouro (
    titulo TEXT, vencimento TEXT, data TEXT, pu_venda REAL, pu_compra REAL, taxa_venda REAL,
    PRIMARY KEY (titulo, vencimento, data)
);
CREATE TABLE IF NOT EXISTS valores_carteira (data TEXT PRIMARY KEY, bruto REAL, liquido REAL);
"""
# Preços oficiais diários do Tesouro Direto (dados abertos do Tesouro Transparente).
URL_PRECOS_TESOURO = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
                      "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")

CLASSES = ("tesouro", "fundos", "renda_fixa", "acoes", "etf", "fiis", "acoes_exterior", "reits", "renda_fixa_exterior",
           "cripto", "outros")
# Negociadas em bolsa: ticker, cotação diária e proventos da B3 quando o código é da B3 (BDRs, por exemplo).
BOLSA = ("acoes", "etf", "fiis", "acoes_exterior", "reits")
FUNDOS = {"INVESTMENT_FUND", "MULTIMARKET_FUND", "FIXED_INCOME_FUND", "STOCK_FUND", "EXCHANGE_FUND", "OFFSHORE_FUND"}
RENDA_VARIAVEL = {"STOCK", "ETF", "BDR", "DERIVATIVES", "OPTION"}
RE_TICKER = re.compile(r"\b([A-Z]{4}\d{1,2})\b")
RE_TICKER_B3 = re.compile(r"^[A-Z]{4}\d{1,2}F?$")
# Nome ou emissor de FII como os bancos escrevem: "FII HGLG", "CSHG LOGISTICA FDO INV IMOB", "FUNDO DE INVESTIMENTO IMOBILIARIO".
RE_FII = re.compile(r"\bFII\b|\bFDO\.? INV\.? IMOB|\bIMOBILIARI")
# ETF pelo nome, emissor ou nome de pregão: "ISTOCK IBOVESPA FUNDO DE ÍNDICE", "BB ETF IBOV", "ISHARES BOVA".
RE_ETF = re.compile(r"\bETF\b|\bINDICE\b|\bINDEX\b|\bISHARES\b")
USER_AGENT = "open-balance/1.0"

# Séries mensais (% no mês). A primeira fonte que responder vale.
FONTES_INDICES = {
    "cdi": [("ipeadata", "BM12_TJCDI12"), ("bcb", 4391)],
    "ipca": [("ipeadata", "PRECOS12_IPCAG12"), ("bcb", 433)],
}


def garantir_tabelas(conexao):
    conexao.executescript(ESQUEMA)


# ============================================================================ posições
def ticker(i):
    """Código de negociação na B3 ('HGLG11'), pelo código da posição ou pelo nome ('HGLG11 · CSHG LOG…'). None se não tem."""
    codigo = (i.get("code") or "").strip().upper()
    if RE_TICKER_B3.match(codigo):
        return codigo.rstrip("F")  # PETR4F (fracionário) é PETR4
    achado = RE_TICKER.search(regras.normalizar(i.get("name")))
    return achado[1] if achado else None


def fundo_listado(i):
    """Cota de fundo negociada em bolsa que não é FII (ISIN com 'CTF', como BRBOVACTF003): 'etf', 'infra' ou None.
    O banco pode mandar essas cotas como ação. Sem sinal de ETF e com a B3 dizendo que não é FII nem Fiagro
    (i['_b3'] == 'outro'), é fundo de infraestrutura, como o PREE11."""
    if i.get("_b3") in ("fii", "fiagro") or i.get("subtype") == "REAL_ESTATE_FUND":
        return None
    nome = regras.normalizar(" ".join(filter(None, (i.get("name"), i.get("issuer"), i.get("_b3_nome")))))
    if i.get("subtype") == "ETF" or i.get("type") == "ETF" or (ticker(i) and RE_ETF.search(nome)):
        return "etf"
    if (i.get("isin") or "").upper()[6:9] != "CTF":
        return None
    return "infra" if i.get("_b3") == "outro" else None


def classe_investimento(i):
    """Tesouro Direto | Fundos | Renda fixa (CDB, LCI, COE, saldo em conta aplicado) | Ações | ETFs |
    FIIs (e Fiagros e fundos de infraestrutura listados) | Ações internacionais (e BDRs) | REITs |
    Renda fixa internacional | Criptomoedas | Outros.
    O Itaú informa FIIs e ETFs como ação (EQUITY/STOCK): vale o que a B3 diz do ticker (i['_b3'], ver _brutas)
    ou o nome/emissor da posição. As classes internacionais e cripto vêm de posições importadas (leitores.py)."""
    tipo, sub = i.get("type"), i.get("subtype")
    if sub == "TREASURY":
        return "tesouro"
    if sub == "CRYPTO" or tipo == "CRYPTO":
        return "cripto"
    if sub == "REIT":
        return "reits"
    if sub in ("FOREIGN_STOCK", "BDR"):
        return "acoes_exterior"
    if sub == "FOREIGN_FIXED_INCOME":
        return "renda_fixa_exterior"
    if i.get("_b3") in ("fii", "fiagro") or sub == "REAL_ESTATE_FUND":
        return "fiis"
    if ticker(i) and RE_FII.search(regras.normalizar(" ".join(filter(None, (i.get("name"), i.get("issuer")))))):
        return "fiis"
    fundo = fundo_listado(i)
    if fundo:  # o usuário quer os fundos de infraestrutura junto dos FIIs
        return "fiis" if fundo == "infra" else "etf"
    if sub in RENDA_VARIAVEL or tipo in ("EQUITY", "ETF"):
        return "acoes"
    if sub in FUNDOS or tipo == "MUTUAL_FUND":
        return "fundos"
    if tipo in ("FIXED_INCOME", "COE") or sub == "STRUCTURED_NOTE":
        return "renda_fixa"
    return "outros"


def rentabilidade_contratada(i):
    """Texto da taxa contratada: 'IPCA + 7,22% a.a.', 'Prefixado 13,93% a.a.', '100% do CDI'."""
    def pct(v):
        return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"

    indexador, taxa, fixa = i.get("rateType"), i.get("rate"), i.get("fixedAnnualRate")
    if indexador in ("CDI", "SELIC") and taxa:
        texto = f"{pct(taxa)} do {indexador}"
        return f"{texto} + {pct(fixa)} a.a." if fixa else texto
    if indexador and taxa:
        return f"{indexador} + {pct(taxa)} a.a."
    if fixa:
        return f"Prefixado {pct(fixa)} a.a."
    return None


def _codigo(i):
    return i.get("code") or i.get("isin") or i.get("name") or i["id"]


def _brutas(conexao, itens):
    """Todas as posições (ativas e encerradas) dos itens visíveis: [(item_id, bruto)].
    Quem tem ticker já consultado na B3 ganha '_b3' ('fii', 'fiagro', 'outro'), que decide a classe."""
    tipos_b3 = b3.tipos(conexao)
    nomes_b3 = {r["emissor"]: r["nome"] for r in conexao.execute("SELECT emissor, nome FROM ativos_b3")}
    resultado = []
    for r in conexao.execute("SELECT item_id, bruto FROM investimentos"):
        if r["item_id"] not in itens:
            continue
        i = bruto(r)
        emissor = b3.emissor(ticker(i))
        tipo = tipos_b3.get(emissor)
        if tipo and tipo != "desconhecido":
            i["_b3"], i["_b3_nome"] = tipo, nomes_b3.get(emissor)
        resultado.append((r["item_id"], i))
    return resultado + list(_saldos_em_conta(conexao, itens))


def _saldos_em_conta(conexao, itens):
    """Saldo de conta corrente que o banco aplica sozinho (Itaú, Nubank): o app do banco o soma aos investimentos.
    Vira uma posição pós-fixada de renda fixa; '_conta' é o id da conta (o histórico usa os saldos guardados dela)."""
    for r in conexao.execute("SELECT id, item_id, bruto FROM contas WHERE tipo = 'BANK'"):
        if r["item_id"] not in itens:
            continue
        conta = bruto(r)
        valor = (conta.get("bankData") or {}).get("automaticallyInvestedBalance") or 0
        if valor >= 0.01:
            yield r["item_id"], {
                "id": f"conta:{r['id']}", "_conta": r["id"], "code": f"conta:{r['id']}",
                "name": "Saldo em conta aplicado automaticamente", "type": "FIXED_INCOME", "subtype": "AUTOMATIC_INVESTMENT",
                "rateType": "CDI", "amount": valor, "balance": valor, "status": "ACTIVE", "date": conta.get("updatedAt"),
            }


def resgate_nao_informado(i, movimentos, hoje_iso):
    """Data do resgate de uma posição que o banco ainda informa como ativa (o Itaú faz isso): ela continua na lista
    com o valor congelado no dia do resgate, e a última venda tem exatamente a quantidade e o valor de hoje.
    None para as posições de verdade."""
    quantidade = i.get("quantity") or 0
    if i.get("status") == "TOTAL_WITHDRAWAL" or not quantidade:
        return None
    negocios = [m for m in movimentos if m.get("type") in ("BUY", "SELL")]
    if not negocios or negocios[-1].get("type") != "SELL":
        return None
    venda = negocios[-1]
    tres_dias = (date.fromisoformat(hoje_iso) - timedelta(days=3)).isoformat()
    if (abs((venda.get("quantity") or 0) - quantidade) <= 1e-6 * max(1, quantidade)
            and abs((venda.get("amount") or 0) - (i.get("amount") or 0)) < 0.05 and venda["date"][:10] < tres_dias):
        return venda["date"][:10]
    return None


def encerrada(i, movimentos, hoje_iso):
    return i.get("status") == "TOTAL_WITHDRAWAL" or bool(resgate_nao_informado(i, movimentos, hoje_iso))


def posicoes(conexao, itens):
    """Posições ativas, no formato que a tela consome. 'saldo' é o valor bruto (Tesouro a mercado)."""
    precos = precos_tesouro(conexao)
    hoje_iso = date.today().isoformat()
    movs = _movimentos(conexao, itens)
    resultado = []
    for item_id, i in _brutas(conexao, itens):
        if encerrada(i, movs.get(_codigo(i), []), hoje_iso):
            continue
        valor = avaliar(i, precos, hoje_iso)
        saldo = valor["bruto"]
        aplicado = i.get("amountOriginal")
        resultado.append({
            "id": i["id"], "instituicao": itens.get(item_id, {}).get("instituicao"), "nome": i.get("name"),
            "classe": classe_investimento(i), "tipo": i.get("type"), "subtipo": i.get("subtype"), "saldo": saldo,
            "liquido": valor["liquido"], "fonteValor": valor["fonte"], "dataPreco": valor.get("dataPreco"),
            "puMercado": valor.get("puMercado"), "taxaMercado": valor.get("taxaMercado"), "puCurva": valor.get("puCurva"),
            "codigo": i.get("code"), "quantidade": i.get("quantity"),
            "precoUnitario": valor.get("puMercado") or i.get("value"),
            "aplicado": aplicado, "ganho": round(saldo - aplicado, 2) if aplicado else None,
            "rentabilidade": rentabilidade_contratada(i) or ("aplicação automática" if i.get("_conta") else None),
            "taxa12m": i.get("lastTwelveMonthsRate"), "conta": bool(i.get("_conta")),
            "vencimento": (i.get("dueDate") or "")[:10] or None, "compra": (i.get("purchaseDate") or "")[:10] or None,
            "emissor": i.get("issuer"), "origem": i.get("origem") or "pluggy", "tipoB3": i.get("_b3"),
        })
    resultado.sort(key=lambda p: -p["saldo"])
    return resultado


# ============================================================================ valor de mercado (Tesouro)
def _data_iso(dd_mm_aaaa):
    return f"{dd_mm_aaaa[6:10]}-{dd_mm_aaaa[3:5]}-{dd_mm_aaaa[0:2]}"


def _numero(texto):
    return float(texto.replace(".", "").replace(",", ".")) if texto else None


def atualizar_precos_tesouro(conexao, forcar=False, desde="2024-01-01"):
    """Baixa os preços oficiais do Tesouro Direto, no máximo uma vez por dia. Devolve a fonte, 'em dia' ou None."""
    garantir_tabelas(conexao)
    status = conexao.execute("SELECT atualizado_em FROM indices_status WHERE serie = 'tesouro'").fetchone()
    if status and status[0][:10] == date.today().isoformat() and not forcar:
        return "em dia"
    try:
        req = urllib.request.Request(URL_PRECOS_TESOURO, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resposta:
            texto = resposta.read().decode("latin-1")
    except Exception:  # noqa: BLE001 — fora do ar: a carteira usa o valor da instituição
        return None
    linhas = []
    for r in csv.DictReader(io.StringIO(texto), delimiter=";"):
        data = _data_iso(r["Data Base"])
        if data >= desde:
            linhas.append((r["Tipo Titulo"], _data_iso(r["Data Vencimento"]), data, _numero(r["PU Venda Manha"]),
                           _numero(r["PU Compra Manha"]), _numero(r["Taxa Venda Manha"])))
    if not linhas:
        return None
    with conexao:
        conexao.executemany("INSERT OR REPLACE INTO precos_tesouro (titulo, vencimento, data, pu_venda, pu_compra, taxa_venda) "
                            "VALUES (?, ?, ?, ?, ?, ?)", linhas)
        conexao.execute("INSERT OR REPLACE INTO indices_status (serie, atualizado_em, fonte) VALUES ('tesouro', ?, ?)",
                        (datetime.now().isoformat(timespec="seconds"), "tesouro-transparente"))
    return "tesouro-transparente"


def precos_tesouro(conexao):
    """Último preço de cada título: {vencimento: [{titulo, data, pu, taxa}]}."""
    garantir_tabelas(conexao)
    por_vencimento = defaultdict(list)
    for r in conexao.execute(
            "SELECT p.titulo, p.vencimento, p.data, p.pu_venda, p.taxa_venda FROM precos_tesouro p JOIN "
            "(SELECT titulo, vencimento, max(data) AS data FROM precos_tesouro GROUP BY titulo, vencimento) u "
            "ON u.titulo = p.titulo AND u.vencimento = p.vencimento AND u.data = p.data"):
        if r["pu_venda"]:
            por_vencimento[r["vencimento"]].append({"titulo": r["titulo"], "data": r["data"], "pu": r["pu_venda"],
                                                    "taxa": r["taxa_venda"]})
    return por_vencimento


def _preco_mercado(i, precos, hoje_iso):
    """Preço de venda do dia para um título do Tesouro. Casa pelo vencimento e pelo nome do título
    (ex.: 'Tesouro IPCA+ 2040' não é o 'IPCA+ com Juros Semestrais'); sem nome, pelo preço mais próximo."""
    if i.get("subtype") != "TREASURY" or not i.get("quantity"):
        return None
    candidatos = [c for c in precos.get((i.get("dueDate") or "")[:10], [])
                  if (date.fromisoformat(hoje_iso) - date.fromisoformat(c["data"])).days <= 10]
    if not candidatos:
        return None
    nome = regras.normalizar(i.get("name"))
    pelo_nome = [c for c in candidatos if nome.startswith(regras.normalizar(c["titulo"]))]
    if pelo_nome:
        return max(pelo_nome, key=lambda c: len(c["titulo"]))
    referencia = i.get("value") or 0
    return min(candidatos, key=lambda c: abs(c["pu"] - referencia))


def _aliquota_ir(compra, hoje_iso):
    """Tabela regressiva da renda fixa."""
    if not compra:
        return 0.15
    dias = (date.fromisoformat(hoje_iso) - date.fromisoformat(compra[:10])).days
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


def avaliar(i, precos, hoje_iso):
    """Valor bruto e líquido de uma posição.
    Tesouro: quantidade × preço de venda oficial do dia (marcação a mercado), não o valor na curva.
    Demais: o que a instituição informa (amount = bruto, balance = líquido de IR)."""
    liquido_inst = i.get("balance") or 0
    bruto_inst = i.get("amount") or liquido_inst
    mercado = _preco_mercado(i, precos, hoje_iso)
    if not mercado:
        return {"bruto": bruto_inst, "liquido": liquido_inst, "fonte": "instituição"}
    bruto = i["quantity"] * mercado["pu"]
    aplicado = i.get("amountOriginal") or 0
    # IR: usa a alíquota efetiva que a própria instituição aplicou (já considera o prazo de cada compra);
    # sem essa informação, a tabela regressiva pela data de compra.
    ganho_inst, imposto_inst = bruto_inst - aplicado, bruto_inst - liquido_inst
    if aplicado and ganho_inst > 0 and imposto_inst > 0:
        aliquota = min(0.225, imposto_inst / ganho_inst)
    else:
        aliquota = _aliquota_ir(i.get("purchaseDate"), hoje_iso)
    imposto = max(0.0, bruto - aplicado) * aliquota if aplicado else imposto_inst
    return {"bruto": round(bruto, 2), "liquido": round(bruto - imposto, 2), "fonte": "mercado",
            "dataPreco": mercado["data"], "puMercado": mercado["pu"], "taxaMercado": mercado["taxa"],
            "puCurva": i.get("value"), "titulo": mercado["titulo"]}


# ============================================================================ sincronização
def sincronizar_movimentos(conexao, api, item_id, investimentos):
    """Busca as movimentações (compras, vendas, proventos) de cada posição. Falhas pontuais são ignoradas."""
    garantir_tabelas(conexao)
    linhas = []
    for inv in investimentos:
        try:
            movimentos = api.get_paginado(f"/investments/{inv['id']}/transactions", {})
        except ErroApi:
            continue
        linhas += [(m["id"], inv["id"], item_id, _codigo(inv), (m.get("date") or "")[:10], para_json(m))
                   for m in movimentos]
    with conexao:
        conexao.executemany("INSERT OR REPLACE INTO movimentos_investimento (id, investimento_id, item_id, codigo, data, bruto) "
                            "VALUES (?, ?, ?, ?, ?, ?)", linhas)
    return len(linhas)


def _baixar_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def _ipeadata(codigo):
    dados = _baixar_json(f"https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{codigo}')")
    return [(v["VALDATA"][:7], float(v["VALVALOR"])) for v in dados.get("value", [])
            if v.get("VALVALOR") is not None and v["VALDATA"][:4] >= "2015"]


def _bcb(codigo):
    fim = date.today().strftime("%d/%m/%Y")
    dados = _baixar_json(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
                         f"&dataInicial=01/01/2015&dataFinal={fim}")
    return [(f"{v['data'][6:10]}-{v['data'][3:5]}", float(v["valor"])) for v in dados]


def atualizar_indices(conexao, forcar=False):
    """CDI e IPCA mensais, no máximo uma vez por dia. Devolve {serie: fonte usada | None | 'em dia'}."""
    garantir_tabelas(conexao)
    hoje = date.today().isoformat()
    resultado = {}
    for serie, fontes in FONTES_INDICES.items():
        status = conexao.execute("SELECT atualizado_em FROM indices_status WHERE serie = ?", (serie,)).fetchone()
        if status and status[0][:10] == hoje and not forcar:
            resultado[serie] = "em dia"
            continue
        resultado[serie] = None
        for fonte, codigo in fontes:
            try:
                valores = _ipeadata(codigo) if fonte == "ipeadata" else _bcb(codigo)
            except Exception:  # noqa: BLE001 — fonte fora do ar ou bloqueada: tenta a próxima
                continue
            if valores:
                with conexao:
                    conexao.executemany("INSERT OR REPLACE INTO indices (serie, mes, valor) VALUES (?, ?, ?)",
                                        [(serie, m, v) for m, v in valores])
                    conexao.execute("INSERT OR REPLACE INTO indices_status (serie, atualizado_em, fonte) VALUES (?, ?, ?)",
                                    (serie, datetime.now().isoformat(timespec="seconds"), fonte))
                resultado[serie] = fonte
                break
    return resultado


# ============================================================================ índices
def _mes_seguinte(d):
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


class Indice:
    """Índice mensal (% no mês por 'AAAA-MM'), com pró-rata nos meses parciais."""

    def __init__(self, mensal, hoje_iso):
        self.mensal = mensal
        self.hoje = hoje_iso
        completos = sorted(m for m in mensal if m < hoje_iso[:7])
        self.ultimo_completo = completos[-1] if completos else None

    def __bool__(self):
        return bool(self.mensal)

    def fator(self, inicio, fim=None):
        fim = fim or self.hoje
        d0, d1 = date.fromisoformat(inicio[:10]), date.fromisoformat(fim[:10])
        f, mes = 1.0, date(d0.year, d0.month, 1)
        while mes <= d1 and d1 > d0:
            chave, prox = mes.isoformat()[:7], _mes_seguinte(mes)
            taxa = self.mensal.get(chave)
            if taxa is None:
                break  # mês ainda não publicado (IPCA sai com atraso)
            dias = (prox - mes).days
            if chave == self.hoje[:7]:  # o valor do mês corrente já é parcial (até ~hoje)
                dias = max(1, (date.fromisoformat(self.hoje) - mes).days)
            sobreposicao = (min(d1, prox) - max(d0, mes)).days
            f *= (1 + taxa / 100) ** min(1.0, max(0, sobreposicao) / dias)
            mes = prox
        return f

    def acumulado_12m(self):
        """% acumulado nos 12 últimos meses fechados, e o período."""
        meses = sorted(m for m in self.mensal if m <= (self.ultimo_completo or ""))[-12:]
        f = 1.0
        for m in meses:
            f *= 1 + self.mensal[m] / 100
        return ((f - 1) * 100, meses[0], meses[-1]) if meses else (None, None, None)


def carregar_indices(conexao, hoje_iso):
    garantir_tabelas(conexao)
    series = defaultdict(dict)
    for r in conexao.execute("SELECT serie, mes, valor FROM indices"):
        series[r["serie"]][r["mes"]] = r["valor"]
    status = {r["serie"]: dict(r) for r in conexao.execute("SELECT * FROM indices_status")}
    return Indice(series.get("cdi", {}), hoje_iso), Indice(series.get("ipca", {}), hoje_iso), status


# ============================================================================ movimentações
def _movimentos(conexao, itens):
    """Movimentações por código do ativo. De itens antigos (ex.: antes de reconectar) só entra
    o que for anterior às movimentações do item atual, para não contar duas vezes."""
    garantir_tabelas(conexao)
    por_codigo = defaultdict(lambda: {"atuais": [], "antigos": []})
    for r in conexao.execute("SELECT item_id, codigo, bruto FROM movimentos_investimento"):
        por_codigo[r["codigo"]]["atuais" if r["item_id"] in itens else "antigos"].append(bruto(r))
    resultado = {}
    for codigo, g in por_codigo.items():
        inicio = min((m["date"][:10] for m in g["atuais"]), default="9999")
        resultado[codigo] = sorted(g["atuais"] + [m for m in g["antigos"] if m["date"][:10] < inicio],
                                   key=lambda m: (m["date"], m.get("type") != "BUY"))
    return resultado


def _custo_medio(movimentos, quantidade_atual):
    """Custo pelas compras e vendas (custo médio). completo = as movimentações explicam a quantidade atual."""
    quantidade = custo = comprado = vendido = 0.0
    fluxos = []
    for m in movimentos:
        q, valor, dia = m.get("quantity") or 0, m.get("amount") or 0, m["date"][:10]
        if m.get("type") == "BUY":
            quantidade += q
            custo += valor
            comprado += valor
            fluxos.append((dia, valor))
        elif m.get("type") == "SELL":
            if quantidade > 0:
                custo -= custo * min(1.0, q / quantidade)
            quantidade -= q
            vendido += valor
            fluxos.append((dia, -valor))
    alvo = quantidade_atual or 0
    completo = bool(fluxos) and abs(quantidade - alvo) <= max(0.01, 0.01 * alvo)
    return {"custo": custo, "fluxos": fluxos, "completo": completo, "comprado": comprado, "vendido": vendido}


def _comparar(fluxos, valor_final, recebidos, indice, hoje_iso):
    """Ganho real x ganho que o índice daria com os mesmos aportes/resgates.
    recebidos = [(data, valor)] que saíram da posição (proventos), corrigidos pelo índice até hoje."""
    if not indice or not fluxos:
        return None
    aportado = sum(v for _, v in fluxos)
    equivalente = sum(v * indice.fator(d, hoje_iso) for d, v in fluxos)
    real = valor_final + sum(v * indice.fator(d, hoje_iso) for d, v in recebidos)
    ganho_indice = equivalente - aportado
    if ganho_indice <= 0 or aportado <= 0:
        return None
    return {"ganhoReal": real - aportado, "ganhoIndice": ganho_indice, "pct": (real - aportado) / ganho_indice * 100,
            "indicePeriodo": ganho_indice / aportado * 100}


# ============================================================================ proventos
def _tipo_provento(descricao_normalizada):
    if "DIVIDEND" in descricao_normalizada:
        return "Dividendos"
    if re.search(r"JSCP|\bJCP\b|JUROS S/ ?CAP", descricao_normalizada):
        return "JCP"
    return "Rendimento"


def _proventos(movs, transacoes, nomes_por_codigo, hoje_iso):
    """Proventos dos ativos (movimentações INTEREST) + rendimentos do extrato que não vieram nelas."""
    lista = []
    for codigo, movimentos in movs.items():
        for m in movimentos:
            if m.get("type") == "INTEREST" and (m.get("amount") or 0) > 0:
                lista.append({"data": m["date"][:10], "valor": m["amount"], "codigo": codigo,
                              "origem": nomes_por_codigo.get(codigo, codigo), "tipo": "Provento", "_extrato": False})
    for t in transacoes:
        if t["natureza"] != regras.RENDIMENTO or not t["entrada"] or t.get("oculto") or t["data"] > hoje_iso:
            continue
        desc = regras.normalizar(t["descricao"])
        ticker = (RE_TICKER.search(desc) or [None, None])[1]
        tipo = _tipo_provento(desc)
        par = next((p for p in lista if not p["_extrato"] and p["codigo"] == ticker and abs(p["valor"] - t["valor"]) < 0.05
                    and abs((date.fromisoformat(p["data"]) - date.fromisoformat(t["data"])).days) <= 7), None)
        if par:  # mesmo provento visto nas duas fontes: fica um, com o tipo do extrato (mais específico)
            par["tipo"], par["_extrato"] = tipo, True
            continue
        origem = ticker or ("Aplicação automática" if "APLIC AUT" in desc else t["descricao"][:40])
        lista.append({"data": t["data"], "valor": t["valor"], "codigo": ticker, "origem": origem, "tipo": tipo,
                      "_extrato": True})
    for p in lista:
        p.pop("_extrato", None)
    return sorted(lista, key=lambda p: p["data"])


# ============================================================================ proventos anunciados (B3)
def atualizar_proventos_b3(conexao, itens, forcar=False):
    """Consulta a B3 para cada ticker da carteira: se é FII e quais proventos já foram anunciados."""
    tickers = {ticker(i) for _, i in _brutas(conexao, itens) if classe_investimento(i) not in ("tesouro", "renda_fixa")}
    return b3.atualizar(conexao, tickers - {None}, forcar)


def _somar_meses_data(iso, n):
    """'2026-01-31', 1 → '2026-02-28'."""
    mes = _somar_meses(iso[:7], n)
    return f"{mes}-{min(int(iso[8:10]), calendar.monthrange(int(mes[:4]), int(mes[5:7]))[1]):02d}"


def _quantidade_no_dia(q_hoje, movimentos, dia):
    """Quantidade ao fim de um dia passado: a de hoje, desfazendo as compras e vendas feitas depois dele."""
    q = q_hoje
    for m in movimentos:
        if m["date"][:10] > dia:
            q += {"BUY": -1, "SELL": 1}.get(m.get("type"), 0) * (m.get("quantity") or 0)
    return max(0.0, q)


def _bolsa(brutas, movs, b3_por_emissor, consultados, hoje_iso):
    """Ações e FIIs agrupados por ticker: proventos da B3 deste papel, quantidade de hoje e movimentações."""
    grupos = {}
    for _, i in brutas:
        tk, classe = ticker(i), classe_investimento(i)
        if classe not in BOLSA or not tk:
            continue
        movimentos = movs.get(_codigo(i), [])
        g = grupos.setdefault(tk, {
            "ticker": tk, "classe": classe, "quantidade": 0.0, "movimentos": movimentos, "semQuantidade": False,
            "consultado": b3.emissor(tk) in consultados, "importada": False,
            "proventos": b3.do_ativo(b3_por_emissor.get(b3.emissor(tk), []), tk, i.get("isin")),
        })
        g["movimentos"] = g["movimentos"] or movimentos
        g["importada"] |= i.get("origem") == "importacao"
        if not encerrada(i, movimentos, hoje_iso):
            g["quantidade"] += i.get("quantity") or 0
            g["semQuantidade"] |= not i.get("quantity")
    return grupos


def _mensal(proventos, hoje_iso):
    """FII que pagou rendimento em pelo menos 10 dos últimos 12 meses: paga todo mês."""
    inicio = (date.fromisoformat(hoje_iso) - timedelta(days=380)).isoformat()
    return sum(1 for p in proventos if p["tipo"] == "RENDIMENTO" and p["data_com"] >= inicio) >= 10


def _a_receber(grupos, hoje_iso):
    """Proventos anunciados e ainda não pagos, pela quantidade na data com (o último dia para ter direito).
        garantido     a data com já passou: quantidade daquele dia (recuada pelas compras e vendas de depois)
        se mantiver   a data com ainda vai chegar: quantidade de hoje
        estimado      FII que paga todo mês e ainda não anunciou o próximo: repete o último rendimento
    Posição importada de planilha não tem compras e vendas: supõe a quantidade de hoje na data com ('suposto')."""
    limite = (date.fromisoformat(hoje_iso) - timedelta(days=365)).isoformat()
    itens = []
    for g in grupos.values():
        pendentes = [p for p in g["proventos"] if (p["pagamento"] or "9999") >= hoje_iso and p["data_com"] >= limite]
        for p in pendentes:
            passou = p["data_com"] < hoje_iso
            q = _quantidade_no_dia(g["quantidade"], g["movimentos"], p["data_com"]) if passou else g["quantidade"]
            if q > 0:
                itens.append({"codigo": g["ticker"], "classe": g["classe"], "tipo": b3.nome_tipo(p["tipo"]),
                              "dataCom": p["data_com"], "pagamento": p["pagamento"], "porCota": p["valor"], "quantidade": q,
                              "valor": round(q * p["valor"], 2), "situacao": "garantido" if passou else "se mantiver",
                              "suposto": passou and g["importada"] and not g["movimentos"], "referencia": p["referencia"]})
        rendimentos = [p for p in g["proventos"] if p["tipo"] == "RENDIMENTO" and p["pagamento"]]
        if (g["classe"] == "fiis" and g["quantidade"] > 0 and rendimentos and _mensal(rendimentos, hoje_iso)
                and not any(p["tipo"] == "RENDIMENTO" for p in pendentes)):
            ultimo, n = rendimentos[-1], 1
            while _somar_meses_data(ultimo["pagamento"], n) < hoje_iso:
                n += 1
            itens.append({"codigo": g["ticker"], "classe": g["classe"], "tipo": "Rendimento",
                          "dataCom": _somar_meses_data(ultimo["data_com"], n), "pagamento": _somar_meses_data(ultimo["pagamento"], n),
                          "porCota": ultimo["valor"], "quantidade": g["quantidade"],
                          "valor": round(g["quantidade"] * ultimo["valor"], 2), "situacao": "estimado", "referencia": None})
    return sorted(itens, key=lambda x: (x["pagamento"] or "9999", x["codigo"]))


def _renda_b3(g, quantidade, preco, hoje_iso):
    """Último provento, quanto o papel pagou por cota em 12 meses (pela data com, sem amortizações) e a renda
    mensal esperada para esta quantidade: FII mensal = último rendimento; os demais = média dos 12 meses."""
    inicio = (date.fromisoformat(hoje_iso) - timedelta(days=365)).isoformat()
    renda = [p for p in g["proventos"] if p["tipo"] != "AMORTIZACAO" and p["data_com"] <= hoje_iso]
    por_cota_12m = sum(p["valor"] for p in renda if p["data_com"] > inicio)
    ultimo = renda[-1] if renda else None
    mensal = ultimo["valor"] if g["classe"] == "fiis" and ultimo and _mensal(renda, hoje_iso) else por_cota_12m / 12
    return {
        "ultimoProvento": {"porCota": ultimo["valor"], "dataCom": ultimo["data_com"], "pagamento": ultimo["pagamento"],
                           "tipo": b3.nome_tipo(ultimo["tipo"])} if ultimo else None,
        "porCota12m": round(por_cota_12m, 6), "dy12m": por_cota_12m / preco * 100 if preco else None,
        "rendaMensal": round(mensal * (quantidade or 0), 2),
    }


# ============================================================================ montagem
def _mes(iso):
    return iso[:7]


def _somar_meses(mes, n):
    ano, m = map(int, mes.split("-"))
    total = ano * 12 + m - 1 + n
    return f"{total // 12}-{total % 12 + 1:02d}"


def montar(conexao, itens, transacoes, hoje):
    hoje_iso = hoje.isoformat()
    cdi, ipca, status_indices = carregar_indices(conexao, hoje_iso)
    brutas = _brutas(conexao, itens)
    precos = precos_tesouro(conexao)
    movs = _movimentos(conexao, itens)
    # Só as posições vivas têm valor; as demais (inclusive as que o banco ainda mostra já resgatadas) são encerradas.
    vivas = {i["id"]: i for _, i in brutas if not encerrada(i, movs.get(_codigo(i), []), hoje_iso)}
    valores = {k: avaliar(i, precos, hoje_iso) for k, i in vivas.items()}
    # A outra visão do Resumo: Tesouro na curva, pela taxa contratada (sem preço de mercado, vale o que o banco informa).
    valores_curva = ({k: avaliar(i, {}, hoje_iso) for k, i in vivas.items()}
                     if any(v["fonte"] == "mercado" for v in valores.values()) else None)
    ignoradas = [{"nome": i.get("name"), "resgate": data, "valor": i.get("amount")} for _, i in brutas
                 if (data := resgate_nao_informado(i, movs.get(_codigo(i), []), hoje_iso))]
    nomes = {_codigo(i): (ticker(i) if classe_investimento(i) in BOLSA else i.get("name")) or _codigo(i)
             for _, i in brutas}
    proventos = _proventos(movs, transacoes, nomes, hoje_iso)
    proventos_por_codigo = defaultdict(list)
    for p in proventos:
        if p["codigo"]:
            proventos_por_codigo[p["codigo"]].append(p)
    inicio_12m = (hoje - timedelta(days=365)).isoformat()
    b3_por_emissor, b3_atualizado = b3.carregar(conexao)
    bolsa = _bolsa(brutas, movs, b3_por_emissor, set(b3.tipos(conexao)), hoje_iso)
    a_receber = _a_receber(bolsa, hoje_iso)

    def avaliar_posicoes(valores):
        """Posições vivas com custo, ganho, proventos e comparação com índices; e as encerradas."""
        lista, encerradas = [], []
        for item_id, i in brutas:
            # Valor principal = bruto (Tesouro a mercado, ou na curva na outra visão); líquido = depois do IR estimado.
            codigo = _codigo(i)
            valor = valores.get(i["id"], {"bruto": 0, "liquido": 0})
            bruto_atual, liquido = valor["bruto"], valor["liquido"]
            historico = _custo_medio(movs.get(codigo, []), i.get("quantity"))
            recebidos = [(p["data"], p["valor"]) for p in proventos_por_codigo.get(codigo, [])]
            total_proventos = sum(v for _, v in recebidos)

            if i["id"] not in valores:
                if historico["completo"] and historico["comprado"] > 0:
                    resultado = historico["vendido"] + total_proventos - historico["comprado"]
                    encerradas.append({
                        "nome": nomes.get(codigo, codigo), "classe": classe_investimento(i),
                        "inicio": historico["fluxos"][0][0], "fim": historico["fluxos"][-1][0],
                        "investido": round(historico["comprado"], 2), "resgatado": round(historico["vendido"], 2),
                        "proventos": round(total_proventos, 2), "resultado": round(resultado, 2),
                        "resultadoPct": resultado / historico["comprado"] * 100,
                    })
                continue

            aplicado = i.get("amountOriginal")
            if aplicado:  # Tesouro/CDB: a instituição informa o valor aplicado
                fluxos = historico["fluxos"] if historico["completo"] and abs(historico["custo"] - aplicado) <= 0.02 * aplicado \
                    else ([((i.get("purchaseDate") or "")[:10], aplicado)] if i.get("purchaseDate") else [])
                custo, fonte_custo = aplicado, "instituição"
            elif historico["completo"]:
                fluxos, custo, fonte_custo = historico["fluxos"], historico["custo"], "movimentações"
            else:
                fluxos, custo, fonte_custo = [], None, None

            ganho = bruto_atual - custo if custo else None
            ganho_liquido = liquido - custo if custo else None
            classe = classe_investimento(i)
            grupo = bolsa.get(ticker(i)) if classe in BOLSA else None
            quantidade = i.get("quantity")
            renda_b3 = _renda_b3(grupo, quantidade, bruto_atual / quantidade if quantidade else None, hoje_iso) \
                if grupo and grupo["consultado"] else None
            pendentes = [x for x in a_receber if grupo and x["codigo"] == grupo["ticker"]]
            # Comparação com índices pelo valor bruto (os índices também são brutos).
            vs_cdi = _comparar(fluxos, bruto_atual, recebidos, cdi, hoje_iso) if custo else None
            vs_ipca = _comparar(fluxos, bruto_atual, recebidos, ipca, hoje_iso) if custo else None
            primeira = fluxos[0][0] if fluxos else None
            maduro = bool(primeira) and (hoje - date.fromisoformat(primeira)).days >= 30
            lista.append({
                "id": i["id"], "codigo": codigo, "classe": classe, "saldo": round(bruto_atual, 2),
                "bruto": round(bruto_atual, 2), "liquido": round(liquido, 2), "ir": round(max(0.0, bruto_atual - liquido), 2),
                "fonteValor": valor.get("fonte"),
                "custo": round(custo, 2) if custo else None, "fonteCusto": fonte_custo,
                "ganho": round(ganho, 2) if ganho is not None else None,
                "ganhoPct": ganho / custo * 100 if ganho is not None else None,
                "ganhoLiquido": round(ganho_liquido, 2) if ganho_liquido is not None else None,
                "ganhoLiquidoPct": ganho_liquido / custo * 100 if ganho_liquido is not None else None,
                "precoMedio": custo / quantidade if custo and quantidade and (classe in BOLSA or classe == "fundos") else None,
                "conta": bool(i.get("_conta")),  # saldo em conta: não tem custo nem ganho, e isso não é falta de dado
                "proventos": round(total_proventos, 2),
                "proventos12m": round(sum(v for d, v in recebidos if d >= inicio_12m), 2),
                # Proventos pela B3: último pago, yield de 12 meses, renda mensal esperada e o que já foi anunciado.
                "ultimoProvento": renda_b3["ultimoProvento"] if renda_b3 else None,
                "dy12m": renda_b3["dy12m"] if renda_b3 else None,
                "rendaMensalProventos": renda_b3["rendaMensal"] if renda_b3
                                        else round(sum(v for d, v in recebidos if d >= inicio_12m) / 12, 2) if classe in BOLSA else None,
                "aReceber": round(sum(x["valor"] for x in pendentes if x["situacao"] != "estimado"), 2),
                "proximoProvento": pendentes[0] if pendentes else None,
                "pctCdi": vs_cdi["pct"] if vs_cdi and maduro else None,
                "cdiPeriodo": vs_cdi["indicePeriodo"] if vs_cdi and maduro else None,
                "ganhoCdi": round(vs_cdi["ganhoIndice"], 2) if vs_cdi and maduro else None,
                "ganhoRealCdi": round(vs_cdi["ganhoReal"], 2) if vs_cdi and maduro else None,
                "acimaIpca": (((bruto_atual + total_proventos) / (sum(v * ipca.fator(d, hoje_iso) for d, v in fluxos) or 1)) - 1) * 100
                             if vs_ipca and maduro else None,
                "desde": primeira,
                "rendaMensalEstimada": _renda_estimada(i, bruto_atual, cdi, ipca),
            })
        return lista, encerradas

    lista, encerradas = avaliar_posicoes(valores)
    lista_curva = avaliar_posicoes(valores_curva)[0] if valores_curva else None
    posicoes_por_id = {p["id"]: p for p in lista}
    for p in lista_curva or []:
        posicoes_por_id[p["id"]]["saldoCurva"] = p["saldo"]
    # Registro do valor do dia, como o banco informa (a evolução do Resumo vem do histórico de cotações).
    if lista:
        with conexao:
            conexao.execute("INSERT OR REPLACE INTO valores_carteira (data, bruto, liquido) VALUES (?, ?, ?)",
                            (hoje_iso, round(sum(p["bruto"] for p in lista), 2), round(sum(p["liquido"] for p in lista), 2)))
    datas_preco = sorted({v["dataPreco"] for v in valores.values() if v.get("dataPreco")})
    return {
        "posicoes": posicoes_por_id,
        "resumo": _resumo(lista, encerradas, proventos, a_receber, inicio_12m, cdi, ipca, hoje_iso),
        "resumoCurva": _resumo(lista_curva, encerradas, proventos, a_receber, inicio_12m, cdi, ipca, hoje_iso) if lista_curva else None,
        "proventos": {**_resumo_proventos(proventos, posicoes_por_id, lista, a_receber, inicio_12m, hoje_iso),
                      "aReceber": _resumo_a_receber(a_receber, bolsa, b3_atualizado)},
        "vencimentos": _vencimentos(brutas, valores),
        "indexadores": _indexadores(brutas, valores),
        "precoTesouro": {"data": datas_preco[-1] if datas_preco else None,
                         "titulos": sum(1 for v in valores.values() if v.get("fonte") == "mercado")},
        "encerradas": sorted(encerradas, key=lambda e: e["fim"], reverse=True),
        "ignoradas": ignoradas,
        "metas": {r["classe"]: r["percentual"] for r in conexao.execute("SELECT classe, percentual FROM metas_alocacao")},
        "indices": {
            "cdi12m": cdi.acumulado_12m()[0], "ipca12m": ipca.acumulado_12m()[0],
            "cdiAte": cdi.ultimo_completo, "ipcaAte": ipca.ultimo_completo,
            # Só CDI e IPCA: a mesma tabela guarda o status das cotações do histórico (CVM, Yahoo).
            "fonte": {s: status_indices[s].get("fonte") for s in ("cdi", "ipca") if s in status_indices},
            "atualizadoEm": max((status_indices[s].get("atualizado_em") or "" for s in ("cdi", "ipca") if s in status_indices),
                                default=None),
        },
    }


def _renda_estimada(i, saldo, cdi, ipca):
    """Rendimento bruto estimado por mês, pelas taxas contratadas e pelo CDI/IPCA recentes (só renda fixa)."""
    if classe_investimento(i) not in ("tesouro", "renda_fixa") or not saldo:
        return None
    indexador, taxa, fixa = i.get("rateType"), i.get("rate") or 0, i.get("fixedAnnualRate") or 0
    if indexador in ("CDI", "SELIC"):
        if not cdi.ultimo_completo:
            return None
        mensal = cdi.mensal[cdi.ultimo_completo] / 100 * (taxa / 100) + ((1 + fixa / 100) ** (1 / 12) - 1)
    elif indexador == "IPCA":
        acumulado = ipca.acumulado_12m()[0]
        if acumulado is None:
            return None
        mensal = (1 + acumulado / 100) ** (1 / 12) * (1 + taxa / 100) ** (1 / 12) - 1
    elif fixa:
        mensal = (1 + fixa / 100) ** (1 / 12) - 1
    else:
        return None
    return round(saldo * mensal, 2)


def _resumo(lista, encerradas, proventos, a_receber, inicio_12m, cdi, ipca, hoje_iso):
    patrimonio = sum(p["saldo"] for p in lista)
    com_custo = [p for p in lista if p["custo"]]
    aplicado = sum(p["custo"] for p in com_custo)
    ganho_aberto = sum(p["ganho"] for p in com_custo)
    realizado = sum(e["resultado"] - e["proventos"] for e in encerradas)
    total_proventos = sum(p["valor"] for p in proventos)
    proventos_12m = sum(p["valor"] for p in proventos if p["data"] >= inicio_12m)
    com_cdi = [p for p in lista if p["pctCdi"] is not None]
    ganho_cdi = sum(p["ganhoCdi"] for p in com_cdi)
    ganho_real_cdi = sum(p["ganhoRealCdi"] for p in com_cdi)
    renda = [p["rendaMensalEstimada"] for p in lista if p["rendaMensalEstimada"]]
    renda_bolsa = {classe: sum(p["rendaMensalProventos"] or 0 for p in lista if p["classe"] == classe) for classe in BOLSA}
    # Rendimentos do extrato sem ativo (ex.: aplicação automática da conta) não estão em nenhuma posição.
    renda_outros = sum(p["valor"] for p in proventos if not p["codigo"] and p["data"] >= inicio_12m) / 12
    lucro = ganho_aberto + realizado + total_proventos
    # Saldo em conta fica fora da cobertura de custo: é dinheiro parado, não um custo que faltou informar.
    aplicacoes = [p for p in lista if not p["conta"]]
    return {
        "patrimonio": round(patrimonio, 2), "patrimonioLiquido": round(sum(p["liquido"] for p in lista), 2),
        "ir": round(sum(p["ir"] for p in lista), 2), "aplicado": round(aplicado, 2),
        "ganhoAbertoLiquido": round(sum(p["ganhoLiquido"] for p in com_custo), 2),
        "cobertura": sum(p["saldo"] for p in com_custo) / (sum(p["saldo"] for p in aplicacoes) or 1),
        "semCusto": len(aplicacoes) - len(com_custo),
        "saldoEmConta": round(sum(p["saldo"] for p in lista if p["conta"]), 2),
        "ganhoAberto": round(ganho_aberto, 2), "ganhoRealizado": round(realizado, 2),
        "proventos": round(total_proventos, 2), "proventos12m": round(proventos_12m, 2),
        "proventosDesde": proventos[0]["data"] if proventos else None,
        "lucro": round(lucro, 2), "rentabilidade": lucro / aplicado * 100 if aplicado else None,
        "pctCdi": ganho_real_cdi / ganho_cdi * 100 if ganho_cdi > 0 else None,
        "rendaFixaMensal": round(sum(renda), 2) if renda else None,
        "rendaFixaPosicoes": len(renda),
        "rendaFiisMensal": round(renda_bolsa["fiis"], 2), "rendaAcoesMensal": round(renda_bolsa["acoes"] + renda_bolsa["etf"], 2),
        "rendaExteriorMensal": round(renda_bolsa["acoes_exterior"] + renda_bolsa["reits"], 2),
        "rendaOutrosMensal": round(renda_outros, 2),
        "rendaMensal": round(sum(renda) + sum(renda_bolsa.values()) + renda_outros, 2),
        "aReceber": round(sum(x["valor"] for x in a_receber if x["situacao"] != "estimado"), 2),
    }


def _resumo_proventos(proventos, posicoes_por_id, lista, a_receber, inicio_12m, hoje_iso):
    # 12 meses para trás e, para a frente, até o último pagamento já anunciado (no máximo 3 meses).
    distancias = [(int(x["pagamento"][:4]) - int(hoje_iso[:4])) * 12 + int(x["pagamento"][5:7]) - int(hoje_iso[5:7])
                  for x in a_receber if x["pagamento"]]
    adiante = max([0] + [n for n in distancias if n <= 3])
    meses = [_somar_meses(hoje_iso[:7], n) for n in range(-11, adiante + 1)]
    por_mes = {m: defaultdict(float) for m in meses}
    for p in proventos:
        if _mes(p["data"]) in por_mes:
            por_mes[_mes(p["data"])][p["origem"]] += p["valor"]
    previstos = {m: defaultdict(float) for m in meses}
    for x in a_receber:
        if x["pagamento"] and _mes(x["pagamento"]) in previstos:
            previstos[_mes(x["pagamento"])][(x["codigo"], x["situacao"] == "estimado")] += x["valor"]
    custo_por_codigo = {p["codigo"]: p["custo"] for p in lista if p["custo"]}
    ativos = {p["codigo"] for p in lista}
    por_origem = defaultdict(lambda: {"total": 0.0, "total12m": 0.0, "pagamentos": 0, "ultima": None, "ultimoValor": 0, "tipos": set()})
    for p in proventos:
        o = por_origem[(p["origem"], p["codigo"])]
        o["total"] += p["valor"]
        o["pagamentos"] += 1
        o["tipos"].add(p["tipo"])
        if p["data"] >= inicio_12m:
            o["total12m"] += p["valor"]
        if not o["ultima"] or p["data"] >= o["ultima"]:
            o["ultima"], o["ultimoValor"] = p["data"], p["valor"]
    origens = []
    for (origem, codigo), o in por_origem.items():
        custo = custo_por_codigo.get(codigo)
        origens.append({
            "origem": origem, "codigo": codigo, "total": round(o["total"], 2), "total12m": round(o["total12m"], 2),
            "pagamentos": o["pagamentos"], "ultima": o["ultima"], "ultimoValor": round(o["ultimoValor"], 2),
            "tipos": sorted(o["tipos"]), "naCarteira": codigo in ativos,
            "yieldOnCost": o["total12m"] / custo * 100 if custo else None,
        })
    return {
        "porMes": [{"mes": m, "total": round(sum(por_mes[m].values()), 2),
                    "itens": sorted(({"origem": k, "valor": round(v, 2)} for k, v in por_mes[m].items()), key=lambda x: -x["valor"]),
                    "aReceber": round(sum(previstos[m].values()), 2),
                    "itensAReceber": sorted(({"origem": k[0], "estimado": k[1], "valor": round(v, 2)}
                                             for k, v in previstos[m].items()), key=lambda x: -x["valor"])}
                   for m in meses],
        "porOrigem": sorted(origens, key=lambda o: -o["total12m"]),
        "ultimos": [{**p} for p in proventos[-8:]][::-1],
    }


def _resumo_a_receber(a_receber, bolsa, atualizado_em):
    """O que a tela e o aviso do Atualizar mostram: anunciados (garantidos ou se mantiver) e estimativas dos FIIs."""
    anunciados = [x for x in a_receber if x["situacao"] != "estimado"]
    return {
        "itens": a_receber,
        "total": round(sum(x["valor"] for x in anunciados), 2),
        "garantido": round(sum(x["valor"] for x in anunciados if x["situacao"] == "garantido"), 2),
        "estimado": round(sum(x["valor"] for x in a_receber if x["situacao"] == "estimado"), 2),
        "fiis": round(sum(x["valor"] for x in anunciados if x["classe"] == "fiis"), 2),
        "proximo": next((x for x in anunciados if x["pagamento"]), None),
        "ate": max((x["pagamento"] for x in anunciados if x["pagamento"]), default=None),
        "ativos": len(bolsa),
        "naoConsultados": sorted(g["ticker"] for g in bolsa.values() if not g["consultado"]),
        "semQuantidade": sorted(g["ticker"] for g in bolsa.values() if g["semQuantidade"]),
        "atualizadoEm": atualizado_em,
    }


def _vencimentos(brutas, valores):
    anos = defaultdict(lambda: {"total": 0.0, "itens": []})
    sem = 0.0
    for _, i in brutas:
        if i["id"] not in valores:  # encerrada
            continue
        saldo = valores[i["id"]]["bruto"]
        venc = (i.get("dueDate") or "")[:10]
        if venc:
            a = anos[venc[:4]]
            a["total"] += saldo
            a["itens"].append({"nome": i.get("name"), "vencimento": venc, "valor": saldo, "classe": classe_investimento(i)})
        else:
            sem += saldo
    return {"porAno": [{"ano": ano, "total": round(v["total"], 2), "itens": sorted(v["itens"], key=lambda x: x["vencimento"])}
                       for ano, v in sorted(anos.items())],
            "semVencimento": round(sem, 2)}


def _indexadores(brutas, valores):
    grupos = defaultdict(float)
    for _, i in brutas:
        if i["id"] not in valores or classe_investimento(i) not in ("tesouro", "renda_fixa"):
            continue
        indexador = i.get("rateType")
        if indexador in ("CDI", "SELIC"):
            nome = "Pós-fixado (CDI/Selic)"
        elif indexador == "IPCA":
            nome = "Inflação (IPCA+)"
        elif i.get("fixedAnnualRate"):
            nome = "Prefixado"
        else:
            nome = "Outros"
        grupos[nome] += valores[i["id"]]["bruto"]
    total = sum(grupos.values())
    return [{"nome": n, "valor": round(v, 2), "pct": v / total * 100 if total else 0}
            for n, v in sorted(grupos.items(), key=lambda kv: -kv[1])]


# ============================================================================ metas de alocação
def salvar_metas(conexao, corpo):
    garantir_tabelas(conexao)
    metas = corpo.get("metas") or {}
    if not isinstance(metas, dict):
        raise ValueError("metas inválidas")
    limpas = {}
    for classe, valor in metas.items():
        if classe not in CLASSES:
            raise ValueError(f"classe desconhecida: {classe}")
        if valor in (None, ""):
            continue
        valor = float(valor)
        if not 0 <= valor <= 100:
            raise ValueError("cada meta precisa ficar entre 0% e 100%")
        limpas[classe] = valor
    if sum(limpas.values()) > 100.01:
        raise ValueError(f"as metas somam {sum(limpas.values()):.1f}%; o máximo é 100%")
    with conexao:
        conexao.execute("DELETE FROM metas_alocacao")
        conexao.executemany("INSERT INTO metas_alocacao (classe, percentual) VALUES (?, ?)", list(limpas.items()))
    return {"ok": True, "metas": limpas}
