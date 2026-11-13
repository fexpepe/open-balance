"""Previsão de caixa: quanto deve sobrar nas contas no fim deste mês e dos próximos 3.

    saldo de hoje das contas (corrente e poupança)
  + entradas que se repetem todo mês (salário, aposentadoria, Pix fixo…)
  − faturas dos cartões (a fechada ainda não paga, a aberta e as próximas, com as parcelas já lançadas)
  − contas fixas e assinaturas cobradas direto na conta
  − gasto do dia a dia (mediana dos últimos meses; você pode trocar pelo seu valor)
  ± lançamentos que você adicionou (bônus, IPVA, viagem…)

Aplicações, resgates, transferências entre suas contas e empréstimos a terceiros não entram:
são dinheiro mudando de lugar, não gasto nem renda.
"""

import calendar
import json
import statistics
import uuid
from collections import defaultdict
from datetime import date, timedelta

from . import regras
from .banco import gravar_preferencia, preferencia

MESES_FUTUROS = 3  # além do mês corrente
MESES_BASE = 6  # meses fechados usados para estimar o dia a dia
# Salário, aposentadoria, empreendedorismo e auxílio do governo: o fluxo é a categoria, não a descrição
# (o mesmo salário chega como "PAGTO SALARIO", "SALARIOS", "REMUNERACAO"…).
CATEGORIAS_RENDA = ("01010000", "01020000", "01030000", "01040000")
PREFERENCIA = "previsao"
LIMITE_VALOR = 100_000_000


# ------------------------------------------------------------------ datas
def _mais_meses(d, n):
    total = d.year * 12 + d.month - 1 + n
    ano, mes = divmod(total, 12)
    return date(ano, mes + 1, min(d.day, calendar.monthrange(ano, mes + 1)[1]))


def _fim_do_mes(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _dia_do_mes(mes, dia):
    ano, m = int(mes[:4]), int(mes[5:7])
    return date(ano, m, min(dia, calendar.monthrange(ano, m)[1]))


def _repeticoes(primeira, inicio, fim):
    """Datas mensais a partir de `primeira` (sem acumular o encurtamento de fevereiro) dentro de [inicio, fim]."""
    k = 0
    while (d := _mais_meses(primeira, k)) <= fim:
        if d >= inicio:
            yield d
        k += 1


def _previstas(primeira, amanha, fim):
    """Datas mensais a partir de `primeira`; a que já devia ter caído e ainda não caiu fica para amanhã."""
    datas = list(_repeticoes(primeira, primeira, fim))
    return [max(datas[0], amanha), *datas[1:]] if datas else []


def _valor(t):
    return -t["valor"] if t["entrada"] else t["valor"]


# ------------------------------------------------------------------ ajustes do usuário
def carregar_ajustes(conexao):
    try:
        salvo = json.loads(preferencia(conexao, PREFERENCIA, "") or "{}")
    except ValueError:
        salvo = {}
    return {
        "diaADiaConta": salvo.get("diaADiaConta"),  # None = automático
        "diaADiaCartao": salvo.get("diaADiaCartao"),
        "ignorados": list(salvo.get("ignorados") or []),
        "manuais": list(salvo.get("manuais") or []),
    }


def _valor_opcional(v, nome):
    if v in (None, ""):
        return None
    v = round(float(v), 2)
    if not 0 <= v <= LIMITE_VALOR:
        raise ValueError(f"{nome} precisa ficar entre zero e {LIMITE_VALOR:,.0f}".replace(",", "."))
    return v


def salvar_ajustes(conexao, corpo):
    ignorados = corpo.get("ignorados") or []
    manuais = corpo.get("manuais") or []
    if not isinstance(ignorados, list) or not isinstance(manuais, list) or len(ignorados) > 300 or len(manuais) > 100:
        raise ValueError("ajustes da previsão inválidos")
    limpos = []
    for m in manuais:
        descricao = str(m.get("descricao") or "").strip()[:80]
        valor = round(float(m.get("valor") or 0), 2)
        try:
            data = date.fromisoformat(str(m.get("data"))[:10]).isoformat()
        except ValueError:
            raise ValueError("data inválida no lançamento") from None
        if not descricao:
            raise ValueError("dê um nome ao lançamento")
        if not valor or abs(valor) > LIMITE_VALOR:
            raise ValueError("informe o valor do lançamento")
        limpos.append({"id": str(m.get("id") or uuid.uuid4().hex[:12])[:40], "descricao": descricao,
                       "valor": valor, "data": data, "mensal": bool(m.get("mensal"))})
    ajustes = {
        "diaADiaConta": _valor_opcional(corpo.get("diaADiaConta"), "o gasto do dia a dia na conta"),
        "diaADiaCartao": _valor_opcional(corpo.get("diaADiaCartao"), "o gasto do dia a dia no cartão"),
        "ignorados": sorted({str(i)[:200] for i in ignorados}),
        "manuais": limpos,
    }
    gravar_preferencia(conexao, PREFERENCIA, json.dumps(ajustes, ensure_ascii=False))
    return {"ok": True, "ajustes": ajustes}


# ------------------------------------------------------------------ entradas recorrentes
def _grupos_por_dia(lista):
    """Separa pagamentos do mesmo fluxo pelo dia do mês (ex.: adiantamento dia 15 x salário dia 30).

    O mês é tratado como um círculo, para o salário que cai dia 30 num mês e dia 1 no outro ficar num grupo só.
    """
    dias = sorted({int(t["data"][8:10]) for t in lista})
    buracos = [((dias[(i + 1) % len(dias)] - d) % 31) or 31 for i, d in enumerate(dias)]
    inicio = (buracos.index(max(buracos)) + 1) % len(dias)  # começa logo depois do maior intervalo sem pagamento
    ordem = dias[inicio:] + dias[:inicio]
    grupo_do_dia, g = {}, 0
    for i, d in enumerate(ordem):
        if i and (d - ordem[i - 1]) % 31 > 4:
            g += 1
        grupo_do_dia[d] = g
    grupos = defaultdict(list)
    for t in lista:
        grupos[grupo_do_dia[int(t["data"][8:10])]].append(t)
    return grupos.values()


def _ocorrencias(lista):
    """Junta créditos a até 7 dias um do outro numa ocorrência só (salário pago em duas partes, 13º junto…)."""
    ocorrencias = []
    for t in sorted(lista, key=lambda t: t["data"]):
        d = date.fromisoformat(t["data"])
        if ocorrencias and (d - ocorrencias[-1]["data"]).days <= 7:
            ocorrencias[-1]["valor"] += t["valor"]
        else:
            ocorrencias.append({"data": d, "valor": t["valor"], "t": t})
    return ocorrencias


def _parte_do_mes(dia):
    return "fim" if dia >= 26 or dia <= 3 else "inicio" if dia <= 12 else "meio"


def entradas_recorrentes(transacoes, categorias, hoje):
    hoje_iso = hoje.isoformat()
    desde = (hoje - timedelta(days=MESES_BASE * 31)).isoformat()
    fluxos = defaultdict(list)
    for t in transacoes:
        if t["natureza"] != regras.RECEITA or not t["entrada"] or t["oculto"] or not desde <= t["data"] <= hoje_iso:
            continue
        fluxos[f"cat:{t['categoriaId']}" if t["categoriaId"] in CATEGORIAS_RENDA else f"desc:{t['chave']}"].append(t)

    resultado = []
    for chave, lista in fluxos.items():
        for grupo in _grupos_por_dia(lista):
            ocorrencias = _ocorrencias(grupo)
            if len(ocorrencias) < 3 or (hoje - ocorrencias[-1]["data"]).days > 40:
                continue
            datas = [o["data"] for o in ocorrencias]
            if not 25 <= statistics.median((b - a).days for a, b in zip(datas, datas[1:])) <= 35:
                continue
            ultima = ocorrencias[-1]
            categoria = ultima["t"]["categoriaId"]
            nome_categoria = (categorias.get(categoria) or {}).get("nome")
            resultado.append({
                "id": f"entrada:{chave}:{_parte_do_mes(ultima['data'].day)}",
                "tipo": "entrada", "nome": ultima["t"]["descricao"],
                "detalhe": f"{nome_categoria or 'Entrada'} · {len(ocorrencias)} vezes nos últimos meses",
                "valor": round(statistics.median(o["valor"] for o in ocorrencias[-3:]), 2),
                "primeira": _mais_meses(ultima["data"], 1), "categoriaId": categoria,
            })
    return resultado


# ------------------------------------------------------------------ gasto do dia a dia
def _mediana_mensal(por_mes, meses_validos, mes_atual):
    meses = sorted(m for m in meses_validos if m < mes_atual)[-MESES_BASE:]
    valores = [{"mes": m, "valor": round(por_mes.get(m, 0), 2)} for m in meses]
    return (round(statistics.median(v["valor"] for v in valores), 2) if valores else 0), valores


def dia_a_dia_conta(transacoes, contas_banco, chaves_fixas, hoje):
    """Mediana do que saiu das contas por mês, fora contas fixas (que entram uma a uma)."""
    hoje_iso = hoje.isoformat()
    por_mes, meses = defaultdict(float), set()
    datas = [t["data"] for t in transacoes if t["contaId"] in contas_banco and t["data"] <= hoje_iso]
    if not datas:
        return 0, []
    primeiro = min(datas)
    for t in transacoes:
        if t["contaId"] not in contas_banco or t["data"] > hoje_iso:
            continue
        # O primeiro mês só conta se os dados começam nos primeiros dias dele (senão o mês sai pela metade).
        if t["data"][:7] == primeiro[:7] and int(primeiro[8:10]) > 5:
            continue
        meses.add(t["data"][:7])
        if t["natureza"] == regras.DESPESA and not t["oculto"] and t["chave"] not in chaves_fixas:
            por_mes[t["data"][:7]] += _valor(t)
    return _mediana_mensal(por_mes, meses, hoje_iso[:7])


def dia_a_dia_cartao(txs_cartao, chaves_assinaturas, mes_aberta):
    """Mediana das faturas fechadas sem parcelas nem assinaturas (essas entram separadas)."""
    por_mes, meses = defaultdict(float), set()
    for t in txs_cartao:
        if not t["faturaMes"] or t["natureza"] != regras.DESPESA:
            continue
        meses.add(t["faturaMes"])
        if not t["parcela"] and t["chave"] not in chaves_assinaturas:
            por_mes[t["faturaMes"]] += _valor(t)
    validos = sorted(meses)
    if len(validos) > 3:
        validos = validos[1:]  # a fatura mais antiga costuma vir incompleta (os dados começam no meio do ciclo)
    return _mediana_mensal(por_mes, validos, mes_aberta)


# ------------------------------------------------------------------ faturas
def _fatura_ja_paga(cartao, transacoes, hoje_iso):
    fechada = cartao["ultimaFechada"]
    desde = fechada["fechamento"] or fechada["vencimento"][:8] + "01"
    pagos = sum(t["valor"] for t in transacoes if t["contaId"] == cartao["contaId"] and t["entrada"]
                and t["natureza"] == regras.FATURA and desde < t["data"] <= hoje_iso)
    if pagos >= fechada["valor"] - 1:
        return True
    # Cartão importado sem as linhas de pagamento: procura o débito do mesmo valor na conta.
    return any(t["natureza"] == regras.FATURA and not t["entrada"] and desde < t["data"] <= hoje_iso
               and abs(t["valor"] - fechada["valor"]) <= 1 for t in transacoes)


def faturas_previstas(cartao, txs_cartao, assinaturas, variavel, transacoes, hoje, fim):
    """Faturas do cartão que vencem até `fim`, cada uma com o que já foi lançado e o que falta estimar."""
    aberta = cartao["faturaAberta"]
    if not aberta["vencimento"]:
        return []
    hoje_iso = hoje.isoformat()
    vencimento_aberta = date.fromisoformat(aberta["vencimento"])
    fechada = cartao["ultimaFechada"]
    resultado = []

    if fechada and fechada["aPagar"] and not _fatura_ja_paga(cartao, transacoes, hoje_iso):
        resultado.append({"vencimento": date.fromisoformat(fechada["vencimento"]), "mes": fechada["vencimento"][:7],
                          "lancado": fechada["valor"], "assinaturas": 0, "estimativa": 0, "fechada": True})

    if fechada and fechada["fechamento"]:
        fechamento_anterior = date.fromisoformat(fechada["fechamento"])
        fechamento = _mais_meses(fechamento_anterior, 1)
    else:  # sem histórico de faturas: fecha ~7 dias antes do vencimento
        fechamento = vencimento_aberta - timedelta(days=7)
        fechamento_anterior = _mais_meses(fechamento, -1)
    ciclo = max(1, (fechamento - fechamento_anterior).days)
    falta = min(1, max(0, (fechamento - hoje).days) / ciclo)
    a_cobrar = sum(a["valor"] for a in assinaturas if date.fromisoformat(a["proxima"]) <= fechamento)
    resultado.append({"vencimento": vencimento_aberta, "mes": aberta["mes"], "lancado": aberta["valor"],
                      "assinaturas": a_cobrar, "estimativa": variavel * falta, "fechada": False})

    parcelas = {p["mes"]: p["valor"] for p in cartao["proximas"]}
    mensal_assinaturas = sum(a["valor"] for a in assinaturas)
    mes = aberta["mes"]
    while True:
        mes = _mais_meses(date.fromisoformat(mes + "-01"), 1).isoformat()[:7]
        vencimento = _dia_do_mes(mes, vencimento_aberta.day)
        if vencimento > fim:
            break
        resultado.append({"vencimento": vencimento, "mes": mes, "lancado": parcelas.get(mes, 0),
                          "assinaturas": mensal_assinaturas, "estimativa": variavel, "fechada": False})
    return [f for f in resultado if hoje < f["vencimento"] <= fim or (f["fechada"] and f["vencimento"] == hoje)]


# ------------------------------------------------------------------ montagem
def montar(conexao, contas, cartoes, recorrentes, transacoes, categorias, hoje):
    if not contas:
        return None
    ajustes = carregar_ajustes(conexao)
    ignorados = set(ajustes["ignorados"])
    hoje_iso = hoje.isoformat()
    amanha = hoje + timedelta(days=1)
    fim = _fim_do_mes(_mais_meses(hoje.replace(day=1), MESES_FUTUROS))

    contas_banco = {c["id"]: c for c in contas if c["tipo"] == "BANK"}
    com_saldo = [c for c in contas_banco.values() if not c["semSaldo"]]
    datas_saldo = [c["saldoData"][:10] for c in com_saldo if c.get("saldoData")]

    fontes = []  # o que gera lançamentos previstos; cada uma pode ser ignorada pelo id
    for e in entradas_recorrentes(transacoes, categorias, hoje):
        primeira = e.pop("primeira")
        fontes.append({**e, "datas": _previstas(primeira, amanha, fim)})

    chaves_fixas = set()
    for r in recorrentes:
        if r["contaId"] not in contas_banco:
            continue
        chaves_fixas.add(r["chave"])
        fontes.append({"id": f"conta:{r['chave']}", "tipo": "conta", "nome": r["nome"], "valor": -r["valor"],
                       "detalhe": "Conta fixa" if r["tipo"] == "conta_fixa" else "Assinatura",
                       "categoriaId": r["categoriaId"],
                       "datas": _previstas(date.fromisoformat(r["proxima"]), amanha, fim)})

    auto_conta, base_conta = dia_a_dia_conta(transacoes, contas_banco, chaves_fixas, hoje)
    diario_conta = auto_conta if ajustes["diaADiaConta"] is None else ajustes["diaADiaConta"]

    # Cartões: estimativa automática por cartão; se você informou um total, ele é dividido na mesma proporção.
    por_cartao = []
    for c in cartoes:
        txs = [t for t in transacoes if t["contaId"] == c["contaId"] and not t["oculto"]]
        assinaturas = [r for r in recorrentes if r["contaId"] == c["contaId"]]
        auto, base = dia_a_dia_cartao(txs, {r["chave"] for r in assinaturas}, c["faturaAberta"]["mes"] or hoje_iso[:7])
        por_cartao.append((c, txs, assinaturas, auto, base))
    auto_cartao = round(sum(p[3] for p in por_cartao), 2)
    usado_cartao = auto_cartao if ajustes["diaADiaCartao"] is None else ajustes["diaADiaCartao"]
    ativos = [p for p in por_cartao if p[0]["faturaAberta"]["vencimento"]]
    for c, txs, assinaturas, auto, _ in por_cartao:
        if ajustes["diaADiaCartao"] is None:
            variavel = auto
        elif auto_cartao > 0:
            variavel = usado_cartao * auto / auto_cartao
        else:
            variavel = usado_cartao / len(ativos) if ativos and c["faturaAberta"]["vencimento"] else 0
        for f in faturas_previstas(c, txs, assinaturas, variavel, transacoes, hoje, fim):
            total = round(f["lancado"] + f["assinaturas"] + f["estimativa"], 2)
            if total <= 0:
                continue
            fontes.append({
                "id": f"fatura:{c['contaId']}:{f['mes']}", "tipo": "fatura", "nome": f"Fatura {c['nome']}",
                "contaId": c["contaId"], "instituicao": c["instituicao"], "final": c["final"], "valor": -total, "datas": [max(f["vencimento"], amanha)],
                "fechada": f["fechada"], "lancado": round(f["lancado"], 2), "assinaturas": round(f["assinaturas"], 2),
                "estimativa": round(f["estimativa"], 2),
                "detalhe": "Fatura fechada" if f["fechada"] else f"Fatura de {f['mes']}",
            })

    for m in ajustes["manuais"]:
        primeira = date.fromisoformat(m["data"])
        if m["mensal"]:
            datas = list(_repeticoes(primeira, amanha, fim))
        else:
            datas = [max(primeira, amanha)] if hoje <= primeira <= fim else []
        fontes.append({"id": f"manual:{m['id']}", "tipo": "manual", "nome": m["descricao"], "valor": m["valor"],
                       "detalhe": "Todo mês" if m["mensal"] else "Uma vez", "datas": datas, "manual": m})

    eventos = []
    for f in fontes:
        f["ignorado"] = f["id"] in ignorados
        f["proxima"] = f["datas"][0].isoformat() if f["datas"] else None
        if not f["ignorado"]:
            eventos += [{"fonte": f["id"], "tipo": f["tipo"], "nome": f["nome"], "data": d.isoformat(),
                         "valor": f["valor"]} for d in f["datas"]]
        del f["datas"]
    eventos.sort(key=lambda e: (e["data"], -e["valor"]))

    # Saldo dia a dia: o de hoje já inclui o que aconteceu hoje; a previsão começa amanhã.
    saldo = round(sum(c["saldo"] for c in com_saldo), 2) if com_saldo else 0.0
    por_dia = defaultdict(list)
    for e in eventos:
        por_dia[e["data"]].append(e)
    diario, alerta = [{"data": hoje_iso, "saldo": saldo}], None
    meses = {hoje_iso[:7]: _novo_mes(hoje_iso, saldo)}
    d = amanha
    while d <= fim:
        iso = d.isoformat()
        resumo = meses.get(iso[:7]) or meses.setdefault(iso[:7], _novo_mes(iso, saldo))
        gasto = diario_conta / calendar.monthrange(d.year, d.month)[1]
        resumo["diaADia"] -= gasto
        saldo -= gasto
        for e in por_dia.get(iso, []):
            campo = {"entrada": "entradas", "fatura": "faturas", "conta": "contas", "manual": "outros"}[e["tipo"]]
            resumo[campo] += e["valor"]
            saldo += e["valor"]
        resumo["final"] = saldo
        if saldo < resumo["menor"]:
            resumo["menor"], resumo["menorData"] = saldo, iso
        if alerta is None and saldo < 0 and com_saldo:
            alerta = {"data": iso, "saldo": round(saldo, 2)}
        diario.append({"data": iso, "saldo": round(saldo, 2)})
        d += timedelta(days=1)

    return {
        "hoje": hoje_iso, "fim": fim.isoformat(),
        "saldoConhecido": bool(com_saldo), "saldoInicial": diario[0]["saldo"],
        "saldoData": min(datas_saldo) if datas_saldo else None,
        "contasSemSaldo": [c["nome"] for c in contas_banco.values() if c["semSaldo"]],
        "meses": [{k: round(v, 2) if isinstance(v, float) else v for k, v in m.items()} for m in meses.values()],
        "diario": diario, "eventos": eventos, "fontes": fontes, "alerta": alerta,
        "diaADia": {
            "conta": {"auto": auto_conta, "usado": round(diario_conta, 2), "meses": base_conta},
            "cartao": {"auto": auto_cartao, "usado": round(usado_cartao, 2),
                       "meses": _somar_bases([p[4] for p in por_cartao])},
        },
        "ajustes": ajustes,
    }


def _novo_mes(data_iso, saldo):
    return {"mes": data_iso[:7], "inicial": saldo, "entradas": 0.0, "faturas": 0.0, "contas": 0.0, "diaADia": 0.0,
            "outros": 0.0, "final": saldo, "menor": saldo, "menorData": data_iso}


def _somar_bases(bases):
    soma = defaultdict(float)
    for base in bases:
        for b in base:
            soma[b["mes"]] += b["valor"]
    return [{"mes": m, "valor": round(v, 2)} for m, v in sorted(soma.items())][-MESES_BASE:]
