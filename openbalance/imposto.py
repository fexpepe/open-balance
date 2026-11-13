"""Imposto de renda dos investimentos — uma estimativa para conferir, não orientação tributária.

    apuração mensal (renda variável)   vendas de ações, ETFs, BDRs e FIIs pelo custo médio das movimentações da Pluggy;
                                       ações isentas no mês em que as vendas de ações não passam de R$ 20 mil; prejuízo
                                       compensado dentro do grupo (operações comuns × FIIs); DARF 6015 até o último
                                       dia útil do mês seguinte, só a partir de R$ 10 (abaixo disso, acumula)
    declaração anual                   Bens e Direitos (custo em 31/12), rendimentos isentos (dividendos, FIIs, ganhos
                                       isentos com ações, LCI/LCA) e de tributação exclusiva (JCP, renda fixa e fundos)
    custo informado                    as movimentações cobrem ~12 meses e posições importadas de planilha não têm custo:
                                       você informa o custo total numa data e o resto sai do custo médio

Regras de 2026 (Perguntão IRPF 2026 da Receita, perguntas 706 a 731; IN RFB 1.585/2015):
    operações comuns 15% (ações, ETFs de ações, BDRs) · FIIs e Fiagros 20% · day trade 20% (só sinalizado aqui)
    isenção de R$ 20 mil/mês só para ações à vista — ETF, BDR e FII não têm
    IRRF de 0,005% sobre as vendas ("dedo-duro"), descontado do imposto do mês
    prejuízo de mês isento também compensa ganho tributável (pergunta 729); prejuízo não caduca
    JCP: 15% na fonte até 2025, 17,5% a partir de 2026 (LC 224/2025)
    dividendos: isentos, mas acima de R$ 50 mil no mês da mesma empresa há retenção de 10% sobre o total (Lei 15.270/2025),
    salvo lucros apurados até 2025 com distribuição aprovada até 31/12/2025
"""

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import b3, carteira, regras
from .banco import gravar_preferencia, preferencia

ESQUEMA = """
CREATE TABLE IF NOT EXISTS custos_imposto (
    codigo TEXT PRIMARY KEY, data TEXT, custo REAL, categoria TEXT, atualizado_em TEXT
);
"""

ALIQUOTA = {"comum": 0.15, "fii": 0.20}
LIMITE_ISENCAO_ACOES = 20_000.0
DEDO_DURO = 0.00005  # 0,005%; não é retido quando dá até R$ 1,00
DARF_MINIMO = 10.0
CODIGO_DARF = "6015"
LIMITE_DIVIDENDOS_MES = 50_000.0
RETENCAO_DIVIDENDOS = 0.10
TOL = 1e-6

# Categoria de cada ativo para o IR. "grupo" = onde entra na apuração mensal (None = fora dela).
CATEGORIAS = {
    "acao": {"nome": "Ação", "grupo": "comum"},
    "etf": {"nome": "ETF", "grupo": "comum"},
    "bdr": {"nome": "BDR", "grupo": "comum"},
    "fii": {"nome": "FII / Fiagro", "grupo": "fii"},
    "isento": {"nome": "Fundo isento (infra)", "grupo": None},
    "fora": {"nome": "Fora da apuração", "grupo": None},
}
# Títulos que o banco emite com PU inicial de R$ 1,00 (quantidade = valor aplicado), como o Itaú informa.
BANCARIOS = {"CDB", "RDB", "LCI", "LCA", "LC", "LF", "LCD"}
RENDA_FIXA_ISENTA = {"LCI", "LCA", "CRI", "CRA", "LH", "SAVINGS", "LIG"}
RE_INFRA = re.compile(r"INFRA|INCENTIVAD")

# Bens e Direitos: (grupo, código, nome) — conferir no programa da Receita, que às vezes renumera.
BENS = {
    "acao": ("03", "01", "Ações (inclusive as listadas em bolsa)"),
    "fii": ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
    "fiagro": ("07", "02", "Fiagro"),
    "etf": ("07", "06", "FIP, FIDC e ETF – entidade de investimento"),
    "bdr": ("04", "04", "Ativos negociados em bolsa no Brasil, exceto ações e fundos"),
    "isento": ("07", "10", "Fundos de infraestrutura e outros (alíquota 0%)"),
    "tributado": ("04", "02", "Títulos públicos e privados sujeitos à tributação"),
    "titulo_isento": ("04", "03", "Títulos isentos de tributação"),
    "poupanca": ("04", "01", "Depósito em conta poupança"),
    "fundo": ("07", "01", "Fundos sujeitos à tributação periódica (come-cotas)"),
    "fundo_acoes": ("07", "04", "Fundos de Investimento em Ações"),
    "bitcoin": ("08", "01", "Criptoativo Bitcoin (BTC)"),
    "stablecoin": ("08", "03", "Stablecoins"),
    "cripto": ("08", "02", "Outras criptomoedas (altcoins)"),
}


def garantir_tabelas(conexao):
    conexao.executescript(ESQUEMA)


# ============================================================================ datas
def _pascoa(ano):
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def _feriados(ano):
    """Feriados nacionais e dias sem expediente bancário (carnaval, 31/12)."""
    pascoa = _pascoa(ano)
    fixos = ["01-01", "04-21", "05-01", "09-07", "10-12", "11-02", "11-15", "11-20", "12-25", "12-31"]
    moveis = [pascoa - timedelta(days=48), pascoa - timedelta(days=47), pascoa - timedelta(days=2), pascoa + timedelta(days=60)]
    return {date.fromisoformat(f"{ano}-{f}") for f in fixos} | set(moveis)


def ultimo_dia_util(mes):
    """'2026-08' → '2026-08-31' (ou o dia útil anterior)."""
    ano, m = int(mes[:4]), int(mes[5:7])
    d = date(ano + m // 12, m % 12 + 1, 1) - timedelta(days=1)
    feriados = _feriados(ano)
    while d.weekday() >= 5 or d in feriados:
        d -= timedelta(days=1)
    return d.isoformat()


def aliquota_jcp(data_iso):
    return 0.175 if data_iso >= "2026-01-01" else 0.15


def _aliquota_regressiva(compra, venda):
    dias = (date.fromisoformat(venda) - date.fromisoformat(compra[:10])).days
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


# ============================================================================ custo médio
def _percorrer(eventos, q0):
    """Compras e vendas pelo custo médio. Cada custo é um par (b, a) = b + a × c0, onde c0 é o custo do lote que já
    existia antes das movimentações (q0 cotas) — ainda desconhecido enquanto ninguém o informa. Zerou a posição,
    o lote antigo deixa de pesar (a = 0) e as compras seguintes têm custo conhecido."""
    q, b, a = q0, 0.0, 1.0 if q0 > TOL else 0.0
    pontos, vendas, come_cotas = [(None, q, b, a)], [], []
    for m in eventos:
        tipo, qm, valor, dia = m.get("type"), m.get("quantity") or 0, m.get("amount") or 0, m["date"][:10]
        if tipo == "BUY":
            q, b = q + qm, b + valor
        elif tipo in ("SELL", "TAX", "AJUSTE"):
            antes = q
            fracao = min(1.0, qm / antes) if antes > TOL else 0.0
            cb, ca = b * fracao, a * fracao
            b, a, q = b - cb, a - ca, max(0.0, q - qm)
            if q <= TOL:
                q, b, a = 0.0, 0.0, 0.0
            if tipo == "SELL":
                vendas.append({"data": dia, "quantidade": qm, "valor": valor, "liquido": m.get("netAmount") or valor,
                               "custo": (cb, ca), "excede": qm > antes * 1.001 + TOL})
            elif tipo == "TAX":  # come-cotas: o fundo resgata cotas para pagar o IR
                come_cotas.append({"data": dia, "valor": valor})
        else:
            continue
        pontos.append((dia, q, b, a))
    return vendas, pontos, come_cotas


def _estado(pontos, dia):
    """(q, b, a) ao fim do dia."""
    atual = pontos[0]
    for p in pontos[1:]:
        if p[0] > dia:
            break
        atual = p
    return atual[1], atual[2], atual[3]


def _valor(par, c0):
    b, a = par
    if a <= TOL:
        return b
    return None if c0 is None else b + a * c0


# ============================================================================ ativos
def categoria_fiscal(i, classe, tk, nome_b3):
    """(categoria, incerta). ETFs e fundos de infraestrutura listados chegam do banco como ação: a cota de fundo
    tem 'CTF' no ISIN (BRBOVACTF003); FII é decidido pela B3 (classe 'fiis'). Fundo de infraestrutura listado fica na
    classe 'fiis' da carteira, mas aqui é isento."""
    if tk and carteira.fundo_listado(i) == "infra":
        return "isento", True
    if classe == "fiis":
        return "fii", False
    if not tk or classe not in carteira.BOLSA:
        return "fora", False
    sub = i.get("subtype")
    if sub == "BDR" or classe not in ("acoes", "etf") or re.match(r"^[A-Z]{4}3[2-59]$", tk):
        return "bdr", False
    if classe == "etf" or sub == "ETF" or i.get("type") == "ETF":
        return "etf", False
    if (i.get("isin") or "").upper()[6:9] == "CTF":
        nome = regras.normalizar(" ".join(filter(None, (i.get("name"), i.get("issuer"), nome_b3))))
        return ("isento" if RE_INFRA.search(nome) else "etf"), True
    return "acao", False


def _codigo_bem(ativo):
    """Grupo e código de Bens e Direitos sugeridos para o ativo (None quando depende do caso, como bens no exterior)."""
    categoria, classe, sub, i = ativo["categoria"], ativo["classe"], ativo["subtipo"], ativo["_bruto"]
    if categoria == "fii":
        return BENS["fiagro" if i.get("_b3") == "fiagro" else "fii"]
    if categoria in ("acao", "etf", "bdr", "isento"):
        return BENS[categoria]
    nome = regras.normalizar(i.get("name"))
    if classe == "tesouro" or (classe == "renda_fixa" and sub not in RENDA_FIXA_ISENTA):
        return BENS["poupanca"] if sub == "SAVINGS" else BENS["tributado"]
    if classe == "renda_fixa":
        return BENS["titulo_isento"]
    if classe == "fundos":
        if RE_INFRA.search(nome):
            return BENS["isento"]
        return BENS["fundo_acoes"] if sub == "STOCK_FUND" else BENS["fundo"]
    if classe == "cripto":
        if re.search(r"BITCOIN|\bBTC\b", nome):
            return BENS["bitcoin"]
        return BENS["stablecoin"] if re.search(r"\bUSD[TC]\b|STABLE", nome) else BENS["cripto"]
    return None


def _ativos(conexao, itens, hoje_iso):
    """Um ativo por ticker (ações, FIIs, ETFs, BDRs) ou por posição (renda fixa, fundos, demais), com as compras e
    vendas, a quantidade de hoje e o custo — das movimentações, do valor aplicado que o banco informa ou o informado."""
    garantir_tabelas(conexao)
    brutas = carteira._brutas(conexao, itens)
    movs = carteira._movimentos(conexao, itens)
    nomes_b3 = {r["emissor"]: r["nome"] for r in conexao.execute("SELECT emissor, nome FROM ativos_b3")}
    manuais = {r["codigo"]: dict(r) for r in conexao.execute("SELECT * FROM custos_imposto")}
    ativos = {}
    for item_id, i in brutas:
        if i.get("_conta"):  # saldo em conta aplicado pelo banco: vai pelo informe do banco
            continue
        classe, tk, codigo = carteira.classe_investimento(i), carteira.ticker(i), carteira._codigo(i)
        chave = tk if classe in carteira.BOLSA and tk else codigo
        movimentos = movs.get(codigo, [])
        encerrada = carteira.encerrada(i, movimentos, hoje_iso)
        quantidade = 0.0 if encerrada else i.get("quantity")
        a = ativos.get(chave)
        if a:  # o mesmo papel em outra instituição
            a["quantidade"] = (a["quantidade"] or 0) + (quantidade or 0)
            a["movimentos"] = a["movimentos"] or movimentos
            a["instituicoes"].add(itens.get(item_id, {}).get("instituicao"))
            continue
        nome_b3 = nomes_b3.get(b3.emissor(tk)) if tk else None
        categoria, incerta = categoria_fiscal(i, classe, tk, nome_b3)
        ativos[chave] = {
            "codigo": chave, "ticker": tk if classe in carteira.BOLSA else None, "nome": i.get("name"), "nomeB3": nome_b3,
            "classe": classe, "subtipo": i.get("subtype"), "categoriaAuto": categoria, "categoriaIncerta": incerta,
            "quantidade": quantidade, "semQuantidade": i.get("quantity") is None and not encerrada,
            "movimentos": movimentos, "instituicoes": {itens.get(item_id, {}).get("instituicao")},
            "importada": i.get("origem") == "importacao", "dataPosicao": i.get("_dataPosicao"),
            "compra": (i.get("purchaseDate") or "")[:10] or None, "_bruto": i,
            "aplicado": None if encerrada else i.get("amountOriginal"),
            "manual": manuais.get(chave),
        }
    # Início da janela de movimentações: o que já existia antes da primeira movimentação de um ativo da Pluggy
    # foi comprado antes dela, então estava na carteira desde (pelo menos) esse dia.
    janela = min((m["date"][:10] for a in ativos.values() for m in a["movimentos"]), default=None)
    resultado = []
    for a in ativos.values():
        manual = a["manual"] or {}
        a["categoria"] = manual.get("categoria") if manual.get("categoria") in CATEGORIAS else a["categoriaAuto"]
        a["inicioJanela"] = None if a["importada"] else janela
        if a["categoria"] in ("acao", "etf", "bdr", "fii") or a["movimentos"] or (a["quantidade"] or a["semQuantidade"]):
            resultado.append(_calcular(a, hoje_iso))
    return resultado


def _calcular(a, hoje_iso):
    """Custo médio do ativo: vendas com custo, posição ao fim de cada ano e de onde veio o custo."""
    eventos = [m for m in a["movimentos"] if m.get("type") in ("BUY", "SELL", "TAX")]
    sinal = lambda m: {"BUY": 1, "SELL": -1, "TAX": -1}[m["type"]] * (m.get("quantity") or 0)
    liquido = sum(map(sinal, eventos))
    quantidade = 1.0 if a["semQuantidade"] else (a["quantidade"] or 0)  # renda fixa de planilha: só o valor
    q0 = quantidade - liquido  # o que já existia antes da primeira movimentação
    tolerancia = max(0.01, 0.001 * max(quantidade, abs(liquido)))
    semana = (date.fromisoformat(hoje_iso) - timedelta(days=7)).isoformat()
    recente = sum(sinal(m) for m in eventos if m["date"][:10] > semana)
    aviso = None
    if abs(q0) > tolerancia and abs(recente) > TOL and abs(q0 + recente) <= tolerancia:
        q0 = 0.0  # a posição do banco ainda não inclui as negociações dos últimos dias: valem as movimentações
    elif q0 < -tolerancia:
        # Vendas ou resgates que não vieram nas movimentações: a diferença sai da posição hoje, sem entrar na apuração.
        eventos = eventos + [{"type": "AJUSTE", "quantity": -q0, "date": hoje_iso}]
        aviso = "Faltam vendas ou resgates nas movimentações para chegar à quantidade de hoje; a diferença não entra na apuração."
        q0 = 0.0
    elif q0 <= tolerancia:
        q0 = 0.0
    vendas, pontos, come_cotas = _percorrer(eventos, q0)
    primeira = eventos[0]["date"][:10] if eventos else None

    # Custo do lote anterior (c0): informado > valor aplicado do banco > PU inicial de R$ 1,00 (CDB/LCI do Itaú).
    c0, origem = None, "movimentações" if q0 <= TOL else None
    manual = a["manual"] or {}
    if q0 <= TOL and manual.get("custo") is not None:
        aviso = "As movimentações já explicam toda a posição: o custo vem delas, e o valor informado não é usado."
    if q0 > TOL and manual.get("custo") is not None:
        dia = manual.get("data") or hoje_iso
        _, b, coef = _estado(pontos, dia)
        if coef > TOL:
            c0, origem = max(0.0, (manual["custo"] - b) / coef), "informado"
            if manual["custo"] < b - 0.01:
                aviso = "O custo informado é menor que as compras registradas até essa data; confira o valor e a data."
        else:
            aviso = "Nessa data o lote antigo já tinha sido vendido: o custo informado não muda nada. Use uma data anterior."
    if c0 is None and q0 > TOL and a["aplicado"]:
        _, b, coef = _estado(pontos, hoje_iso)
        if coef > TOL:
            c0, origem = max(0.0, (a["aplicado"] - b) / coef), "banco"
    if c0 is None and q0 > TOL and a["subtipo"] in BANCARIOS:
        pus = [m.get("value") for m in eventos if m.get("value")] + [a["_bruto"].get("value")]
        if any(pu and 0.5 <= pu <= 10 for pu in pus):
            c0, origem = q0 * 1.0, "estimado"

    q_hoje, b_hoje, a_hoje = _estado(pontos, hoje_iso)
    custo_hoje = _valor((b_hoje, a_hoje), c0)
    # Desde quando a posição é conhecida: antes disso, Bens e Direitos fica sem valor (não sabemos se já tinha).
    datas_lote = [d for d in (a["compra"], manual.get("data") if manual.get("custo") is not None else None, a["dataPosicao"],
                              a.get("inicioJanela")) if d]
    inicio_lote = min(datas_lote) if datas_lote else None

    def posicao_em(dia):
        """(quantidade, custo) ao fim do dia; None se não dá para saber."""
        if primeira and dia >= primeira:
            q, b, coef = _estado(pontos, dia)
            return q, _valor((b, coef), c0)
        if q0 <= TOL or (a["compra"] and dia < a["compra"]):
            return 0.0, 0.0
        if inicio_lote and dia >= inicio_lote[:10]:
            return q0, c0
        return None

    for v in vendas:
        v["custoValor"] = None if v["excede"] else _valor(v["custo"], c0)
        v["resultado"] = None if v["custoValor"] is None else round(v["valor"] - v["custoValor"], 2)
        v.pop("custo")
    instituicoes = sorted(filter(None, a["instituicoes"]))
    return {
        "codigo": a["codigo"], "ticker": a["ticker"], "nome": a["nome"], "nomeB3": a["nomeB3"], "classe": a["classe"],
        "subtipo": a["subtipo"], "categoria": a["categoria"], "categoriaAuto": a["categoriaAuto"],
        "categoriaIncerta": a["categoriaIncerta"] and not (manual.get("categoria") in CATEGORIAS),
        "instituicao": ", ".join(instituicoes) or None, "importada": a["importada"], "compra": a["compra"],
        "dataPosicao": a["dataPosicao"],
        "quantidade": None if a["semQuantidade"] else round(q_hoje, 6), "semQuantidade": a["semQuantidade"],
        "quantidadeInicial": round(q0, 6), "primeiraMovimentacao": primeira,
        "custo": round(custo_hoje, 2) if custo_hoje is not None else None,
        "precoMedio": custo_hoje / q_hoje if custo_hoje is not None and q_hoje > TOL and not a["semQuantidade"] else None,
        "origemCusto": origem if q_hoje > TOL or vendas else None,
        # Fora da bolsa, posição já encerrada não pede custo: o rendimento e o IR saem no informe do banco.
        "precisaCusto": q0 > TOL and c0 is None and (CATEGORIAS[a["categoria"]]["grupo"] is not None or q_hoje > TOL),
        "manual": {"data": manual.get("data"), "custo": manual.get("custo")} if manual.get("custo") is not None else None,
        "aviso": aviso, "vendas": vendas, "comeCotas": come_cotas,
        "_posicao": posicao_em, "_bruto": a["_bruto"], "_movimentos": a["movimentos"],
    }


# ============================================================================ apuração mensal
def _meses(inicio, fim):
    meses, m = [], inicio
    while m <= fim:
        meses.append(m)
        m = carteira._somar_meses(m, 1)
    return meses


def apurar(ativos, prejuizo_inicial, hoje_iso):
    """Mês a mês, da primeira venda em bolsa até hoje: resultado por grupo, compensação, imposto e DARF."""
    vendas = []
    for a in ativos:
        grupo = CATEGORIAS[a["categoria"]]["grupo"]
        if grupo:
            vendas += [{**v, "ativo": a["ticker"] or a["codigo"], "categoria": a["categoria"], "grupo": grupo,
                        "semCusto": v["resultado"] is None} for v in a["vendas"]]
    if not vendas:
        return []
    compras_por_dia = {(a["ticker"], m["date"][:10]) for a in ativos for m in a["_movimentos"] if m.get("type") == "BUY"}
    por_mes = defaultdict(list)
    for v in vendas:
        por_mes[v["data"][:7]].append(v)
    prejuizo = {"comum": prejuizo_inicial.get("comum") or 0.0, "fii": prejuizo_inicial.get("fii") or 0.0}
    acumulado, irrf_sobra, ano_irrf = 0.0, 0.0, None
    resultado = []
    for mes in _meses(min(por_mes), hoje_iso[:7]):
        lista = sorted(por_mes.get(mes, []), key=lambda v: (v["data"], v["ativo"]))
        if mes[:4] != ano_irrf:  # o IRRF que sobra só se compensa dentro do ano
            ano_irrf, irrf_sobra = mes[:4], 0.0
        acoes = [v for v in lista if v["categoria"] == "acao"]
        vendas_acoes = sum(v["valor"] for v in acoes)
        isento = vendas_acoes <= LIMITE_ISENCAO_ACOES
        ganho_acoes = sum(v["resultado"] or 0 for v in acoes)
        ganho_outros = sum(v["resultado"] or 0 for v in lista if v["categoria"] in ("etf", "bdr"))
        ganho_fii = sum(v["resultado"] or 0 for v in lista if v["grupo"] == "fii")
        # Mês isento: o ganho com ações sai da conta (vai para os isentos da declaração); o prejuízo continua compensável.
        ganho_isento = ganho_acoes if isento and ganho_acoes > 0 else 0.0
        resultados = {"comum": ganho_outros + ganho_acoes - ganho_isento, "fii": ganho_fii}
        linha = {"mes": mes, "vendasAcoes": round(vendas_acoes, 2), "isento": isento and bool(acoes),
                 "vendasTotal": round(sum(v["valor"] for v in lista), 2), "ganhoAcoes": round(ganho_acoes, 2),
                 "ganhoOutros": round(ganho_outros, 2), "ganhoFii": round(ganho_fii, 2), "ganhoIsento": round(ganho_isento, 2)}
        imposto_total = 0.0
        for grupo in ("comum", "fii"):
            base = resultados[grupo]
            compensado = 0.0
            if base > 0:
                compensado = min(base, prejuizo[grupo])
                base -= compensado
                prejuizo[grupo] -= compensado
            elif base < 0:
                prejuizo[grupo] -= base
                base = 0.0
            imposto = base * ALIQUOTA[grupo]
            imposto_total += imposto
            linha.update({f"resultado{grupo.title()}": round(resultados[grupo], 2), f"compensado{grupo.title()}": round(compensado, 2),
                          f"base{grupo.title()}": round(base, 2), f"imposto{grupo.title()}": round(imposto, 2),
                          f"prejuizo{grupo.title()}": round(prejuizo[grupo], 2)})
        # Dedo-duro: 0,005% das vendas de cada dia (nota de corretagem), quando passa de R$ 1,00.
        por_dia = defaultdict(float)
        for v in lista:
            por_dia[v["data"]] += v["valor"]
        irrf = sum(round(t * DEDO_DURO, 2) for t in por_dia.values() if t * DEDO_DURO > 1.0)
        irrf_disponivel = irrf + irrf_sobra
        irrf_usado = min(imposto_total, irrf_disponivel)
        irrf_sobra = irrf_disponivel - irrf_usado
        devido = imposto_total - irrf_usado + acumulado
        darf = round(devido, 2) if devido >= DARF_MINIMO else 0.0
        acumulado_antes, acumulado = acumulado, (0.0 if darf else devido)
        vencimento = ultimo_dia_util(carteira._somar_meses(mes, 1)) if darf else None
        avisos = []
        if any(v["semCusto"] for v in lista):
            avisos.append("Venda sem custo conhecido: " + ", ".join(sorted({v["ativo"] for v in lista if v["semCusto"]}))
                          + ". Informe o custo em “Custo dos ativos” para completar a conta.")
        day_trade = sorted({v["ativo"] for v in lista if (v["ativo"], v["data"]) in compras_por_dia})
        if day_trade:
            avisos.append(f"Compra e venda no mesmo dia ({', '.join(day_trade)}): pode ser day trade, que tem alíquota de 20% "
                          "e apuração separada. Aqui entrou como operação comum.")
        linha.update({
            "irrf": round(irrf, 2), "irrfUsado": round(irrf_usado, 2), "imposto": round(imposto_total, 2),
            "acumuladoAnterior": round(acumulado_antes, 2), "acumulado": round(acumulado, 2), "darf": darf,
            "codigo": CODIGO_DARF if darf else None, "vencimento": vencimento,
            "situacao": None if not darf else ("vencido" if vencimento < hoje_iso else "a pagar"),
            "emAndamento": mes == hoje_iso[:7], "incompleto": any(v["semCusto"] for v in lista),
            "vendas": [{k: v[k] for k in ("data", "ativo", "categoria", "quantidade", "valor", "custoValor", "resultado")}
                       for v in lista], "avisos": avisos,
        })
        resultado.append(linha)
    return resultado


# ============================================================================ proventos
def _proventos(conexao, itens, transacoes, ativos, hoje_iso):
    """Proventos recebidos: anunciados na B3 × quantidade na data com (dá o tipo e o valor bruto), conferidos com o que
    caiu na conta (movimentações INTEREST e extrato). O que só aparece na conta entra com o tipo que dá para inferir."""
    brutas = carteira._brutas(conexao, itens)
    movs = carteira._movimentos(conexao, itens)
    b3_por_emissor, _ = b3.carregar(conexao)
    grupos = carteira._bolsa(brutas, movs, b3_por_emissor, set(b3.tipos(conexao)), hoje_iso)
    categorias = {a["ticker"]: a["categoria"] for a in ativos if a["ticker"]}
    nomes_b3 = {a["ticker"]: a["nomeB3"] for a in ativos if a["ticker"]}
    posicao_em = {a["ticker"]: a["dataPosicao"] for a in ativos if a["ticker"]}
    lista = []
    for tk, g in grupos.items():
        suposto = g["importada"] and not g["movimentos"]
        # Planilha sem compras e vendas: supõe a quantidade de hoje, mas só nos 12 meses antes da data da posição.
        limite = (date.fromisoformat((posicao_em.get(tk) or hoje_iso)[:10]) - timedelta(days=365)).isoformat() if suposto else ""
        for p in g["proventos"]:
            if p["tipo"] == "AMORTIZACAO" or not p["pagamento"] or p["pagamento"] > hoje_iso or p["data_com"] < limite:
                continue
            q = carteira._quantidade_no_dia(g["quantidade"], g["movimentos"], p["data_com"])
            if q <= TOL:
                continue
            bruto = q * p["valor"]
            tipo = {"DIVIDENDO": "dividendos", "JRS CAP PROPRIO": "jcp"}.get(p["tipo"])
            if not tipo:
                tipo = "fii" if g["classe"] == "fiis" and categorias.get(tk) != "isento" else "outros"
            ir = bruto * aliquota_jcp(p["aprovado_em"] or p["data_com"]) if tipo == "jcp" else 0.0
            lista.append({"data": p["pagamento"], "dataCom": p["data_com"], "aprovadoEm": p["aprovado_em"], "codigo": tk,
                          "pagador": nomes_b3.get(tk), "tipo": tipo, "bruto": round(bruto, 2), "ir": round(ir, 2),
                          "liquido": round(bruto - ir, 2), "quantidade": q, "porCota": p["valor"], "fonte": "b3",
                          "conferido": False, "suposto": suposto, "categoria": categorias.get(tk)})
    nomes = {carteira._codigo(i): carteira.ticker(i) or carteira._codigo(i) for _, i in brutas}
    conta = []
    for r in carteira._proventos(movs, transacoes, nomes, hoje_iso):
        tk = r["codigo"]
        if not tk:  # rendimento do extrato sem ticker: aplicação automática da conta e afins
            conta.append({"data": r["data"], "valor": r["valor"], "origem": r["origem"]})
            continue
        if tk not in grupos and not carteira.RE_TICKER_B3.match(tk):
            continue  # cupom de título ou rendimento de fundo: entra na renda fixa
        classe = grupos[tk]["classe"] if tk in grupos else None
        perto = [p for p in lista if p["codigo"] == tk and not p["conferido"]
                 and abs((date.fromisoformat(p["data"]) - date.fromisoformat(r["data"])).days) <= 10]
        par = next((p for p in perto if min(abs(r["valor"] - p["bruto"]), abs(r["valor"] - p["liquido"])) <= max(0.05, 0.02 * p["bruto"])), None)
        if par:
            par.update(conferido=True, recebido=r["valor"])
            continue
        # Quantidade suposta (planilha) e valor diferente: vale o que caiu na conta, com o tipo que a B3 informa.
        par = next((p for p in perto if p.get("suposto")), None)
        if par:
            ir = r["valor"] / (1 - aliquota_jcp(par["aprovadoEm"] or par["dataCom"])) - r["valor"] if par["tipo"] == "jcp" else 0.0
            par.update(conferido=True, recebido=r["valor"], suposto=False, bruto=round(r["valor"] + ir, 2), ir=round(ir, 2),
                       liquido=r["valor"])
            continue
        tipo = "fii" if classe == "fiis" and categorias.get(tk) != "isento" else {"Dividendos": "dividendos", "JCP": "jcp"}.get(r["tipo"], "outros")
        ir = r["valor"] / (1 - aliquota_jcp(r["data"])) - r["valor"] if tipo == "jcp" else 0.0
        lista.append({"data": r["data"], "codigo": tk, "pagador": nomes_b3.get(tk), "tipo": tipo, "bruto": round(r["valor"] + ir, 2),
                      "ir": round(ir, 2), "liquido": r["valor"], "fonte": "conta", "conferido": True, "recebido": r["valor"],
                      "categoria": categorias.get(tk)})
    return sorted(lista, key=lambda p: (p["data"], p["codigo"])), conta


def _alertas_dividendos(proventos, ano):
    """Lei 15.270/2025: mais de R$ 50 mil de dividendos da mesma empresa no mesmo mês → 10% retidos sobre o total."""
    if ano < 2026:
        return []
    por_mes = defaultdict(list)
    for p in proventos:
        if p["tipo"] == "dividendos" and p["data"][:4] == str(ano):
            por_mes[(b3.emissor(p["codigo"]) or p["codigo"], p["data"][:7])].append(p)
    alertas = []
    for (emissor, mes), lista in sorted(por_mes.items()):
        total = sum(p["bruto"] for p in lista)
        if total > LIMITE_DIVIDENDOS_MES:
            transicao = all((p.get("aprovadoEm") or "9999") <= "2025-12-31" for p in lista)
            alertas.append({"emissor": emissor, "pagador": lista[0]["pagador"], "mes": mes, "total": round(total, 2),
                            "retencao": 0.0 if transicao else round(total * RETENCAO_DIVIDENDOS, 2), "transicao": transicao})
    return alertas


# ============================================================================ renda fixa e fundos
def _renda_fixa(ativos, conta, ano):
    """Resgates, cupons e come-cotas do ano fora da bolsa: o rendimento e o IR retido que o informe do banco deve mostrar."""
    linhas = []
    for a in ativos:
        if a["classe"] not in ("tesouro", "renda_fixa", "fundos"):
            continue
        isento = a["subtipo"] in RENDA_FIXA_ISENTA or (a["classe"] == "fundos" and RE_INFRA.search(regras.normalizar(a["nome"])))
        for v in a["vendas"]:
            if v["data"][:4] != str(ano):
                continue
            ir = max(0.0, v["valor"] - v["liquido"])
            rendimento, estimado = v["resultado"], a["origemCusto"] == "estimado"
            if rendimento is None and ir > 0.005 and a["compra"] and a["classe"] != "fundos":
                rendimento, estimado = ir / _aliquota_regressiva(a["compra"], v["data"]), True
            linhas.append({"data": v["data"], "ativo": a["nome"], "classe": a["classe"], "tipo": "resgate", "isento": bool(isento),
                           "bruto": round(v["valor"], 2), "ir": round(ir, 2),
                           "rendimento": round(rendimento, 2) if rendimento is not None else None, "estimado": estimado})
        for m in a["_movimentos"]:
            if m.get("type") == "INTEREST" and m["date"][:4] == str(ano):
                valor, liquido = m.get("amount") or 0, m.get("netAmount") or m.get("amount") or 0
                linhas.append({"data": m["date"][:10], "ativo": a["nome"], "classe": a["classe"], "tipo": "juros",
                               "isento": bool(isento), "bruto": round(valor, 2), "ir": round(max(0.0, valor - liquido), 2),
                               "rendimento": round(valor, 2), "estimado": False})
        for c in a["comeCotas"]:
            if c["data"][:4] == str(ano):
                linhas.append({"data": c["data"], "ativo": a["nome"], "classe": a["classe"], "tipo": "come-cotas",
                               "isento": False, "bruto": 0.0, "ir": round(c["valor"], 2), "rendimento": None, "estimado": False})
    creditado = [c for c in conta if c["data"][:4] == str(ano)]
    return sorted(linhas, key=lambda x: x["data"]), round(sum(c["valor"] for c in creditado), 2)


# ============================================================================ declaração anual
def _bens(ativos, ano, hoje_iso):
    """Bens e Direitos: custo em 31/12 do ano anterior e do ano (no ano corrente, a posição de hoje como prévia)."""
    fim = f"{ano}-12-31"
    atual = fim if fim < hoje_iso else hoje_iso
    linhas = []
    for a in ativos:
        antes, depois = a["_posicao"](f"{ano - 1}-12-31"), a["_posicao"](atual)
        if not any(p and (p[0] > TOL or (a["semQuantidade"] and p[1])) for p in (antes, depois)):
            continue
        codigo = _codigo_bem(a)

        def situacao(p):
            if p is None:
                return {"quantidade": None, "custo": None, "desconhecido": True}
            q, custo = p
            if q <= TOL:
                return {"quantidade": 0.0, "custo": 0.0, "desconhecido": False}
            return {"quantidade": None if a["semQuantidade"] else round(q, 6),
                    "custo": round(custo, 2) if custo is not None else None, "desconhecido": False}

        s_antes, s_depois = situacao(antes), situacao(depois)
        linhas.append({
            "codigo": a["codigo"], "ticker": a["ticker"], "nome": a["nome"], "nomeB3": a["nomeB3"], "classe": a["classe"],
            "categoria": a["categoria"], "instituicao": a["instituicao"],
            "grupo": codigo[0] if codigo else None, "codigoBem": codigo[1] if codigo else None, "nomeBem": codigo[2] if codigo else None,
            "anterior": s_antes, "atual": s_depois, "discriminacao": _discriminacao(a, s_depois if s_depois["quantidade"] else s_antes),
        })
    ordem = {"03": 0, "07": 1, "04": 2, "08": 3}
    return sorted(linhas, key=lambda l: (ordem.get(l["grupo"], 9), l["codigoBem"] or "", l["ticker"] or l["nome"] or ""))


def _discriminacao(a, s):
    """Texto sugerido para o campo Discriminação."""
    q = s.get("quantidade")
    unidade = {"acao": "ações", "fii": "cotas", "etf": "cotas", "isento": "cotas", "bdr": "BDRs"}.get(a["categoria"], "cotas")
    numero = lambda v: f"{v:,.6f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
    partes = []
    if a["ticker"]:
        partes.append(f"{numero(q)} {unidade} {a['ticker']}" if q else a["ticker"])
        if a["nomeB3"]:
            partes.append(a["nomeB3"])
        if q and s.get("custo"):
            partes.append("preço médio R$ " + f"{s['custo'] / q:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    else:
        partes.append(a["nome"] or a["codigo"])
        if a["classe"] == "fundos" and re.match(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", a["codigo"] or ""):
            partes.append(f"CNPJ {a['codigo']}")
        if a["subtipo"] in BANCARIOS or a["classe"] == "tesouro":
            compra = a["_bruto"].get("purchaseDate")
            if compra:
                partes.append(f"aplicado em {compra[8:10]}/{compra[5:7]}/{compra[:4]}")
    if a["instituicao"]:
        partes.append(f"custódia: {a['instituicao']}")
    return " – ".join(partes)


def _por_ano(ativos, meses, proventos, conta, prejuizo_inicial, ano, hoje_iso):
    do_ano = [m for m in meses if m["mes"][:4] == str(ano)]
    provs = [p for p in proventos if p["data"][:4] == str(ano)]
    renda_fixa, creditado = _renda_fixa(ativos, conta, ano)
    soma = lambda lista, campo: round(sum(x[campo] or 0 for x in lista), 2)
    por_pagador = defaultdict(lambda: {"bruto": 0.0, "ir": 0.0, "liquido": 0.0, "pagamentos": 0})
    for p in provs:
        g = por_pagador[(p["tipo"], p["codigo"])]
        g["pagador"] = p.get("pagador")
        g["bruto"] += p["bruto"]
        g["ir"] += p["ir"]
        g["liquido"] += p["liquido"]
        g["pagamentos"] += 1
        g["suposto"] = g.get("suposto") or p.get("suposto", False)
        g["naoConferido"] = g.get("naoConferido", 0) + (0 if p["conferido"] else 1)
    pagadores = sorted(({"tipo": t, "codigo": c, **{k: round(v, 2) if isinstance(v, float) else v for k, v in g.items()}}
                        for (t, c), g in por_pagador.items()), key=lambda x: (x["tipo"], -x["bruto"]))
    rf_exclusiva = [x for x in renda_fixa if not x["isento"]]
    rf_isenta = [x for x in renda_fixa if x["isento"]]
    # Prejuízo no fim do ano (ou hoje): o do último mês apurado; sem vendas ainda, o que você informou da declaração anterior.
    ultimo = next((m for m in reversed(meses) if m["mes"][:4] <= str(ano)), None)
    inicial = prejuizo_inicial if any(prejuizo_inicial.values()) else {"comum": None, "fii": None}
    return {
        "rendaVariavel": {
            "vendas": soma(do_ano, "vendasTotal"), "ganhoIsento": soma(do_ano, "ganhoIsento"), "imposto": soma(do_ano, "imposto"),
            "darfs": soma(do_ano, "darf"), "irrf": soma(do_ano, "irrf"),
            "prejuizoComum": ultimo["prejuizoComum"] if ultimo else inicial["comum"],
            "prejuizoFii": ultimo["prejuizoFii"] if ultimo else inicial["fii"],
            "acumulado": ultimo["acumulado"] if ultimo and ultimo["mes"][:4] == str(ano) else 0.0,
        },
        "bens": _bens(ativos, ano, hoje_iso),
        "proventos": provs, "pagadores": pagadores,
        "isentos": {
            "dividendos": soma([p for p in provs if p["tipo"] == "dividendos"], "bruto"),
            "fii": soma([p for p in provs if p["tipo"] == "fii"], "bruto"),
            "ganhoAcoes": soma(do_ano, "ganhoIsento"),
            "rendaFixa": soma([x for x in rf_isenta if x["rendimento"]], "rendimento"),
            "outros": soma([p for p in provs if p["tipo"] == "outros"], "bruto"),
        },
        "exclusivos": {
            "jcpBruto": soma([p for p in provs if p["tipo"] == "jcp"], "bruto"),
            "jcpIr": soma([p for p in provs if p["tipo"] == "jcp"], "ir"),
            "jcpLiquido": soma([p for p in provs if p["tipo"] == "jcp"], "liquido"),
            "rendaFixaRendimento": soma([x for x in rf_exclusiva if x["rendimento"]], "rendimento"),
            # Líquido só dos lançamentos com rendimento calculado; o IR dos demais (fundos, come-cotas) fica à parte.
            "rendaFixaLiquido": round(sum(x["rendimento"] - x["ir"] for x in rf_exclusiva if x["rendimento"]), 2),
            "rendaFixaIr": soma(rf_exclusiva, "ir"),
            "rendaFixaSemRendimento": sum(1 for x in rf_exclusiva if x["rendimento"] is None and x["tipo"] == "resgate"),
            "creditadoConta": creditado,
        },
        "rendaFixa": renda_fixa,
        "alertasDividendos": _alertas_dividendos(proventos, ano),
    }


def montar(conexao, itens, transacoes, hoje):
    hoje_iso = hoje.isoformat()
    ativos = _ativos(conexao, itens, hoje_iso)
    prejuizo_inicial = {g: float(preferencia(conexao, f"imposto_prejuizo_{g}") or 0) for g in ("comum", "fii")}
    meses = apurar(ativos, prejuizo_inicial, hoje_iso)
    proventos, conta = _proventos(conexao, itens, transacoes, ativos, hoje_iso)
    datas = ([m["mes"] for m in meses] + [p["data"] for p in proventos]
             + [a["primeiraMovimentacao"] for a in ativos if a["primeiraMovimentacao"]])
    primeiro_ano = int(min(datas)[:4]) if datas else hoje.year
    anos = list(range(max(primeiro_ano, hoje.year - 4), hoje.year + 1))
    # Até maio o que interessa é a declaração do ano anterior; depois, o ano em curso.
    padrao = hoje.year - 1 if hoje.month <= 5 and hoje.year - 1 in anos else hoje.year
    pendentes = [m for m in meses if m["darf"] and m["situacao"] == "a pagar"]
    return {
        "hoje": hoje_iso, "anos": anos, "anoPadrao": padrao,
        # Custo dos ativos: os de bolsa, os que ainda têm posição e os que precisam de custo para fechar a conta.
        "ativos": [{k: v for k, v in a.items() if not k.startswith("_") and k not in ("vendas", "comeCotas")}
                   | {"vendas": len(a["vendas"])} for a in ativos
                   if a["classe"] in carteira.BOLSA or a["precisaCusto"] or a["manual"] or (a["quantidade"] or a["semQuantidade"])],
        "prejuizoInicial": {**prejuizo_inicial, "desde": meses[0]["mes"] if meses else None},
        "meses": meses,
        "proximoDarf": pendentes[0] if pendentes else None,
        "porAno": {str(ano): _por_ano(ativos, meses, proventos, conta, prejuizo_inicial, ano, hoje_iso) for ano in anos},
        "categorias": {k: v["nome"] for k, v in CATEGORIAS.items()},
        "parametros": {"limiteIsencao": LIMITE_ISENCAO_ACOES, "darfMinimo": DARF_MINIMO, "codigoDarf": CODIGO_DARF,
                       "aliquotaComum": ALIQUOTA["comum"], "aliquotaFii": ALIQUOTA["fii"],
                       "aliquotaJcp": aliquota_jcp(hoje_iso), "limiteDividendos": LIMITE_DIVIDENDOS_MES},
    }


# ============================================================================ o que você informa
def salvar_custo(conexao, corpo):
    """Custo total do ativo numa data (o resto sai do custo médio) e/ou a categoria para o IR. custo null = apagar."""
    garantir_tabelas(conexao)
    codigo = str(corpo.get("codigo") or "").strip()
    if not codigo:
        raise ValueError("ativo não informado")
    atual = conexao.execute("SELECT * FROM custos_imposto WHERE codigo = ?", (codigo,)).fetchone()
    novo = dict(atual) if atual else {"data": None, "custo": None, "categoria": None}
    if "custo" in corpo:
        custo = corpo["custo"]
        if custo in (None, ""):
            novo["custo"], novo["data"] = None, None
        else:
            custo = float(custo)
            if custo < 0:
                raise ValueError("o custo não pode ser negativo")
            data = str(corpo.get("data") or date.today().isoformat())[:10]
            date.fromisoformat(data)  # valida
            novo["custo"], novo["data"] = round(custo, 2), data
    if "categoria" in corpo:
        categoria = corpo["categoria"] or None
        if categoria not in (None, *CATEGORIAS):
            raise ValueError(f"categoria inválida: {categoria}")
        novo["categoria"] = categoria
    with conexao:
        if novo["custo"] is None and not novo["categoria"]:
            conexao.execute("DELETE FROM custos_imposto WHERE codigo = ?", (codigo,))
        else:
            conexao.execute("INSERT OR REPLACE INTO custos_imposto (codigo, data, custo, categoria, atualizado_em) VALUES (?, ?, ?, ?, ?)",
                            (codigo, novo["data"], novo["custo"], novo["categoria"], datetime.now().isoformat(timespec="seconds")))
    return {"ok": True}


def salvar_prejuizo(conexao, corpo):
    """Prejuízo a compensar de antes das movimentações (o da última declaração), por grupo."""
    for grupo in ("comum", "fii"):
        if grupo in corpo:
            valor = corpo[grupo]
            valor = None if valor in (None, "") else float(valor)
            if valor is not None and valor < 0:
                raise ValueError("informe o prejuízo como um número positivo")
            gravar_preferencia(conexao, f"imposto_prejuizo_{grupo}", round(valor, 2) if valor else None)
    return {"ok": True}
