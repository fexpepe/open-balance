"""Histórico diário da carteira — base das sub-abas Rentabilidade e Risco.

Reconstrói o valor de cada posição em cada dia útil e a rentabilidade da carteira pelo método de cotas
(o mesmo do Investidor10 e do Kinvo: aportes e resgates não contam como ganho), com os índices de
comparação na mesma régua de datas.

    Tesouro Direto     quantidade × preço de venda oficial do dia (Tesouro Transparente)
    CDB, LCI, LCA      preço de hoje recuado pela taxa contratada: % do CDI diário (Ipeadata), IPCA + taxa ou prefixado
    ações, ETF, FII    quantidade × fechamento do dia (Yahoo Finance); a rentabilidade usa o fechamento ajustado,
                       que já inclui dividendos e JCP
    fundos             cotas × valor da cota (informe diário da CVM)
    saldo em conta     o saldo guardado a cada sincronização (só desde que o Open Balance passou a guardá-lo)
    quantidades        recuadas a partir de hoje pelas compras, vendas e come-cotas (movimentações da Pluggy)
    índices            CDI e IPCA (Ipeadata); Ibovespa, IFIX (pelo ETF XFIX11), dólar e S&P 500 em reais (Yahoo)

Antes da primeira movimentação conhecida, supõe que a quantidade não mudou desde a data de compra (ou desde
o início do histórico, quando o banco não informa a data): esse trecho volta marcado como estimado.

As cotações ficam no banco (tabela series_diarias) e são atualizadas no máximo uma vez por dia, numa thread
com conexão própria, para o painel não travar enquanto baixa (a primeira carga dos fundos baixa ~11 MB por mês).
"""

import csv
import io
import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import carteira, regras
from .analise import itens_visiveis

ESQUEMA = """
CREATE TABLE IF NOT EXISTS series_diarias (serie TEXT, data TEXT, valor REAL, PRIMARY KEY (serie, data));
"""
URL_YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}"
             "&interval=1d&includeAdjustedClose=true")
URL_CDI_DIARIO = "http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='SGS366_CDI366')"
URL_CVM = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{}.zip"
USER_AGENT = "Mozilla/5.0 (open-balance)"

# Índices do Yahoo usados na comparação. O IFIX não tem histórico no Yahoo: vai pelo ETF que o replica.
SIMBOLOS_REFERENCIA = {"ibov": "^BVSP", "ifix": "XFIX11.SA", "dolar": "BRL=X", "sp500": "^GSPC"}
ANOS_MAXIMOS = 5
DIAS_UTEIS_ANO = 252


def garantir_tabelas(conexao):
    carteira.garantir_tabelas(conexao)
    conexao.executescript(ESQUEMA)


# ============================================================================ download
def _baixar(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        return resposta.read()


def baixar_yahoo(simbolo, desde):
    """Fechamento e fechamento ajustado (com proventos) de cada pregão: [(data, fechamento, ajustado)]."""
    inicio = int(datetime.fromisoformat(desde).replace(tzinfo=timezone.utc).timestamp())
    fim = int(datetime.now(timezone.utc).timestamp()) + 86400
    dados = json.loads(_baixar(URL_YAHOO.format(urllib.parse.quote(simbolo, safe=""), inicio, fim)))
    resultado = ((dados.get("chart") or {}).get("result") or [None])[0]
    if not resultado or not resultado.get("timestamp"):
        return []
    deslocamento = (resultado.get("meta") or {}).get("gmtoffset") or 0
    fechamentos = resultado["indicators"]["quote"][0].get("close") or []
    ajustados = ((resultado["indicators"].get("adjclose") or [{}])[0].get("adjclose")) or fechamentos
    por_dia = {}
    for ts, fechamento, ajustado in zip(resultado["timestamp"], fechamentos, ajustados):
        if fechamento:
            dia = datetime.fromtimestamp(ts + deslocamento, timezone.utc).date().isoformat()
            por_dia[dia] = (dia, fechamento, ajustado or fechamento)
    return sorted(por_dia.values())


def baixar_cdi_diario(desde):
    """CDI de cada dia útil, em % ao dia."""
    dados = json.loads(_baixar(URL_CDI_DIARIO))
    return [(v["VALDATA"][:10], float(v["VALVALOR"])) for v in dados.get("value", [])
            if v.get("VALVALOR") is not None and v["VALDATA"][:10] >= desde]


def baixar_cvm_mes(mes, cnpjs):
    """Valor da cota de cada fundo em cada dia do mês ('AAAA-MM'), pelo informe diário da CVM: {cnpj: [(data, cota)]}.
    Fundos com subclasses: fica a cota da classe (linha sem subclasse) ou, na falta dela, a da primeira subclasse."""
    conteudo = _baixar(URL_CVM.format(mes.replace("-", "")), timeout=300)
    por_fundo = defaultdict(lambda: defaultdict(list))
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        for nome in pacote.namelist():
            with pacote.open(nome) as arquivo:
                leitor = csv.reader(io.TextIOWrapper(arquivo, encoding="latin-1"), delimiter=";")
                cabecalho = next(leitor)
                col_cnpj = cabecalho.index("CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in cabecalho else "CNPJ_FUNDO")
                col_data, col_cota = cabecalho.index("DT_COMPTC"), cabecalho.index("VL_QUOTA")
                col_sub = cabecalho.index("ID_SUBCLASSE") if "ID_SUBCLASSE" in cabecalho else None
                for linha in leitor:
                    if linha[col_cnpj] in cnpjs:
                        sub = linha[col_sub] if col_sub is not None else ""
                        por_fundo[linha[col_cnpj]][sub].append((linha[col_data], float(linha[col_cota])))
    return {cnpj: subs[""] if "" in subs else subs[sorted(subs)[0]] for cnpj, subs in por_fundo.items()}


# ============================================================================ atualização (thread própria)
_progresso = {"rodando": False, "etapa": "", "feitas": 0, "total": 0, "erros": [], "inicio": None, "fim": None}
_trava_progresso = threading.Lock()


def progresso():
    with _trava_progresso:
        return {**_progresso, "erros": list(_progresso["erros"])}


def _anotar(etapa=None, total=None, feita=False, erro=None):
    with _trava_progresso:
        if etapa is not None:
            _progresso["etapa"] = etapa
        if total is not None:
            _progresso["total"] = total
        if feita:
            _progresso["feitas"] += 1
        if erro:
            _progresso["erros"].append(erro)


def iniciar_atualizacao(conexao, forcar=False):
    """Atualiza as cotações em segundo plano. Não repete se já rodou nos últimos 10 minutos (cada série
    também só é baixada uma vez por dia). Devolve True se começou agora."""
    with _trava_progresso:
        if _progresso["rodando"]:
            return False
        recente = _progresso["fim"] and datetime.now() - datetime.fromisoformat(_progresso["fim"]) < timedelta(minutes=10)
        if recente and not forcar:
            return False
        _progresso.update(rodando=True, etapa="começando", feitas=0, total=0, erros=[],
                          inicio=datetime.now().isoformat(timespec="seconds"))
    caminho = conexao.execute("PRAGMA database_list").fetchone()[2]
    threading.Thread(target=_atualizar_em_segundo_plano, args=(caminho,), daemon=True, name="historico").start()
    return True


def _atualizar_em_segundo_plano(caminho):
    conexao = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    try:
        atualizar_fontes(conexao, _anotar)
    except Exception as e:  # noqa: BLE001 — o painel continua com o que já estava guardado
        _anotar(erro=f"{type(e).__name__}: {e}")
    finally:
        conexao.close()
        with _trava_progresso:
            _progresso.update(rodando=False, etapa="", fim=datetime.now().isoformat(timespec="seconds"))


def atualizar_fontes(conexao, anotar=lambda **_: None):
    """Baixa o que o histórico precisa e ainda não foi baixado hoje."""
    garantir_tabelas(conexao)
    hoje = date.today()
    posicoes, _ = _posicoes(conexao, itens_visiveis(conexao), hoje.isoformat())
    if not posicoes:
        return
    inicio = _inicio(posicoes, hoje)
    simbolos = sorted({p["fonte"]["simbolo"] for p in posicoes if p["fonte"]["tipo"] == "yahoo"} | set(SIMBOLOS_REFERENCIA.values()))
    cnpjs = sorted({p["fonte"]["cnpj"] for p in posicoes if p["fonte"]["tipo"] == "cvm"})
    tarefas = [("CDI e IPCA mensais", lambda: carteira.atualizar_indices(conexao)),
               ("CDI diário", lambda: _atualizar_cdi(conexao, inicio, hoje)),
               ("Proventos anunciados (B3)", lambda: _atualizar_b3(conexao))]
    if any(p["fonte"]["tipo"] == "tesouro" for p in posicoes):
        tarefas.append(("Preços do Tesouro Direto", lambda: _atualizar_tesouro(conexao, inicio)))
    tarefas += [(f"Cotações de {s}", lambda s=s: _atualizar_yahoo(conexao, s, inicio, hoje)) for s in simbolos]
    if cnpjs:
        tarefas += [(f"Cotas dos fundos ({m[5:]}/{m[:4]})", lambda m=m: _atualizar_cvm(conexao, m, cnpjs, hoje))
                    for m in _meses_cvm_pendentes(conexao, inicio, cnpjs, hoje)]
    anotar(total=len(tarefas))
    for nome, tarefa in tarefas:
        anotar(etapa=nome)
        try:
            tarefa()
        except Exception as e:  # noqa: BLE001 — fonte fora do ar: fica o que já estava guardado
            anotar(erro=f"{nome}: {type(e).__name__}: {e}")
        anotar(feita=True)


def _status(conexao, serie):
    return conexao.execute("SELECT atualizado_em, fonte FROM indices_status WHERE serie = ?", (serie,)).fetchone()


def _gravar_serie(conexao, serie, pontos, fonte):
    """Troca a série inteira (o fechamento ajustado muda para trás a cada novo provento)."""
    with conexao:
        conexao.execute("DELETE FROM series_diarias WHERE serie = ?", (serie,))
        conexao.executemany("INSERT OR REPLACE INTO series_diarias (serie, data, valor) VALUES (?, ?, ?)",
                            [(serie, d, v) for d, v in pontos])
        _gravar_status(conexao, serie, fonte)


def _gravar_status(conexao, serie, fonte):
    conexao.execute("INSERT OR REPLACE INTO indices_status (serie, atualizado_em, fonte) VALUES (?, ?, ?)",
                    (serie, datetime.now().isoformat(timespec="seconds"), fonte))


def _em_dia(conexao, serie, hoje):
    status = _status(conexao, serie)
    return bool(status) and status["atualizado_em"][:10] == hoje.isoformat()


def _atualizar_cdi(conexao, inicio, hoje):
    if _em_dia(conexao, "cdi_diario", hoje):
        return
    pontos = baixar_cdi_diario(min(inicio, "2015-01-01"))
    if pontos:
        _gravar_serie(conexao, "cdi_diario", pontos, "ipeadata")


def _atualizar_b3(conexao):
    # Também roda aqui porque sem Pluggy não há sincronização: é o único caminho para quem só importa arquivos.
    erros = carteira.atualizar_proventos_b3(conexao, itens_visiveis(conexao))["erros"]
    if erros:
        raise RuntimeError("; ".join(erros[:3]))


def _atualizar_tesouro(conexao, inicio):
    # A tabela guarda desde 2024; histórico mais antigo que isso força baixar de novo a partir do início.
    desde = min(inicio, "2024-01-01")
    menor = conexao.execute("SELECT min(data) FROM precos_tesouro").fetchone()[0]
    forcar = menor is None or menor > (date.fromisoformat(desde) + timedelta(days=7)).isoformat()
    carteira.atualizar_precos_tesouro(conexao, forcar=forcar, desde=desde)


def _atualizar_yahoo(conexao, simbolo, inicio, hoje):
    if _em_dia(conexao, f"yahoo:{simbolo}", hoje):
        return
    linhas = baixar_yahoo(simbolo, (date.fromisoformat(inicio) - timedelta(days=10)).isoformat())
    if not linhas:
        raise RuntimeError("sem cotações")
    _gravar_serie(conexao, f"yahoo_aj:{simbolo}", [(d, a) for d, _, a in linhas], "yahoo")
    _gravar_serie(conexao, f"yahoo:{simbolo}", [(d, f) for d, f, _ in linhas], "yahoo")


def _meses_entre(inicio_mes, fim_mes):
    meses, mes = [], inicio_mes
    while mes <= fim_mes:
        meses.append(mes)
        mes = carteira._somar_meses(mes, 1)
    return meses


def _meses_cvm_pendentes(conexao, inicio, cnpjs, hoje):
    """Meses do informe da CVM a baixar: os que faltam algum fundo e os que ainda recebem dias novos
    (o informe de um mês continua sendo completado por cerca de uma semana depois que ele acaba)."""
    pendentes = []
    for mes in _meses_entre(inicio[:7], hoje.isoformat()[:7]):
        status = _status(conexao, f"cvm:{mes}")
        if status:
            tinha = set(json.loads(status["fonte"] or "[]"))
            fechado = status["atualizado_em"][:10] > (date.fromisoformat(f"{carteira._somar_meses(mes, 1)}-01")
                                                       + timedelta(days=10)).isoformat()
            if set(cnpjs) <= tinha and (fechado or status["atualizado_em"][:10] == hoje.isoformat()):
                continue
        pendentes.append(mes)
    return pendentes


def _atualizar_cvm(conexao, mes, cnpjs, hoje):
    try:
        cotas = baixar_cvm_mes(mes, set(cnpjs))
    except urllib.error.HTTPError as e:
        # O arquivo do mês só aparece depois do primeiro dia útil com informe: até lá, tenta de novo na próxima vez.
        if e.code == 404 and mes == hoje.isoformat()[:7]:
            return
        raise
    with conexao:
        for cnpj, pontos in cotas.items():
            conexao.executemany("INSERT OR REPLACE INTO series_diarias (serie, data, valor) VALUES (?, ?, ?)",
                                [(f"cvm:{cnpj}", d, v) for d, v in pontos])
        _gravar_status(conexao, f"cvm:{mes}", json.dumps(sorted(cnpjs)))


# ============================================================================ posições no tempo
def _delta(m, classe):
    """Quanto a movimentação muda a quantidade. Come-cotas (TAX) só reduz cotas de fundos."""
    q = m.get("quantity") or 0
    tipo = m.get("type")
    if tipo == "BUY":
        return q
    if tipo == "SELL" or (tipo == "TAX" and classe == "fundos"):
        return -q
    return 0


def _cnpj(texto):
    digitos = regras.so_digitos(texto)
    if len(digitos) != 14:
        return None
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def _fonte_preco(i, classe):
    if i.get("subtype") == "TREASURY":
        return {"tipo": "tesouro"}
    if classe in carteira.BOLSA:
        codigo = carteira.ticker(i)
        return {"tipo": "yahoo", "simbolo": f"{codigo}.SA"} if codigo else None
    if classe == "fundos":
        cnpj = _cnpj(i.get("code"))
        return {"tipo": "cvm", "cnpj": cnpj} if cnpj else None
    if classe == "renda_fixa" and i.get("subtype") != "STRUCTURED_NOTE":  # COE não segue uma taxa
        if i.get("rateType") in ("CDI", "SELIC", "IPCA") or i.get("fixedAnnualRate"):
            return {"tipo": "curva"}
    return None


def _data_br(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _posicoes(conexao, itens, hoje_iso):
    """Cada posição (ativa ou encerrada) com a fonte de preço e as mudanças de quantidade.
    q_antes = quantidade antes da primeira movimentação conhecida; inicio = None quando a data é desconhecida."""
    garantir_tabelas(conexao)
    movs = carteira._movimentos(conexao, itens)
    lista, avisos = [], []
    for _, i in carteira._brutas(conexao, itens):
        if i.get("_conta"):
            conta = _saldo_em_conta(conexao, i)
            if conta:
                lista.append(conta)
            continue
        classe = carteira.classe_investimento(i)
        codigo = carteira._codigo(i)
        nome = (carteira.ticker(i) if classe in carteira.BOLSA else i.get("name")) or codigo
        movimentos = [m for m in movs.get(codigo, []) if _delta(m, classe)]
        q_hoje = 0 if carteira.encerrada(i, movs.get(codigo, []), hoje_iso) else (i.get("quantity") or 0)
        resgate = carteira.resgate_nao_informado(i, movs.get(codigo, []), hoje_iso)
        if resgate:
            avisos.append(f"{nome}: o banco ainda informa esta posição, mas ela foi resgatada em {_data_br(resgate)}; "
                          f"o Open Balance a considera encerrada nesse dia.")
        eventos = [(m["date"][:10], _delta(m, classe), m) for m in movimentos]
        q_antes = q_hoje - sum(d for _, d, _ in eventos)
        if q_antes <= max(0.01, 0.01 * max([q_hoje] + [abs(d) for _, d, _ in eventos])):
            q_antes = 0
        if not q_antes and not eventos:
            # Nada a reconstruir (ex.: resgatada antes das movimentações que o banco informa), a não ser um título
            # que o banco zerou sem informar a venda, mas cujo saldo o Open Balance guardou antes do resgate.
            if _fonte_preco(i, classe) == {"tipo": "curva"}:
                resgatada = _resgatada_sem_venda(conexao, i, nome, codigo, classe)
                if resgatada:
                    lista.append(resgatada)
            continue
        fonte = _fonte_preco(i, classe)
        if not fonte:
            avisos.append(f"{nome}: sem fonte de preço diário; fica fora do histórico.")
            continue
        compra = (i.get("purchaseDate") or "")[:10] or None
        primeira = eventos[0][0] if eventos else hoje_iso
        inicio = (compra if compra and compra <= primeira else None) if q_antes else primeira
        lista.append({"id": i["id"], "nome": nome, "codigo": codigo, "classe": classe, "fonte": fonte, "bruto": i,
                      "qHoje": q_hoje, "qAntes": q_antes, "inicio": inicio, "eventos": eventos})
    return lista, avisos


def _resgatada_sem_venda(conexao, i, nome, codigo, classe):
    """CDB resgatado que o Itaú zera (valor aplicado inclusive) sem informar a venda. Com o último saldo guardado
    antes do resgate, volta para o histórico: quantidade 1 desde a compra, valor pela taxa contratada ancorado nesse
    saldo, e o resgate no dia em que o banco o encerrou."""
    ultimo = conexao.execute("SELECT data, saldo FROM historico_saldos WHERE ref_id = ? AND saldo > 0 ORDER BY data DESC LIMIT 1",
                             (i["id"],)).fetchone()
    if not ultimo:
        return None
    fim = max((i.get("date") or "")[:10], ultimo["data"])
    return {"id": i["id"], "nome": nome, "codigo": codigo, "classe": classe, "fonte": {"tipo": "curva"}, "bruto": i,
            "qHoje": 0, "qAntes": 1.0, "inicio": (i.get("purchaseDate") or "")[:10] or None,
            "eventos": [(fim, -1.0, {"date": fim, "type": "SELL", "value": ultimo["saldo"]})]}


def _saldo_em_conta(conexao, i):
    """Saldo em conta aplicado automaticamente: o banco não manda o histórico desse saldo, então só entram os dias em
    que o Open Balance o guardou (a cada sincronização). Cada mudança conta como aporte ou resgate (preço fixo em 1)."""
    eventos, anterior = [], 0.0
    for r in conexao.execute("SELECT data, saldo FROM historico_saldos WHERE ref_id = ? ORDER BY data", (i["_conta"],)):
        saldo = max(0.0, r["saldo"] or 0)
        if abs(saldo - anterior) >= 0.01:
            eventos.append((r["data"], saldo - anterior, {"date": r["data"]}))
        anterior = saldo
    if not eventos:
        return None
    return {"id": i["id"], "nome": i["name"], "codigo": i["code"], "classe": carteira.classe_investimento(i),
            "fonte": {"tipo": "caixa"}, "bruto": i, "qHoje": anterior, "qAntes": 0, "inicio": eventos[0][0], "eventos": eventos}


def _detalhe(p):
    """Segunda linha do nome: distingue os vários 'CDB - ITAU UNIBANCO S.A.' pela taxa e pelo vencimento."""
    i = p["bruto"]
    if p["classe"] not in ("tesouro", "renda_fixa"):
        return None
    vencimento = (i.get("dueDate") or "")[:10]
    partes = [carteira.rentabilidade_contratada(i), f"vence {_data_br(vencimento)}" if vencimento and p["classe"] == "renda_fixa" else None]
    return " · ".join(x for x in partes if x) or None


def _inicio(posicoes, hoje):
    conhecidos = [p["inicio"] for p in posicoes if p["inicio"]]
    limite = date(hoje.year - ANOS_MAXIMOS, hoje.month, 1).isoformat()
    # Sem nenhuma data (ex.: posição importada sem movimentações), simula os últimos 12 meses.
    return max(min(conhecidos) if conhecidos else (hoje - timedelta(days=365)).isoformat(), limite)


# ============================================================================ séries e calendário
def _carregar_series(conexao, prefixos, desde):
    series = defaultdict(list)
    for r in conexao.execute("SELECT serie, data, valor FROM series_diarias WHERE data >= ? ORDER BY data", (desde,)):
        if r["serie"].split(":", 1)[0] in prefixos or r["serie"] in prefixos:
            series[r["serie"]].append((r["data"], r["valor"]))
    return series


def _dias_mes_uteis(mes):
    ano, m = int(mes[:4]), int(mes[5:7])
    d, n = date(ano, m, 1), 0
    while d.month == m:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def _calendario(cdi_diario, cdi_mensal, ipca_mensal, inicio, hoje_iso):
    """Dias úteis de inicio até hoje, com o CDI (% no dia) e o fator do IPCA de cada um.
    Depois do último CDI publicado repete a última taxa; sem a série diária, reparte o CDI do mês."""
    publicados = dict(p for p in cdi_diario if p[0] >= inicio)
    ultimo = max(publicados) if publicados else None
    dias = []
    d = date.fromisoformat(inicio)
    while d.isoformat() <= hoje_iso:
        iso = d.isoformat()
        if iso in publicados:
            dias.append([iso, publicados[iso]])
        elif d.weekday() < 5 and (ultimo is None or iso > ultimo):
            dias.append([iso, None])
        d += timedelta(days=1)
    ultima_taxa = publicados[ultimo] if ultimo else None
    por_mes = defaultdict(int)
    for iso, _ in dias:
        por_mes[iso[:7]] += 1
    primeiro_mes, mes_atual = inicio[:7], hoje_iso[:7]
    for dia in dias:
        mes = dia[0][:7]
        uteis = _dias_mes_uteis(mes) if mes in (primeiro_mes, mes_atual) else por_mes[mes]
        if dia[1] is None:
            if ultima_taxa is not None:
                dia[1] = ultima_taxa
            else:
                mensal = cdi_mensal.get(mes)
                dia[1] = ((1 + mensal / 100) ** (1 / _dias_mes_uteis(mes)) - 1) * 100 if mensal is not None else 0.0
        ipca = ipca_mensal.get(mes)
        dia.append((1 + ipca / 100) ** (1 / uteis) if ipca is not None else 1.0)
    return dias


def _no_calendario(pontos, datas):
    """Série [(data, valor)] repetindo o último valor nos dias sem cotação; None antes do primeiro."""
    resultado, j, atual = [], 0, None
    for d in datas:
        while j < len(pontos) and pontos[j][0] <= d:
            atual = pontos[j][1]
            j += 1
        resultado.append(atual)
    return resultado


def _curva(i, dias):
    """Índice da taxa contratada de um título (1 no primeiro dia). Cada dia rende o CDI/IPCA do dia útil anterior."""
    indexador, taxa, fixa = i.get("rateType"), i.get("rate") or 0, i.get("fixedAnnualRate") or 0
    diario_fixo = (1 + fixa / 100) ** (1 / DIAS_UTEIS_ANO)
    curva = [1.0]
    for k in range(1, len(dias)):
        _, cdi, ipca = dias[k - 1]
        if indexador in ("CDI", "SELIC"):
            fator = (1 + cdi / 100 * (taxa or 100) / 100) * diario_fixo
        elif indexador == "IPCA":
            fator = ipca * (1 + taxa / 100) ** (1 / DIAS_UTEIS_ANO)
        else:
            fator = diario_fixo
        curva.append(curva[-1] * fator)
    return curva


def _titulo_tesouro(i, titulos):
    """Qual série do Tesouro Transparente é este título: pelo vencimento e pelo começo do nome."""
    vencimento = (i.get("dueDate") or "")[:10]
    candidatos = [t for t in titulos if t[1] == vencimento]
    if not candidatos:
        return None
    nome = regras.normalizar(i.get("name"))
    pelo_nome = [t for t in candidatos if nome.startswith(regras.normalizar(t[0]))]
    if pelo_nome:
        return max(pelo_nome, key=lambda t: len(t[0]))
    referencia = i.get("value") or 0
    return min(candidatos, key=lambda t: abs(titulos[t][-1][1] - referencia))


def _precos(p, dias, datas, series, titulos):
    """(preço, índice de rentabilidade) de cada dia. Preço × quantidade = valor; o índice inclui proventos."""
    i, fonte = p["bruto"], p["fonte"]
    if fonte["tipo"] == "caixa":  # saldo em conta: o valor é a própria quantidade, e o que rende não é informado
        return [1.0] * len(datas), [1.0] * len(datas)
    if fonte["tipo"] == "tesouro":
        titulo = _titulo_tesouro(i, titulos)
        preco = _no_calendario(titulos[titulo], datas) if titulo else [None] * len(datas)
        return preco, preco
    if fonte["tipo"] == "curva":
        curva = _curva(i, dias)
        # Âncora: o preço unitário de hoje (posição ativa) ou o da última venda (encerrada).
        if p["qHoje"]:
            k, unitario = len(datas) - 1, (i.get("amount") or i.get("balance") or 0) / p["qHoje"]
        else:
            venda = next((m for d, delta, m in reversed(p["eventos"]) if delta < 0 and m.get("value")), None)
            if not venda:
                return [None] * len(datas), [None] * len(datas)
            k = max(0, sum(1 for d in datas if d <= venda["date"][:10]) - 1)
            unitario = venda["value"]
        preco = [unitario * c / curva[k] for c in curva]
        return preco, preco
    if fonte["tipo"] == "yahoo":
        fechamento = list(series.get(f"yahoo:{fonte['simbolo']}", []))
        ajustado = list(series.get(f"yahoo_aj:{fonte['simbolo']}", []))
    else:
        fechamento = list(series.get(f"cvm:{fonte['cnpj']}", []))
        ajustado = fechamento
    # O banco informa o preço de hoje; vale como último ponto se a fonte ainda não publicou (CVM sai com atraso).
    if p["qHoje"] and fechamento:
        data_banco = ((i.get("date") or "")[:10] or datas[-1])
        unitario = i.get("value") or ((i.get("amount") or 0) / p["qHoje"])
        if unitario and ajustado and data_banco > fechamento[-1][0]:
            ajustado = ajustado + [(data_banco, ajustado[-1][1] * unitario / fechamento[-1][1])]
            fechamento = fechamento + [(data_banco, unitario)]
    return _no_calendario(fechamento, datas), _no_calendario(ajustado, datas)


def _quantidades(p, datas):
    q, j, resultado = p["qAntes"], 0, []
    eventos = p["eventos"]
    for d in datas:
        while j < len(eventos) and eventos[j][0] <= d:
            q += eventos[j][1]
            j += 1
        resultado.append(0.0 if (p["inicio"] and d < p["inicio"]) else max(0.0, q))
    return resultado


def _normalizar(valores, casas=6):
    base = next((v for v in valores if v), None)
    return [round(v / base, casas) if v and base else None for v in valores]


def _agregar(ativos, n):
    """Valor, aportes − resgates, ganho em reais e cota da carteira em cada dia.
    Rentabilidade por cotas: cada dia rende a média do retorno dos ativos, ponderada pelo valor da véspera.
    O ganho do dia em reais (rendimento por mês do Resumo) usa o mesmo índice, que inclui dividendos e JCP."""
    cota, valor_total, fluxo, ganhos = [1.0], [sum(a["valor"][0] for a in ativos)], [0.0], [0.0]
    for k in range(1, n):
        base = ganho = entrou = 0.0
        for a in ativos:
            anterior, i0, i1 = a["valor"][k - 1], a["indice"][k - 1], a["indice"][k]
            if anterior and i0 and i1:
                base += anterior
                ganho += anterior * (i1 / i0 - 1)
            if a["preco"][k] is not None:
                entrou += (a["qtd"][k] - a["qtd"][k - 1]) * a["preco"][k]
        cota.append(cota[-1] * (1 + (ganho / base if base else 0)))
        valor_total.append(sum(a["valor"][k] for a in ativos))
        fluxo.append(entrou)
        ganhos.append(ganho)
    return {"cota": [round(c, 8) for c in cota], "valor": [round(v, 2) for v in valor_total],
            "fluxo": [round(f, 2) for f in fluxo], "ganho": [round(g, 2) for g in ganhos]}


# ============================================================================ montagem
def montar(conexao, hoje=None):
    """Tudo o que as sub-abas Rentabilidade e Risco precisam, dia a dia. Só lê o que já está guardado."""
    hoje = hoje or date.today()
    hoje_iso = hoje.isoformat()
    posicoes, avisos = _posicoes(conexao, itens_visiveis(conexao), hoje_iso)
    if not posicoes:
        return {"vazio": True}
    inicio = _inicio(posicoes, hoje)
    cdi_mensal, ipca_mensal, _ = carteira.carregar_indices(conexao, hoje_iso)
    series = _carregar_series(conexao, {"yahoo", "yahoo_aj", "cvm", "cdi_diario"},
                              (date.fromisoformat(inicio) - timedelta(days=15)).isoformat())
    dias = _calendario(series.get("cdi_diario", []), cdi_mensal.mensal, ipca_mensal.mensal, inicio, hoje_iso)
    datas = [d[0] for d in dias]
    titulos = defaultdict(list)
    if any(p["fonte"]["tipo"] == "tesouro" for p in posicoes):
        desde = (date.fromisoformat(inicio) - timedelta(days=15)).isoformat()
        for r in conexao.execute("SELECT titulo, vencimento, data, pu_venda FROM precos_tesouro WHERE data >= ? AND pu_venda > 0 "
                                 "ORDER BY data", (desde,)):
            titulos[(r["titulo"], r["vencimento"])].append((r["data"], r["pu_venda"]))

    n = len(datas)
    ativos, sem_preco = [], []
    for p in posicoes:
        preco, indice = _precos(p, dias, datas, series, titulos)
        qtd = _quantidades(p, datas)
        valor = [q * pr if q and pr is not None else 0.0 for q, pr in zip(qtd, preco)]
        if any(q and pr is None for q, pr in zip(qtd, preco)):
            sem_preco.append(p["nome"])
        if not any(valor):
            continue
        ativo = {"p": p, "qtd": qtd, "preco": preco, "indice": indice, "valor": valor}
        if p["fonte"]["tipo"] == "tesouro":
            # Na curva: a taxa contratada, ancorada no valor que o banco informa hoje (como no app do banco).
            curva, _ = _precos({**p, "fonte": {"tipo": "curva"}}, dias, datas, series, titulos)
            ativo["curva"] = {"preco": curva, "indice": curva,
                              "valor": [q * pr if q and pr is not None else 0.0 for q, pr in zip(qtd, curva)]}
        ativos.append(ativo)
    com_curva = [{**a, **a["curva"]} if "curva" in a else a for a in ativos]

    # Índices de comparação na mesma régua de datas.
    cdi, ipca = [1.0], [1.0]
    for k in range(1, n):
        cdi.append(cdi[-1] * (1 + dias[k - 1][1] / 100))
        ipca.append(ipca[-1] * dias[k - 1][2])
    fechamento = lambda simbolo: _no_calendario(series.get(f"yahoo:{simbolo}", []), datas)  # noqa: E731
    indices = {"cdi": cdi, "ipca": ipca}
    for chave, simbolo in SIMBOLOS_REFERENCIA.items():
        if chave != "sp500":
            indices[chave] = fechamento(simbolo)
    sp, dolar = fechamento(SIMBOLOS_REFERENCIA["sp500"]), indices["dolar"]
    indices["sp500"] = [s * d if s and d else None for s, d in zip(sp, dolar)]

    movimentos = [e[0] for p in posicoes for e in p["eventos"]]
    status = {r["serie"]: r["atualizado_em"] for r in conexao.execute("SELECT serie, atualizado_em FROM indices_status")}
    return {
        "datas": datas,
        "inicio": datas[0] if datas else inicio,
        # Antes das primeiras movimentações informadas, compras e vendas não são conhecidas: trecho estimado.
        "confiavelDesde": min(movimentos) if movimentos else None,
        "carteira": _agregar(ativos, n),
        # A mesma carteira com o Tesouro na curva (a outra visão do Resumo); None sem Tesouro.
        "carteiraCurva": _agregar(com_curva, n) if com_curva != ativos else None,
        "indices": {k: _normalizar(v, 8) for k, v in indices.items()},
        "indicesInfo": {"cdiAte": max((d for d, _ in series.get("cdi_diario", [])), default=None),
                        "ipcaAte": ipca_mensal.ultimo_completo},
        "ativos": [{
            "id": a["p"]["id"], "nome": a["p"]["nome"], "detalhe": _detalhe(a["p"]), "classe": a["p"]["classe"],
            "ativo": bool(a["p"]["qHoje"]),
            "fonte": a["p"]["fonte"]["tipo"],
            "valor": [round(v, 2) for v in a["valor"]], "indice": _normalizar(a["indice"], 8),
        } for a in ativos],
        "semPreco": sorted(set(sem_preco)),
        "avisos": avisos,
        "atualizadoEm": max(status.values(), default=None),
    }
