"""Dados públicos da B3: o que é cada ticker (ação, FII, Fiagro, ETF) e os proventos que ela já divulgou.

Vem da mesma consulta da página "Eventos corporativos" do site da B3 (GetListedSupplementCompany), que serve
tanto para empresas quanto para fundos listados. Para cada emissor (as 4 letras do ticker) traz o nome de
pregão e os proventos em dinheiro: data com, data de pagamento, valor por ação/cota e o tipo (dividendo, JCP,
rendimento de FII, amortização). Não precisa de cadastro nem de chave.

Cada emissor é consultado no máximo uma vez por dia. Sem internet, o Open Balance usa o que já estava guardado.
"""

import base64
import json
import re
import urllib.request
from datetime import date, datetime

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ativos_b3 (emissor TEXT PRIMARY KEY, nome TEXT, tipo TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS proventos_b3 (
    emissor TEXT, isin TEXT, tipo TEXT, data_com TEXT, pagamento TEXT, valor REAL, referencia TEXT, aprovado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_proventos_b3 ON proventos_b3 (emissor, data_com);
"""
URL_EMISSOR = ("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
               "GetListedSupplementCompany/{}")
USER_AGENT = "Mozilla/5.0 (open-balance)"
RE_TICKER = re.compile(r"^([A-Z]{4})(\d{1,2})F?$")

# Tipo do provento na B3 → nome na tela.
TIPOS = {"RENDIMENTO": "Rendimento", "DIVIDENDO": "Dividendos", "JRS CAP PROPRIO": "JCP", "AMORTIZACAO": "Amortização"}
# Trecho do ISIN de cada final de ticker: PETR3 → BRPETRACNOR…, PETR4 → BRPETRACNPR…, HGLG11 → BRHGLGCTF…,
# TAEE11 (unit) → BRTAEECDAM…. Recibos de subscrição (BRHGLGR26M…) têm ISIN próprio e ficam de fora.
ISIN_POR_FINAL = {"3": ("ACNOR",), "4": ("ACNPR",), "5": ("ACNPA",), "6": ("ACNPB",), "7": ("ACNPC",),
                  "8": ("ACNPD",), "11": ("CTF", "CDAM", "UNT")}


def garantir_tabelas(conexao):
    conexao.executescript(ESQUEMA)


def emissor(ticker):
    m = RE_TICKER.match((ticker or "").strip().upper())
    return m[1] if m else None


def _tipo_ativo(nome):
    """Pelo nome de pregão: 'FII HGLG PAX', 'FIAGRO KINEA', 'ISHARES BOVA', 'BBSEGURIDADE'."""
    nome = (nome or "").upper()
    if nome.startswith("FII"):
        return "fii"
    if nome.startswith("FIAGRO"):
        return "fiagro"
    return "outro"


def _data(dd_mm_aaaa):
    """'15/10/2026' → '2026-10-15'. Data em branco ou 31/12/9999 (ainda não definida) → None."""
    if not dd_mm_aaaa or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", dd_mm_aaaa) or dd_mm_aaaa.endswith("9999"):
        return None
    return f"{dd_mm_aaaa[6:10]}-{dd_mm_aaaa[3:5]}-{dd_mm_aaaa[0:2]}"


def baixar(codigo_emissor):
    """{'nome', 'tipo', 'proventos': [...]} de um emissor, ou None se a B3 não o conhece."""
    parametro = base64.b64encode(json.dumps({"issuingCompany": codigo_emissor, "language": "pt-br"},
                                            separators=(",", ":")).encode()).decode()
    req = urllib.request.Request(URL_EMISSOR.format(parametro), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resposta:
        dados = json.loads(resposta.read().decode("utf-8"))
    if isinstance(dados, str):  # a B3 devolve o JSON dentro de uma string
        dados = json.loads(dados) if dados else []
    # A consulta aceita qualquer código; só vale a resposta do próprio emissor.
    dados = next((d for d in dados or [] if (d.get("code") or "").strip() == codigo_emissor), None)
    if not dados:
        return None
    nome = (dados.get("tradingName") or "").strip()
    proventos = []
    for p in dados.get("cashDividends") or []:
        valor = float((p.get("rate") or "0").replace(".", "").replace(",", "."))
        data_com = _data(p.get("lastDatePrior"))
        if valor <= 0 or not data_com:
            continue
        # A B3 já manda o "º" estragado ("2� Trimestre/2026").
        referencia = re.sub(r"(\d)�", r"\1º", (p.get("relatedTo") or "").strip()).replace("�", "")
        proventos.append({"isin": p.get("isinCode") or p.get("assetIssued"), "tipo": (p.get("label") or "").strip(),
                          "data_com": data_com, "pagamento": _data(p.get("paymentDate")), "valor": valor,
                          "referencia": referencia, "aprovado_em": _data(p.get("approvedOn"))})
    return {"nome": nome, "tipo": _tipo_ativo(nome), "proventos": proventos}


def atualizar(conexao, tickers, forcar=False):
    """Consulta a B3 para os tickers da carteira (uma vez por dia por emissor). Devolve {'consultados', 'erros'}."""
    garantir_tabelas(conexao)
    hoje = date.today().isoformat()
    em_dia = {r["emissor"] for r in conexao.execute("SELECT emissor, atualizado_em FROM ativos_b3")
              if (r["atualizado_em"] or "")[:10] == hoje}
    resultado = {"consultados": 0, "erros": []}
    for codigo in sorted({e for e in map(emissor, tickers) if e} - (set() if forcar else em_dia)):
        try:
            dados = baixar(codigo)
        except Exception as e:  # noqa: BLE001 — B3 fora do ar: fica o que já estava guardado
            resultado["erros"].append(f"{codigo}: {type(e).__name__}: {e}")
            continue
        with conexao:
            conexao.execute("DELETE FROM proventos_b3 WHERE emissor = ?", (codigo,))
            conexao.executemany(
                "INSERT INTO proventos_b3 (emissor, isin, tipo, data_com, pagamento, valor, referencia, aprovado_em) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(codigo, p["isin"], p["tipo"], p["data_com"], p["pagamento"], p["valor"], p["referencia"], p["aprovado_em"])
                 for p in (dados or {}).get("proventos", [])])
            conexao.execute("INSERT OR REPLACE INTO ativos_b3 (emissor, nome, tipo, atualizado_em) VALUES (?, ?, ?, ?)",
                            (codigo, (dados or {}).get("nome"), (dados or {}).get("tipo", "desconhecido"),
                             datetime.now().isoformat(timespec="seconds")))
        resultado["consultados"] += 1
    return resultado


def tipos(conexao):
    """{emissor: 'fii' | 'fiagro' | 'outro' | 'desconhecido'} do que já foi consultado."""
    garantir_tabelas(conexao)
    return {r["emissor"]: r["tipo"] for r in conexao.execute("SELECT emissor, tipo FROM ativos_b3")}


def carregar(conexao):
    """Proventos guardados por emissor, do mais antigo para o mais novo, e quando a B3 foi consultada pela última vez."""
    garantir_tabelas(conexao)
    por_emissor = {}
    for r in conexao.execute("SELECT * FROM proventos_b3 ORDER BY data_com, pagamento"):
        por_emissor.setdefault(r["emissor"], []).append(dict(r))
    atualizado = conexao.execute("SELECT max(atualizado_em) FROM ativos_b3").fetchone()[0]
    return por_emissor, atualizado


def do_ativo(proventos_do_emissor, ticker, isin=None):
    """Só os proventos deste papel: pelo ISIN da posição ou, sem ele, pelo final do ticker."""
    if isin:
        return [p for p in proventos_do_emissor if p["isin"] == isin]
    m = RE_TICKER.match((ticker or "").strip().upper())
    trechos = ISIN_POR_FINAL.get(m[2] if m else "", ())
    return [p for p in proventos_do_emissor if (p["isin"] or "")[6:].startswith(trechos)] if trechos else []


def nome_tipo(tipo_b3):
    return TIPOS.get(tipo_b3, tipo_b3.capitalize() if tipo_b3 else "Provento")
