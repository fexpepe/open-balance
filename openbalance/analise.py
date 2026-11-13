"""Monta os dados que o painel consome a partir do SQLite.

Ordem de prioridade da classificação de cada transação:
    ajuste manual  >  regra criada por você  >  regras automáticas (regras.py)
"""

import calendar
import statistics
from collections import defaultdict
from datetime import date

from . import orcamento, previsao, regras
from .banco import bruto, preferencia
from .config import itens_configurados, pluggy_configurado, resumo_pluggy

# Recorrentes: categorias que nunca são "assinatura" (a não ser que seja um serviço conhecido).
FORA_DE_RECORRENTES = ("01", "03", "04", "05", "10", "11", "1901", "1503", "16")
# Recorrentes dessas categorias são contas fixas (moradia, financiamentos, seguros, telefone, escola…).
CONTAS_FIXAS = ("02", "15", "17", "18", "20", "0701", "0702")

ROTULO_SUBTIPO = {"CHECKING_ACCOUNT": "Conta corrente", "SAVINGS_ACCOUNT": "Poupança", "CREDIT_CARD": "Cartão"}


def somar_meses(data_iso, meses):
    d = date.fromisoformat(data_iso[:10])
    total = d.year * 12 + d.month - 1 + meses
    ano, mes = divmod(total, 12)
    mes += 1
    dias_no_mes = [31, 29 if ano % 4 == 0 and (ano % 100 or ano % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(ano, mes, min(d.day, dias_no_mes[mes - 1])).isoformat()


def dia_do_mes(mes, dia):
    """'2026-02', 31 → '2026-02-28'."""
    ano, m = int(mes[:4]), int(mes[5:7])
    return date(ano, m, min(dia, calendar.monthrange(ano, m)[1])).isoformat()


def final_numero(numero):
    digitos = regras.so_digitos(numero)
    return digitos[-4:] if digitos else ""


def carregar_categorias(conexao):
    linhas = {r["id"]: dict(r) for r in conexao.execute("SELECT * FROM categorias")}

    def raiz(cat_id):
        vistos = set()
        while linhas.get(cat_id, {}).get("pai_id") and cat_id not in vistos:
            vistos.add(cat_id)
            cat_id = linhas[cat_id]["pai_id"]
        return cat_id

    return {cid: {"nome": c["descricao_pt"] or c["descricao"], "grupo": raiz(cid), "propria": bool(c["propria"])}
            for cid, c in linhas.items()}


def itens_visiveis(conexao):
    """Conexões que entram no painel: as do .env (itens antigos, de antes de reconectar, não somam) e os arquivos importados."""
    configurados = set(itens_configurados())
    return {r["id"]: dict(r) for r in conexao.execute(
        "SELECT id, instituicao, status, atualizado_em, consentimento_expira, origem FROM itens")
        if r["origem"] == "importacao" or not configurados or r["id"] in configurados}


def montar(conexao, hoje=None):
    hoje = hoje or date.today()
    hoje_iso = hoje.isoformat()
    categorias = carregar_categorias(conexao)

    itens = itens_visiveis(conexao)
    contas_brutas = {r["id"]: (r["item_id"], bruto(r)) for r in conexao.execute("SELECT id, item_id, bruto FROM contas")
                     if r["item_id"] in itens}
    nome_titular = preferencia(conexao, "titular", "")

    cpf_por_item = {}
    for item_id, conta in contas_brutas.values():
        cpf = regras.so_digitos(conta.get("taxNumber"))
        if len(cpf) == 11:
            cpf_por_item[item_id] = cpf

    contas = [resumo_conta(conta, item_id, itens) for item_id, conta in contas_brutas.values()]
    ajustes = {r["transacao_id"]: dict(r) for r in conexao.execute("SELECT * FROM ajustes")}
    regras_usuario = [dict(r) for r in conexao.execute("SELECT * FROM regras ORDER BY id")]

    transacoes = []
    for linha in conexao.execute("SELECT conta_id, bruto FROM transacoes ORDER BY data DESC, id"):
        if linha["conta_id"] not in contas_brutas:
            continue
        item_id, conta = contas_brutas[linha["conta_id"]]
        tx = enriquecer(bruto(linha), conta, cpf_por_item.get(item_id, ""), regras_usuario, ajustes, hoje_iso, nome_titular)
        if tx["categoriaId"] not in categorias:
            categorias[tx["categoriaId"]] = {"nome": tx.pop("_categoriaTexto") or "Outros", "grupo": regras.CAT_OUTROS}
        tx.pop("_categoriaTexto", None)
        transacoes.append(tx)

    faturas = defaultdict(list)
    for r in conexao.execute("SELECT conta_id, bruto FROM faturas ORDER BY vencimento"):
        faturas[r["conta_id"]].append(bruto(r))

    sinc = conexao.execute("SELECT inicio, fim, ok, resumo FROM sincronizacoes ORDER BY id DESC LIMIT 1").fetchone()
    historico = [dict(r) for r in conexao.execute("SELECT data, ref_id, tipo, saldo FROM historico_saldos ORDER BY data")]
    lista_cartoes = cartoes(contas, transacoes, faturas, hoje_iso)
    ultima_fechada = {c["contaId"]: c["ultimaFechada"]["vencimento"][:7] for c in lista_cartoes if c["ultimaFechada"]}

    titular = next((c.get("owner") for _, c in contas_brutas.values() if c.get("type") == "BANK" and c.get("owner")), "")
    titular = titular or nome_titular
    lista_recorrentes = recorrentes(transacoes, hoje)

    return {
        "hoje": hoje_iso,
        "pluggy": pluggy_configurado(),
        "pluggyInfo": resumo_pluggy(),  # sem o Client Secret
        "importacoes": importacoes(conexao, contas),
        "nomeTitular": nome_titular,
        "titular": titular.split()[0].title() if titular else "",
        "ultimaSincronizacao": dict(sinc) if sinc else None,
        "itens": list(itens.values()),
        "contas": contas,
        "categorias": categorias,
        "transacoes": transacoes,
        "parcelamentos": parcelamentos(transacoes, hoje_iso, ultima_fechada),
        "emprestimos": emprestimos(transacoes, regras_usuario, hoje_iso),
        "recorrentes": lista_recorrentes,
        "cartoes": lista_cartoes,
        "orcamento": orcamento.montar(conexao, transacoes, categorias, hoje),
        "previsao": previsao.montar(conexao, contas, lista_cartoes, lista_recorrentes, transacoes, categorias, hoje),
        "investimentos": investimentos(conexao, itens),
        "carteira": carteira_completa(conexao, itens, transacoes, hoje),
        "imposto": imposto_investimentos(conexao, itens, transacoes, hoje),
        "historicoSaldos": historico,
        "regras": regras_usuario,
    }


def resumo_conta(conta, item_id, itens):
    credito = conta.get("creditData") or {}
    instituicao = itens.get(item_id, {}).get("instituicao") or "?"
    if conta.get("type") == "CREDIT":
        nome = (conta.get("marketingName") or conta.get("name") or "Cartão").strip()
        if instituicao.lower() not in nome.lower():
            nome = f"{instituicao} {nome.title()}"
    else:
        nome = f"{instituicao} {conta['_apelido']}" if conta.get("_apelido") else instituicao
    importada = conta.get("origem") == "importacao"
    resumo = {
        "id": conta["id"], "itemId": item_id, "instituicao": instituicao, "tipo": conta.get("type"),
        "subtipo": ROTULO_SUBTIPO.get(conta.get("subtype"), conta.get("subtype")), "nome": nome,
        "final": final_numero(conta.get("number")), "saldo": conta.get("balance") or 0,
        "bandeira": credito.get("brand"), "nivel": credito.get("level"),
        "origem": "importacao" if importada else "pluggy", "apelido": conta.get("_apelido"),
        # Conta importada sem saldo informado (ex.: CSV que não traz saldo): o painel mostra "—".
        "semSaldo": importada and conta.get("type") == "BANK" and conta.get("_saldoData") is None,
        "saldoData": conta.get("_saldoData"), "fatura": conta.get("_fatura"),
    }
    if conta.get("type") == "CREDIT":
        resumo.update(limites(credito, conta.get("balance") or 0))
    return resumo


def limites(credito, saldo):
    """Limite total, disponível e usado. O 'usado' vem das linhas de crédito quando o banco informa."""
    limite = credito.get("creditLimit")
    disponivel = credito.get("availableCreditLimit")
    linhas = credito.get("disaggregatedCreditLimits") or []
    # O banco pode repetir a mesma linha; vale a primeira de limite total.
    total = next((l for l in linhas if l.get("creditLineLimitType") == "LIMITE_CREDITO_TOTAL"
                  and l.get("usedAmount") is not None), None)
    if total:
        usado = total["usedAmount"]
    elif limite is not None and disponivel is not None:
        usado = limite - disponivel
    else:
        usado = saldo
    configurado = next((l.get("customizedLimitAmount") for l in linhas if l.get("customizedLimitAmount")), None)
    return {"limite": limite, "disponivel": disponivel, "usado": round(usado, 2), "limiteConfigurado": configurado}


def enriquecer(t, conta, cpf, regras_usuario, ajustes, hoje_iso, nome_titular=""):
    natureza_auto, categoria_auto = regras.classificar(t, conta, cpf, nome_titular)
    natureza, categoria, regra_id = natureza_auto, categoria_auto, None
    for regra in regras_usuario:
        if regras.regra_casa(regra["padrao"], t.get("description")):
            natureza = regra["natureza"] or natureza
            categoria = regra["categoria_id"] or categoria
            regra_id = regra["id"]
            break
    ajuste = ajustes.get(t["id"]) or {}
    natureza = ajuste.get("natureza") or natureza
    categoria = ajuste.get("categoria_id") or categoria

    meta = t.get("creditCardMetadata") or {}
    descricao_norm = regras.normalizar(t.get("description"))
    nome_marca = regras.marca(descricao_norm)
    parcela = None
    if (meta.get("totalInstallments") or 0) > 1 and meta.get("installmentNumber"):
        parcela = [int(meta["installmentNumber"]), int(meta["totalInstallments"])]
    data = t["date"][:10]
    return {
        "id": t["id"], "contaId": conta["id"], "data": data, "descricao": regras.limpar_descricao(t.get("description")),
        "valor": abs(t.get("amount") or 0), "entrada": t.get("type") == "CREDIT", "natureza": natureza,
        "naturezaAuto": natureza_auto, "categoriaId": categoria, "categoriaAuto": categoria_auto,
        "pendente": t.get("status") == "PENDING", "futura": data > hoje_iso, "parcela": parcela,
        "faturaMes": meta.get("billForecastDate"), "compra": (meta.get("purchaseDate") or "")[:10] or None,
        "marca": nome_marca, "chave": regras.chave_estabelecimento(t.get("description"), nome_marca),
        "operacao": t.get("operationType"), "oculto": bool(ajuste.get("oculto")),
        "ajustada": bool(ajuste.get("natureza") or ajuste.get("categoria_id")), "regraId": regra_id,
        "_categoriaTexto": t.get("category"),
    }


def parcelamentos(transacoes, hoje_iso, ultima_fechada):
    """Compras parceladas. 'Pagas' = parcelas em faturas já fechadas; a da fatura aberta ainda conta como restante."""

    def paga(t):
        mes_fechada = ultima_fechada.get(t["contaId"])
        if mes_fechada and t["faturaMes"]:
            return t["faturaMes"] <= mes_fechada
        return t["data"] <= hoje_iso

    grupos = defaultdict(list)
    for t in transacoes:
        if not t["parcela"] or t["natureza"] != regras.DESPESA or t["entrada"] or t["oculto"]:
            continue
        k, n = t["parcela"]
        origem = t["compra"] or somar_meses(t["data"], -(k - 1))[:7]
        grupos[(t["contaId"], t["chave"], n, origem, round(t["valor"]))].append(t)

    resultado = []
    for (conta_id, _, n, origem, _), lista in grupos.items():
        lista.sort(key=lambda t: t["parcela"][0])
        valor = statistics.median(t["valor"] for t in lista)
        pagas = max((t["parcela"][0] for t in lista if paga(t)), default=0)
        ultima = lista[-1]
        proxima = next((t["faturaMes"] or t["data"][:7] for t in lista if not paga(t)), None)
        resultado.append({
            "nome": ultima["marca"] or ultima["descricao"], "marca": ultima["marca"], "contaId": conta_id,
            "categoriaId": ultima["categoriaId"], "compra": origem, "parcelas": n, "pagas": pagas, "valorParcela": round(valor, 2),
            "total": round(n * valor, 2), "pago": round(pagas * valor, 2), "restante": round((n - pagas) * valor, 2),
            "proxima": proxima, "ultimaParcela": somar_meses(ultima["data"], n - ultima["parcela"][0]),
            "status": "ativo" if pagas < n else "finalizado",
        })
    resultado.sort(key=lambda p: (p["status"] != "ativo", -p["restante"], p["nome"]))
    return resultado


def recorrentes(transacoes, hoje):
    hoje_iso = hoje.isoformat()
    grupos = defaultdict(list)
    for t in transacoes:
        if t["natureza"] != regras.DESPESA or t["entrada"] or t["oculto"] or t["data"] > hoje_iso:
            continue
        if t["parcela"]:
            continue
        if not t["marca"] and t["categoriaId"].startswith(FORA_DE_RECORRENTES):
            continue
        grupos[t["chave"]].append(t)

    resultado = []
    for lista in grupos.values():
        por_data = defaultdict(float)  # soma a linha de IOF com a cobrança do mesmo dia
        for t in lista:
            por_data[t["data"]] += t["valor"]
        datas = sorted(por_data)
        meses = {d[:7] for d in datas}
        if len(meses) < 3 or len(datas) / len(meses) > 1.5:
            continue
        dias = [date.fromisoformat(d) for d in datas]
        intervalo = statistics.median((b - a).days for a, b in zip(dias, dias[1:]))
        if not 25 <= intervalo <= 35 or (hoje - dias[-1]).days > 45:
            continue
        principal = max(lista, key=lambda t: (t["data"], t["valor"]))
        categoria = principal["categoriaId"]
        resultado.append({
            "nome": principal["marca"] or principal["descricao"], "descricao": principal["descricao"], "chave": principal["chave"],
            "contaId": principal["contaId"], "categoriaId": categoria, "valor": round(por_data[datas[-1]], 2),
            "media": round(statistics.mean(por_data[d] for d in datas[-6:]), 2), "pagamentos": len(datas),
            "ultima": datas[-1], "proxima": somar_meses(datas[-1], 1),
            "tipo": tipo_recorrente(principal),
            "historico": [{"data": d, "valor": round(por_data[d], 2)} for d in datas[-12:]],
        })
    resultado.sort(key=lambda r: -r["valor"])
    return resultado


def tipo_recorrente(t):
    """Serviço conhecido = assinatura; Pix/TED/boleto recorrente ou categoria de conta fixa = conta fixa."""
    if t["marca"]:
        return "assinatura"
    if t["categoriaId"].startswith(CONTAS_FIXAS) or t["operacao"] in ("PIX", "TED", "BOLETO"):
        return "conta_fixa"
    return "assinatura"


def emprestimos(transacoes, regras_usuario, hoje_iso):
    """Saldo por pessoa do que você emprestou (saídas) e recebeu de volta (entradas)."""
    padroes = {r["id"]: r["padrao"] for r in regras_usuario}
    pessoas = defaultdict(lambda: {"emprestado": 0.0, "devolvido": 0.0, "transacoes": 0, "ultima": "", "nomes": set()})
    for t in transacoes:
        if t["natureza"] != regras.EMPRESTIMO or t["oculto"] or t["data"] > hoje_iso:
            continue
        # Agrupa pela regra (mesma pessoa em bancos diferentes); sem regra, pela própria descrição.
        p = pessoas[padroes.get(t["regraId"]) or regras.nome_contraparte(t["descricao"])]
        p["devolvido" if t["entrada"] else "emprestado"] += t["valor"]
        p["transacoes"] += 1
        p["ultima"] = max(p["ultima"], t["data"])
        p["nomes"].add(regras.nome_contraparte(t["descricao"]))
    resultado = []
    for chave, p in pessoas.items():
        resultado.append({
            "nome": max(p["nomes"], key=len) or chave, "emprestado": round(p["emprestado"], 2),
            "devolvido": round(p["devolvido"], 2), "saldo": round(p["emprestado"] - p["devolvido"], 2),
            "transacoes": p["transacoes"], "ultima": p["ultima"],
        })
    return sorted(resultado, key=lambda p: -p["saldo"])


def cartoes(contas, transacoes, faturas_por_conta, hoje_iso):
    resultado = []
    for conta in contas:
        if conta["tipo"] != "CREDIT":
            continue
        txs = [t for t in transacoes if t["contaId"] == conta["id"] and not t["oculto"]]
        faturas = faturas_por_conta.get(conta["id"], [])
        ultima = faturas[-1] if faturas else None

        # Fatura aberta = a próxima depois da última fechada; sem histórico, usa o mês previsto mais recente.
        if ultima:
            vencimento_aberta = somar_meses(ultima["dueDate"], 1)
        else:
            meses = sorted({t["faturaMes"] for t in txs if t["faturaMes"] and t["data"] <= hoje_iso})
            dia = (conta.get("fatura") or {}).get("diaVencimento") or 10
            vencimento_aberta = dia_do_mes(meses[-1], dia) if meses else None
        mes_aberta = vencimento_aberta[:7] if vencimento_aberta else None

        por_mes = defaultdict(float)
        for t in txs:
            if t["faturaMes"] and t["natureza"] == regras.DESPESA:
                por_mes[t["faturaMes"]] += -t["valor"] if t["entrada"] else t["valor"]

        aberta = round(por_mes.get(mes_aberta, 0), 2) if mes_aberta else 0
        ultima_fechada = {"vencimento": ultima["dueDate"][:10], "fechamento": (ultima.get("billClosingDate") or "")[:10],
                          "valor": ultima["totalAmount"], "aPagar": ultima["dueDate"][:10] >= hoje_iso} if ultima else None
        proximas = [{"mes": m, "valor": round(v, 2)} for m, v in sorted(por_mes.items())
                    if mes_aberta and m > mes_aberta and v > 0][:12]
        disponivel, usado, estimado = conta["disponivel"], conta["usado"], False
        if disponivel is None and conta["limite"]:
            # Cartão importado: o arquivo não traz o limite disponível; estima pelo que ainda vai ser cobrado.
            usado = aberta + sum(p["valor"] for p in proximas) + (ultima_fechada["valor"] if ultima_fechada and ultima_fechada["aPagar"] else 0)
            disponivel, estimado = round(conta["limite"] - usado, 2), True
        resultado.append({
            "contaId": conta["id"], "nome": conta["nome"], "final": conta["final"], "instituicao": conta["instituicao"],
            "bandeira": conta["bandeira"], "nivel": conta["nivel"], "limite": conta["limite"],
            "disponivel": disponivel, "usado": round(usado or 0, 2), "limiteConfigurado": conta["limiteConfigurado"],
            "disponivelEstimado": estimado, "origem": conta.get("origem"),
            "faturaAberta": {"mes": mes_aberta, "vencimento": vencimento_aberta, "valor": aberta},
            "ultimaFechada": ultima_fechada,
            "historico": [{"mes": f["dueDate"][:7], "vencimento": f["dueDate"][:10], "valor": f["totalAmount"]}
                          for f in faturas[-12:]],
            "proximas": proximas,
        })
    return resultado


def importacoes(conexao, contas):
    """Últimas importações de arquivo, para a aba Importar (com o 'desfazer')."""
    nomes = {c["id"]: c["nome"] + (f" •••• {c['final']}" if c["tipo"] == "CREDIT" and c["final"] else "") for c in contas}
    return [{**dict(r), "conta": nomes.get(r["conta_id"])} for r in conexao.execute(
        "SELECT id, criada_em, arquivo, formato, tipo, conta_id, inicio, fim, novas, existentes FROM importacoes "
        "ORDER BY id DESC LIMIT 40")]


def investimentos(conexao, itens):
    # Toda a parte de investimentos fica em carteira.py (import local para não mexer nos imports do módulo).
    from . import carteira
    return carteira.posicoes(conexao, itens)


def carteira_completa(conexao, itens, transacoes, hoje):
    from . import carteira
    return carteira.montar(conexao, itens, transacoes, hoje)


def imposto_investimentos(conexao, itens, transacoes, hoje):
    # Estimativa do IR (imposto.py). Um erro nela aparece só na sub-aba Imposto, sem derrubar o painel.
    import traceback
    from . import imposto
    try:
        return imposto.montar(conexao, itens, transacoes, hoje)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"erro": f"{type(e).__name__}: {e}"}
