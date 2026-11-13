"""Importação dos arquivos exportados pelo banco (OFX, CSV, XLSX…) — o app funciona sem a Pluggy.

Cada arquivo vira transações, faturas, saldos e posições no MESMO formato que a Pluggy entrega,
então todas as telas do painel funcionam igual. Fluxo:

    analisar()   lê o arquivo e devolve uma prévia: conta sugerida, período, quantos já existem…
    confirmar()  grava. Reenviar o mesmo arquivo — ou um período que se sobrepõe ao do mês passado —
                 não duplica nada: cada lançamento ganha um id estável, e os que já existem (inclusive
                 os vindos da Pluggy) são reconhecidos por data, valor e descrição.
    desfazer()   apaga o que uma importação acrescentou.

Contas da Pluggy também podem receber arquivos (para completar o histórico anterior aos 12 meses
do Open Finance); nelas o saldo, o limite e as parcelas futuras continuam vindo só da Pluggy.
"""

import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import categorizar, leitores, regras
from .analise import itens_visiveis
from .banco import para_json

ORIGEM = "importacao"
PREFIXO = "imp-"
TIPOS = ("conta", "cartao", "investimentos")
CAT_PAGAMENTO_CARTAO = regras.CAT_PAGAMENTO_CARTAO
# Palavras que não ajudam a dizer se duas descrições são do mesmo lançamento.
GENERICAS = {"PIX", "TED", "DOC", "ENVIADO", "ENVIADA", "RECEBIDO", "RECEBIDA", "TRANSF", "TRANSFERENCIA", "PAGAMENTO",
             "PAGTO", "COMPRA", "CARTAO", "DEBITO", "CREDITO", "PELO", "PARA", "COM", "DOS", "DAS", "LTDA", "BRA", "BRASIL"}
NOMES_INSTITUICAO = sorted(set(regras.CODIGOS_BANCO.values()) | {n for _, n in leitores.PALAVRAS_EXTRAS})


# ============================================================ utilidades
def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def hash_curto(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:20]


def slug(texto):
    return re.sub(r"[^a-z0-9]+", "-", leitores.norm(texto)).strip("-") or "banco"


def mes_mais(mes, n):
    total = int(mes[:4]) * 12 + int(mes[5:7]) - 1 + n
    return f"{total // 12}-{total % 12 + 1:02d}"


def data_com_dia(mes, dia):
    ano, m = int(mes[:4]), int(mes[5:7])
    return date(ano, m, min(int(dia), calendar.monthrange(ano, m)[1])).isoformat()


def somar_meses_data(iso, n):
    return data_com_dia(mes_mais(iso[:7], n), int(iso[8:10]))


def mais_dias(iso, n):
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def numero(valor):
    """Número vindo do formulário ('1.234,56', '1234.56', 1234.56 ou vazio)."""
    if valor in (None, ""):
        return None
    v = leitores.ler_valor(valor)
    if v is None:
        raise ValueError(f"valor inválido: {valor}")
    return v


def mes_da_fatura(data, dia_fechamento, dia_vencimento):
    """Mês de vencimento da fatura em que cai uma compra, pelo dia de fechamento e de vencimento do cartão."""
    mes = data[:7] if int(data[8:10]) <= dia_fechamento else mes_mais(data[:7], 1)
    return mes if dia_vencimento > dia_fechamento else mes_mais(mes, 1)


def fechamento_da_fatura(mes, dia_fechamento, dia_vencimento):
    return data_com_dia(mes if dia_vencimento > dia_fechamento else mes_mais(mes, -1), dia_fechamento)


# ============================================================ itens e contas
def garantir_item(conexao, instituicao):
    """Uma 'conexão' por instituição para os arquivos importados (id imp-<instituicao>)."""
    item_id = PREFIXO + slug(instituicao)
    conexao.execute("INSERT OR IGNORE INTO itens (id, instituicao, status, atualizado_em, bruto, origem) "
                    "VALUES (?, ?, 'IMPORTADO', ?, '{}', ?)", (item_id, instituicao, agora(), ORIGEM))
    conexao.execute("UPDATE itens SET atualizado_em = ? WHERE id = ?", (agora(), item_id))
    return item_id


def limpar_itens_vazios(conexao):
    conexao.execute("DELETE FROM itens WHERE origem = ? AND id NOT IN (SELECT item_id FROM contas) "
                    "AND id NOT IN (SELECT item_id FROM investimentos)", (ORIGEM,))


def ler_conta(conexao, conta_id):
    linha = conexao.execute("SELECT c.id, c.item_id, c.tipo, c.bruto, i.instituicao, i.origem FROM contas c "
                            "JOIN itens i ON i.id = c.item_id WHERE c.id = ?", (conta_id,)).fetchone()
    if not linha:
        return None
    return {**dict(linha), "bruto": json.loads(linha["bruto"])}


def gravar_conta(conexao, conta_id, bruto):
    conexao.execute("UPDATE contas SET saldo = ?, bruto = ? WHERE id = ?", (bruto.get("balance"), para_json(bruto), conta_id))


def contas_disponiveis(conexao):
    """Contas que podem receber um arquivo (as importadas e as da Pluggy que estão no painel)."""
    itens = itens_visiveis(conexao)
    contas = []
    for r in conexao.execute("SELECT id, item_id, tipo, bruto FROM contas ORDER BY item_id, tipo"):
        if r["item_id"] not in itens:
            continue
        b = json.loads(r["bruto"])
        cartao = r["tipo"] == "CREDIT"
        digitos = regras.so_digitos(b.get("number"))
        transferencia = ((b.get("bankData") or {}).get("transferNumber") or "").split("/")[0]
        nome = b.get("_apelido") or ("Cartão" if cartao else
                                     {"SAVINGS_ACCOUNT": "Poupança"}.get(b.get("subtype"), "Conta corrente"))
        item = itens[r["item_id"]]
        contas.append({
            "id": r["id"], "tipo": "cartao" if cartao else "conta", "instituicao": item["instituicao"],
            "origem": item["origem"], "final": digitos[-4:],
            "rotulo": f"{item['instituicao']} · {nome}{f' {digitos[-4:]}' if digitos else ''}"
                      f"{' (Pluggy)' if item['origem'] != ORIGEM else ''}",
            "_numero": digitos, "_banco": regras.so_digitos(transferencia),
        })
    return contas


def sugerir_conta(extrato, tipo, contas, lembrada):
    candidatas = [c for c in contas if c["tipo"] == tipo]
    numero_arquivo = regras.so_digitos(extrato.get("numero")).lstrip("0")
    banco = extrato.get("banco")
    if numero_arquivo:
        for c in candidatas:
            n = c["_numero"].lstrip("0")
            if not n or (banco and c["_banco"] and c["_banco"].zfill(3) != banco):
                continue
            if tipo == "cartao":
                if n[-4:] == numero_arquivo[-4:]:
                    return c["id"]
            elif n == numero_arquivo or (min(len(n), len(numero_arquivo)) >= 4
                                         and (n.endswith(numero_arquivo) or numero_arquivo.endswith(n))):
                return c["id"]
    if lembrada and any(c["id"] == lembrada for c in candidatas):
        return lembrada
    if extrato.get("instituicao"):
        mesmas = [c for c in candidatas if c["instituicao"] == extrato["instituicao"]]
        if len(mesmas) == 1 and not numero_arquivo:
            return mesmas[0]["id"]
    return None


def criar_conta(conexao, tipo, nova, extrato, lote):
    instituicao = (nova.get("instituicao") or extrato.get("instituicao") or "").strip()[:40] or "Meu banco"
    item_id = garantir_item(conexao, instituicao)
    cartao = tipo == "cartao"
    numero_conta = regras.so_digitos(extrato.get("numero"))
    final = regras.so_digitos(nova.get("final"))[-4:]
    if final and not numero_conta.endswith(final):
        numero_conta = final
    apelido = (nova.get("nome") or "").strip()[:40] or None
    conta_id = PREFIXO + hash_curto(item_id, tipo, numero_conta or apelido or "principal")
    if conexao.execute("SELECT 1 FROM contas WHERE id = ?", (conta_id,)).fetchone():
        return conta_id
    banco_cod = extrato.get("banco") or next((c for c, n in regras.CODIGOS_BANCO.items() if n == instituicao), "")
    bruto = {
        "id": conta_id, "itemId": item_id, "type": "CREDIT" if cartao else "BANK",
        "subtype": "CREDIT_CARD" if cartao else (extrato.get("subtipo") or "CHECKING_ACCOUNT"),
        "name": apelido or ("Cartão" if cartao else instituicao), "marketingName": apelido,
        "number": numero_conta, "balance": 0, "currencyCode": "BRL", "owner": None, "taxNumber": None,
        "bankData": None if cartao else {"transferNumber": f"{banco_cod}/{extrato.get('agencia') or ''}/{numero_conta}"},
        "creditData": {"creditLimit": None, "availableCreditLimit": None, "brand": None, "level": None} if cartao else None,
        "origem": ORIGEM, "_apelido": apelido, "_criadaPorLote": lote,
    }
    conexao.execute("INSERT INTO contas (id, item_id, tipo, saldo, bruto) VALUES (?, ?, ?, ?, ?)",
                    (conta_id, item_id, bruto["type"], 0, para_json(bruto)))
    return conta_id


# ============================================================ leitura com formatos lembrados
def formato_lembrado(conexao, assinatura):
    linha = conexao.execute("SELECT * FROM formatos_arquivo WHERE assinatura = ?", (assinatura,)).fetchone() if assinatura else None
    return dict(linha) if linha else {}


def ler(conexao, nome, conteudo, mapeamento=None, hoje=None):
    """Extratos do arquivo. Se as colunas não foram reconhecidas, tenta o mapeamento que você já fez antes."""
    extratos = leitores.ler_arquivo(nome, conteudo, mapeamento, hoje)
    if not mapeamento and len(extratos) == 1 and extratos[0]["precisaMapeamento"]:
        salvo = formato_lembrado(conexao, extratos[0]["assinatura"]).get("mapeamento")
        if salvo:
            mapeamento = json.loads(salvo)
            extratos = leitores.ler_arquivo(nome, conteudo, mapeamento, hoje)
    return extratos, mapeamento


# ============================================================ conversão para o formato da Pluggy
def config_fatura(extrato, opcoes, bruto_conta, hoje):
    """Vencimento, dia de fechamento e se a fatura está fechada — do formulário, do que já se sabe do cartão ou estimado."""
    lancamentos = extrato["lancamentos"]
    # Parcelas a partir da 2ª podem vir com a data da compra original; não contam para medir o período do arquivo.
    datas = sorted(l["data"] for l in lancamentos if not ((l["parcela"] or l["parcelaSufixo"] or [0])[0] > 1))
    datas = datas or sorted(l["data"] for l in lancamentos) or [hoje]
    extensao = (date.fromisoformat(datas[-1]) - date.fromisoformat(datas[0])).days
    lembrado = (bruto_conta or {}).get("_fatura") or {}
    no_nome = extrato.get("dataNoNome") if extensao <= 45 else None
    vencimento = opcoes.get("vencimento") or None
    dia_venc = int(opcoes.get("diaVencimento") or (vencimento and vencimento[8:10]) or lembrado.get("diaVencimento")
                   or (no_nome and no_nome[8:10]) or 10)
    dia_fech = int(opcoes.get("diaFechamento") or lembrado.get("diaFechamento") or (dia_venc - 7 if dia_venc > 7 else dia_venc + 21))
    if not 1 <= dia_venc <= 31 or not 1 <= dia_fech <= 31:
        raise ValueError("dia de vencimento/fechamento inválido")
    modo = opcoes.get("modoFatura") or ("varios" if extensao > 45 else "unica")
    if not vencimento:
        if no_nome:
            vencimento = no_nome
        else:
            # Parcelas com data da compra original não servem de referência.
            base = max((l["data"] for l in lancamentos if not (l["parcela"] and l["parcela"][0] > 1)), default=datas[-1])
            vencimento = data_com_dia(mes_da_fatura(base, dia_fech, dia_venc), dia_venc)
    fechamento = fechamento_da_fatura(vencimento[:7], dia_fech, dia_venc)
    fechada = opcoes["fechada"] if isinstance(opcoes.get("fechada"), bool) else fechamento < hoje
    return {"modo": modo, "vencimento": vencimento, "diaVencimento": dia_venc, "diaFechamento": dia_fech,
            "fechada": fechada, "extensao": extensao}


def preparar(extrato, tipo, conta_id, cfg, aprendido):
    """Lançamentos no formato da Pluggy (amount/type, creditCardMetadata…), cada um com id estável."""
    cartao = tipo == "cartao"
    lancamentos = extrato["lancamentos"]
    # No cartão, compras são a maioria: o sinal mais comum do arquivo é o de compra (cada banco usa um).
    compra_positiva = sum(l["valor"] > 0 for l in lancamentos) >= sum(l["valor"] < 0 for l in lancamentos)
    fonte = extrato.get("assinatura") or extrato["formato"]
    ocorrencias = Counter()
    txs = []
    for l in lancamentos:
        parcela = l["parcela"] or (l["parcelaSufixo"] if cartao else None)
        descricao = l["descricao"]
        if parcela and l["trechoParcela"]:
            descricao = re.sub(r"\s+", " ", descricao.replace(l["trechoParcela"], " "))
            descricao = re.sub(r"[\s\-–|]+$", "", descricao).strip() or l["descricao"]
        if l["idOrigem"]:
            tx_id = PREFIXO + hash_curto(conta_id, "id", l["idOrigem"])
        else:
            chave = (l["data"], regras.normalizar(l["descricao"]), l["valor"])
            ocorrencias[chave] += 1
            tx_id = PREFIXO + hash_curto(conta_id, *chave, ocorrencias[chave])
        valor = l["valor"]
        if cartao:
            compra = (valor > 0) == compra_positiva
            tipo_tx, valor = ("DEBIT", abs(valor)) if compra else ("CREDIT", -abs(valor))
        else:
            tipo_tx = "CREDIT" if valor > 0 else "DEBIT"
        data, meta = l["data"], None
        if cartao:
            if cfg["modo"] == "unica":
                mes_fatura = cfg["vencimento"][:7]
                if parcela and parcela[0] > 1 and data < mais_dias(cfg["vencimento"], -50):
                    data = somar_meses_data(data, parcela[0] - 1)  # o banco repetiu a data da compra original
            else:
                mes_fatura = mes_da_fatura(data, cfg["diaFechamento"], cfg["diaVencimento"])
            meta = {"billForecastDate": mes_fatura, "purchaseDate": l["data"]}
            if parcela:
                meta.update(installmentNumber=parcela[0], totalInstallments=parcela[1],
                            paymentType="INSTALLMENT", purchaseDate=mes_mais(mes_fatura, -(parcela[0] - 1)))
        categoria, por = categorizar.categorizar(descricao, tipo_tx == "CREDIT", cartao, aprendido)
        txs.append({
            "id": tx_id, "accountId": conta_id, "date": data, "description": descricao, "descriptionRaw": l["descricao"],
            "amount": round(valor, 2), "type": tipo_tx, "status": "POSTED", "currencyCode": "BRL",
            "category": None, "categoryId": categoria, "operationType": categorizar.operacao(descricao),
            "creditCardMetadata": meta, "paymentData": None, "origem": ORIGEM, "_fonte": fonte,
            "_idOrigem": l["idOrigem"], "_categoriaPor": por,
        })
    return txs


# ============================================================ duplicados
def palavras(descricao):
    return {p for p in re.findall(r"[A-Z]{3,}", regras.normalizar(descricao)) if p not in GENERICAS}


def planejar(conexao, conta_id, txs, cartao):
    """Separa (novas, já importadas antes — serão atualizadas, duplicadas de outra fonte — ignoradas)."""
    if not txs or not conta_id:
        return list(txs), [], []
    por_id = {r["id"]: json.loads(r["bruto"]) for r in conexao.execute(
        "SELECT id, bruto FROM transacoes WHERE id IN (SELECT value FROM json_each(?))", (json.dumps([t["id"] for t in txs]),))}
    datas = sorted(t["date"] for t in txs)
    livres = defaultdict(list)
    for r in conexao.execute("SELECT id, bruto FROM transacoes WHERE conta_id = ? AND data BETWEEN ? AND ?",
                             (conta_id, mais_dias(datas[0], -4), mais_dias(datas[-1], 4))):
        e = json.loads(r["bruto"])
        if r["id"] not in por_id and not e.get("_projetada"):
            livres[(round(abs(e.get("amount") or 0), 2), e.get("type"))].append(e)
    limite_dias = 3 if cartao else 1
    novas, atualizar, duplicadas = [], [], []
    for t in txs:
        if t["id"] in por_id:
            t["_manterLote"] = por_id[t["id"]].get("_lote")
            atualizar.append(t)
            continue
        melhor, nota = None, None
        candidatos = livres.get((round(abs(t["amount"]), 2), t["type"]), [])
        for e in candidatos:
            dias = abs((date.fromisoformat(e["date"][:10]) - date.fromisoformat(t["date"])).days)
            if dias > limite_dias:
                continue
            comuns = len(palavras(e.get("description")) & palavras(t["description"]))
            # Mesmo formato de arquivo com id diferente só é o mesmo lançamento se a descrição for parecida
            # (ex.: compra pendente que mudou de nome). De outra fonte (Pluggy, OFX × CSV) basta data e valor.
            if e.get("_fonte") == t["_fonte"] and not comuns:
                continue
            if nota is None or (dias, -comuns) < nota:
                melhor, nota = e, (dias, -comuns)
        if melhor:
            candidatos.remove(melhor)
            duplicadas.append(t)
        else:
            novas.append(t)
    return novas, atualizar, duplicadas


def gravar_transacoes(conexao, txs, lote):
    linhas = []
    for t in txs:
        t["_lote"] = t.pop("_manterLote", None) or lote
        linhas.append((t["id"], t["accountId"], t["date"], para_json(t)))
    conexao.executemany("INSERT OR REPLACE INTO transacoes (id, conta_id, data, bruto) VALUES (?, ?, ?, ?)", linhas)


# ============================================================ faturas, parcelas futuras e saldo
def faturas_do_arquivo(txs, cfg, opcoes, hoje):
    """Faturas fechadas que o arquivo permite montar: [{mes, vencimento, fechamento, total}]."""
    totais = defaultdict(float)
    for t in txs:
        if t["type"] == "CREDIT" and t["categoryId"] == CAT_PAGAMENTO_CARTAO:
            continue  # pagamento da fatura anterior não entra no total desta
        totais[t["creditCardMetadata"]["billForecastDate"]] += t["amount"]
    if cfg["modo"] == "unica":
        if not cfg["fechada"]:
            return []
        mes = cfg["vencimento"][:7]
        total = numero(opcoes.get("totalFatura"))
        return [{"mes": mes, "vencimento": cfg["vencimento"], "fechamento": None,
                 "total": round(total if total is not None else totais.get(mes, 0), 2)}]
    inicio = min(t["date"] for t in txs) if txs else hoje
    faturas = []
    for mes, total in sorted(totais.items()):
        fechamento = fechamento_da_fatura(mes, cfg["diaFechamento"], cfg["diaVencimento"])
        comeco = mais_dias(fechamento_da_fatura(mes_mais(mes, -1), cfg["diaFechamento"], cfg["diaVencimento"]), 1)
        if fechamento < hoje and inicio <= mais_dias(comeco, 3):  # fatura inteira no arquivo e já fechada
            faturas.append({"mes": mes, "vencimento": data_com_dia(mes, cfg["diaVencimento"]), "fechamento": fechamento,
                            "total": round(total, 2)})
    return faturas


def gravar_faturas(conexao, conta_id, faturas, lote):
    gravadas = 0
    for f in faturas:
        fatura_id = f"{PREFIXO}fat-{hash_curto(conta_id, f['mes'])}"
        outras = conexao.execute("SELECT id, bruto FROM faturas WHERE conta_id = ? AND substr(vencimento, 1, 7) = ?",
                                 (conta_id, f["mes"])).fetchall()
        if any(o["id"] != fatura_id for o in outras):
            continue  # já existe fatura desse mês vinda de outra fonte (ex.: Pluggy)
        anterior = json.loads(outras[0]["bruto"]) if outras else {}
        bruto = {"id": fatura_id, "dueDate": f"{f['vencimento']}T00:00:00.000Z",
                 "billClosingDate": f"{f['fechamento']}T00:00:00.000Z" if f["fechamento"] else None,
                 "totalAmount": f["total"], "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": None,
                 "origem": ORIGEM, "_lote": anterior.get("_lote") or lote}
        conexao.execute("INSERT OR REPLACE INTO faturas (id, conta_id, vencimento, total, bruto) VALUES (?, ?, ?, ?, ?)",
                        (fatura_id, conta_id, f["vencimento"], f["total"], para_json(bruto)))
        gravadas += 1
    return gravadas


def projetar_parcelas(conexao, conta_id):
    """Parcelas futuras de compras parceladas do cartão importado (a Pluggy as entrega prontas; arquivos, não).

    Refeitas a cada importação: quando a fatura do mês seguinte chega, a parcela real substitui a projetada.
    """
    conexao.execute("DELETE FROM transacoes WHERE conta_id = ? AND json_extract(bruto, '$._projetada') = 1", (conta_id,))
    ultimas = {}
    for r in conexao.execute("SELECT bruto FROM transacoes WHERE conta_id = ?", (conta_id,)):
        t = json.loads(r["bruto"])
        meta = t.get("creditCardMetadata") or {}
        k, n = meta.get("installmentNumber") or 0, meta.get("totalInstallments") or 0
        if n < 2 or not k or t.get("type") != "DEBIT":
            continue
        chave = (regras.chave_estabelecimento(t.get("description")), n, meta.get("purchaseDate") or "", round(t["amount"]))
        if chave not in ultimas or k > ultimas[chave][0]:
            ultimas[chave] = (k, t)
    linhas = []
    for chave, (k, t) in ultimas.items():
        for j in range(k + 1, chave[1] + 1):
            meta = {**t["creditCardMetadata"], "installmentNumber": j,
                    "billForecastDate": mes_mais(t["creditCardMetadata"]["billForecastDate"], j - k)}
            p = {**t, "id": f"proj-{hash_curto(conta_id, *chave, j)}", "date": somar_meses_data(t["date"], j - k),
                 "creditCardMetadata": meta, "_projetada": 1, "_lote": None}
            linhas.append((p["id"], conta_id, p["date"], para_json(p)))
    conexao.executemany("INSERT OR REPLACE INTO transacoes (id, conta_id, data, bruto) VALUES (?, ?, ?, ?)", linhas)
    return len(linhas)


def ancorar_saldo(conexao, conta_id, saldo, data_saldo, lote=None):
    """Saldo conhecido numa data. Só substitui a âncora atual se for mais recente (arquivo antigo não volta o saldo).

    Cada âncora fica guardada com a importação que a trouxe (_ancoras): ao desfazer essa importação, volta a valer
    a mais recente das que sobraram. lote=None é o saldo digitado na edição da conta."""
    conta = ler_conta(conexao, conta_id)
    b = conta["bruto"]
    if b.get("origem") != ORIGEM or b.get("type") != "BANK":
        return False
    ancoras = b.get("_ancoras")
    if ancoras is None:  # conta de antes das âncoras por importação: a atual vira a primeira, sem lote
        ancoras = [{"data": b["_saldoData"], "valor": b["_saldoValor"], "lote": None}] if b.get("_saldoData") else []
    b["_ancoras"] = ancoras + [{"data": data_saldo, "valor": round(saldo, 2), "lote": lote}]
    if b.get("_saldoData") and data_saldo < b["_saldoData"]:
        gravar_conta(conexao, conta_id, b)
        return False
    b["_saldoValor"], b["_saldoData"] = round(saldo, 2), data_saldo
    gravar_conta(conexao, conta_id, b)
    conexao.execute("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) VALUES (?, ?, 'BANK', ?)",
                    (data_saldo, conta_id, round(saldo, 2)))
    return True


def desancorar_lote(conexao, conta_id, lote):
    """Desfazer: tira as âncoras de saldo da importação e volta para a mais recente das que sobraram.
    Os saldos guardados por ela (na data da âncora e depois do último lançamento que sobrou) saem do histórico."""
    conta = ler_conta(conexao, conta_id)
    b = conta["bruto"] if conta else {}
    ancoras = b.get("_ancoras") or []
    removidas = [a for a in ancoras if a["lote"] == lote]
    if not removidas:
        return
    restantes = [a for a in ancoras if a["lote"] != lote]
    atual = None
    for a in restantes:  # a de data mais recente; no empate, a gravada por último
        if atual is None or a["data"] >= atual["data"]:
            atual = a
    b["_ancoras"] = restantes
    b["_saldoValor"], b["_saldoData"] = (atual["valor"], atual["data"]) if atual else (None, None)
    if not atual:  # sem saldo conhecido, nenhum saldo guardado desta conta continua valendo
        b["balance"] = 0
        gravar_conta(conexao, conta_id, b)
        conexao.execute("DELETE FROM historico_saldos WHERE ref_id = ?", (conta_id,))
        return
    gravar_conta(conexao, conta_id, b)
    ultima = conexao.execute("SELECT max(data) FROM transacoes WHERE conta_id = ?", (conta_id,)).fetchone()[0]
    limite = max(filter(None, (ultima, atual["data"])))
    conexao.execute("DELETE FROM historico_saldos WHERE ref_id = ? AND (data > ? OR data IN (SELECT value FROM json_each(?)))",
                    (conta_id, limite, json.dumps([a["data"] for a in removidas])))
    conexao.execute("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) VALUES (?, ?, 'BANK', ?)",
                    (atual["data"], conta_id, atual["valor"]))


def recalcular_saldo(conexao, conta_id):
    """Saldo atual = última âncora + lançamentos importados depois dela."""
    conta = ler_conta(conexao, conta_id)
    if not conta:
        return
    b = conta["bruto"]
    if b.get("origem") != ORIGEM or b.get("type") != "BANK" or b.get("_saldoData") is None:
        return
    soma, ultima = conexao.execute(
        "SELECT coalesce(sum(json_extract(bruto, '$.amount')), 0), max(data) FROM transacoes WHERE conta_id = ? AND data > ?",
        (conta_id, b["_saldoData"])).fetchone()
    b["balance"] = round(b["_saldoValor"] + soma, 2)
    gravar_conta(conexao, conta_id, b)
    if ultima:
        conexao.execute("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) VALUES (?, ?, 'BANK', ?)",
                        (ultima, conta_id, b["balance"]))


def lembrar_formato(conexao, extrato, tipo, conta_id, mapeamento):
    assinatura = extrato.get("assinatura")
    if not assinatura or assinatura.startswith("posicoes"):
        return
    sem_cabecalho = extrato.get("linhaCabecalho") == -1  # 'sem cabeçalho, 3 colunas' serve para vários bancos
    conexao.execute("INSERT OR REPLACE INTO formatos_arquivo (assinatura, mapeamento, tipo, conta_id, atualizado_em) "
                    "VALUES (?, ?, ?, ?, ?)", (assinatura, para_json(mapeamento) if mapeamento else None, tipo,
                                               None if sem_cabecalho else conta_id, agora()))


# ============================================================ prévia
def nomes_categorias(conexao):
    return {r["id"]: r["descricao_pt"] or r["descricao"] for r in conexao.execute("SELECT id, descricao, descricao_pt FROM categorias")}


def analisar(conexao, nome, conteudo, opcoes=None, hoje=None):
    """Prévia de cada parte do arquivo, sem gravar nada."""
    opcoes = opcoes or {}
    hoje_iso = (hoje or date.today()).isoformat()
    extratos, mapeamento = ler(conexao, nome, conteudo, opcoes.get("mapeamento"), hoje)
    contas = contas_disponiveis(conexao)
    aprendido = categorizar.aprender(conexao)
    categorias = nomes_categorias(conexao)
    previas = []
    for parte, extrato in enumerate(extratos):
        mesma_parte = int(opcoes.get("parte", parte)) == parte
        o = opcoes if mesma_parte else {}
        previa = {"parte": parte, "arquivo": nome, "formato": extrato["formato"], "avisos": list(extrato["avisos"]),
                  "instituicao": extrato["instituicao"], "instituicoes": NOMES_INSTITUICAO, "mapeamento": mapeamento}
        if extrato["precisaMapeamento"]:
            previa.update(precisaMapeamento=True, cabecalho=extrato["cabecalho"], amostra=extrato["amostra"],
                          linhaCabecalho=extrato.get("linhaCabecalho", -1), aba=extrato.get("aba"),
                          colunas=extrato["colunas"])
            previas.append(previa)
            continue
        lembrado = formato_lembrado(conexao, extrato["assinatura"])
        tipo = o.get("tipo") or (extrato["tipo"] if extrato["formato"] == "OFX" else None) or lembrado.get("tipo") or extrato["tipo"]
        if tipo not in TIPOS:
            tipo = "conta"
        previa["tipo"] = tipo
        if tipo == "investimentos":
            previas.append({**previa, **previa_posicoes(extrato, o, hoje_iso)})
            continue
        if not extrato["lancamentos"]:
            previa["avisos"].append("Nenhum lançamento encontrado nesta parte do arquivo.")
        conta_id = o.get("contaId") if "contaId" in o else sugerir_conta(extrato, tipo, contas, lembrado.get("conta_id"))
        conta = ler_conta(conexao, conta_id) if conta_id else None
        if conta_id and (not conta or ("cartao" if conta["tipo"] == "CREDIT" else "conta") != tipo):
            conta_id, conta = None, None
        cfg = config_fatura(extrato, o, conta and conta["bruto"], hoje_iso) if tipo == "cartao" else None
        txs = preparar(extrato, tipo, conta_id or "nova", cfg, aprendido)
        novas, atualizar, duplicadas = planejar(conexao, conta_id, txs, tipo == "cartao") if conta_id else (txs, [], [])
        ids_novas = {t["id"] for t in novas}
        datas = sorted(t["date"] for t in txs)
        entradas = sum(t["amount"] for t in txs if t["type"] == "CREDIT" and tipo == "conta")
        saidas = sum(-t["amount"] for t in txs if t["type"] == "DEBIT" and tipo == "conta")
        previa.update(
            contas=[{k: v for k, v in c.items() if not k.startswith("_")} for c in contas if c["tipo"] == tipo],
            contaId=conta_id, contaOrigem=conta["origem"] if conta else None,
            novaConta={"instituicao": extrato["instituicao"] or "", "final": regras.so_digitos(extrato.get("numero"))[-4:], "nome": ""},
            periodo=[datas[0], datas[-1]] if datas else None, quantidade=len(txs), novas=len(novas),
            atualizadas=len(atualizar), duplicadas=len(duplicadas), entradas=round(entradas, 2), saidas=round(saidas, 2),
            saldo=extrato["saldo"], saldoData=extrato["saldoData"] or (datas[-1] if datas and extrato["saldo"] is not None else None),
            parcelas=sum(1 for t in txs if (t["creditCardMetadata"] or {}).get("totalInstallments")),
            amostra=[{"data": t["date"], "descricao": t["description"], "valor": t["amount"] if tipo == "conta" else -t["amount"],
                      "parcela": [t["creditCardMetadata"]["installmentNumber"], t["creditCardMetadata"]["totalInstallments"]]
                      if (t["creditCardMetadata"] or {}).get("totalInstallments") else None,
                      "categoria": categorias.get(t["categoryId"], "Outros"), "nova": t["id"] in ids_novas}
                     for t in sorted(txs, key=lambda t: t["date"], reverse=True)[:8]],
        )
        if cfg:
            faturas = faturas_do_arquivo(txs, cfg, o, hoje_iso)
            mes = cfg["vencimento"][:7]
            total_mes = sum(t["amount"] for t in txs if t["creditCardMetadata"]["billForecastDate"] == mes
                            and not (t["type"] == "CREDIT" and t["categoryId"] == CAT_PAGAMENTO_CARTAO))
            previa.update(fatura={**cfg, "total": round(total_mes, 2), "faturasFechadas": faturas},
                          pagamentos=sum(1 for t in txs if t["categoryId"] == CAT_PAGAMENTO_CARTAO and t["type"] == "CREDIT"))
        if conta and conta["origem"] != ORIGEM:
            previa["avisos"].append("Esta conta é sincronizada pela Pluggy: o arquivo só completa o histórico. "
                                    "Lançamentos que a Pluggy já trouxe são ignorados, e nos últimos 12 meses ela continua valendo.")
        previas.append(previa)
    return previas


def previa_posicoes(extrato, opcoes, hoje_iso):
    posicoes = extrato["posicoes"]
    instituicoes = sorted({p["instituicao"] for p in posicoes if p["instituicao"]})
    return {"posicoes": posicoes[:300], "total": round(sum(p["saldo"] for p in posicoes), 2), "quantidade": len(posicoes),
            "semInstituicao": sum(1 for p in posicoes if not p["instituicao"]), "instituicoesArquivo": instituicoes,
            "dataPosicao": opcoes.get("dataPosicao") or extrato["dataPosicao"] or hoje_iso,
            "instituicaoPadrao": opcoes.get("instituicao") or ""}


# ============================================================ gravação
def confirmar(conexao, nome, conteudo, opcoes, hoje=None):
    """Grava uma parte do arquivo com as escolhas da prévia. Tudo numa transação só."""
    hoje_iso = (hoje or date.today()).isoformat()
    extratos, mapeamento = ler(conexao, nome, conteudo, opcoes.get("mapeamento"), hoje)
    parte = int(opcoes.get("parte", 0))
    if not 0 <= parte < len(extratos):
        raise ValueError("parte do arquivo inexistente")
    extrato = extratos[parte]
    if extrato["precisaMapeamento"]:
        raise ValueError("indique as colunas de data, descrição e valor antes de importar")
    tipo = opcoes.get("tipo") or extrato["tipo"]
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo}")
    if tipo == "investimentos":
        return confirmar_posicoes(conexao, nome, extrato, opcoes, hoje_iso)
    if not extrato["lancamentos"]:
        raise ValueError("nenhum lançamento para importar")
    cartao = tipo == "cartao"
    aprendido = categorizar.aprender(conexao)

    with conexao:
        lote = conexao.execute("INSERT INTO importacoes (criada_em, arquivo, formato, tipo) VALUES (?, ?, ?, ?)",
                               (agora(), nome[:200], extrato["formato"], tipo)).lastrowid
        conta_id = opcoes.get("contaId") or criar_conta(conexao, tipo, opcoes.get("novaConta") or {}, extrato, lote)
        conta = ler_conta(conexao, conta_id)
        if not conta or ("cartao" if conta["tipo"] == "CREDIT" else "conta") != tipo:
            raise ValueError("conta de destino inválida para este tipo de arquivo")
        importada = conta["origem"] == ORIGEM
        cfg = config_fatura(extrato, opcoes, conta["bruto"], hoje_iso) if cartao else None
        if cartao and importada:
            conexao.execute("DELETE FROM transacoes WHERE conta_id = ? AND json_extract(bruto, '$._projetada') = 1", (conta_id,))
        txs = preparar(extrato, tipo, conta_id, cfg, aprendido)
        novas, atualizar, duplicadas = planejar(conexao, conta_id, txs, cartao)
        gravar_transacoes(conexao, novas + atualizar, lote)

        resumo = {"conta": conta_id, "instituicao": conta["instituicao"], "novas": len(novas), "atualizadas": len(atualizar),
                  "duplicadas": len(duplicadas), "faturas": 0, "projetadas": 0, "saldo": None}
        if cartao:
            resumo["faturas"] = gravar_faturas(conexao, conta_id, faturas_do_arquivo(txs, cfg, opcoes, hoje_iso), lote)
            if importada:
                b = conta["bruto"]
                b["_fatura"] = {"diaVencimento": cfg["diaVencimento"], "diaFechamento": cfg["diaFechamento"]}
                b.setdefault("creditData", {})["balanceDueDate"] = f"{cfg['vencimento']}T00:00:00.000Z"
                gravar_conta(conexao, conta_id, b)
                resumo["projetadas"] = projetar_parcelas(conexao, conta_id)
        elif importada:
            saldo, data_saldo = numero(opcoes.get("saldo")), opcoes.get("saldoData")
            if saldo is not None:
                ancorar_saldo(conexao, conta_id, saldo, data_saldo or hoje_iso, lote)
            elif extrato["saldo"] is not None:
                ancorar_saldo(conexao, conta_id, extrato["saldo"], extrato["saldoData"] or max(t["date"] for t in txs), lote)
            recalcular_saldo(conexao, conta_id)
            resumo["saldo"] = ler_conta(conexao, conta_id)["bruto"].get("balance")
        lembrar_formato(conexao, extrato, tipo, conta_id, mapeamento)
        conexao.execute("UPDATE itens SET atualizado_em = ? WHERE id = ?", (agora(), conta["item_id"]))
        datas = sorted(t["date"] for t in txs)
        conexao.execute("UPDATE importacoes SET conta_id = ?, inicio = ?, fim = ?, novas = ?, existentes = ?, resumo = ? WHERE id = ?",
                        (conta_id, datas[0], datas[-1], len(novas), len(atualizar) + len(duplicadas), para_json(resumo), lote))
    resumo["lote"] = lote
    return resumo


def confirmar_posicoes(conexao, nome, extrato, opcoes, hoje_iso):
    """Posição de investimentos: substitui a carteira importada de cada instituição do arquivo."""
    posicoes = extrato["posicoes"]
    if not posicoes:
        raise ValueError("nenhuma posição de investimento encontrada")
    data_posicao = opcoes.get("dataPosicao") or extrato["dataPosicao"] or hoje_iso
    padrao = (opcoes.get("instituicao") or "").strip()[:40]
    if any(not p["instituicao"] for p in posicoes) and not padrao:
        raise ValueError("informe a instituição das posições que vieram sem ela")
    por_instituicao = defaultdict(list)
    for p in posicoes:
        por_instituicao[p["instituicao"] or padrao].append(p)
    with conexao:
        lote = conexao.execute("INSERT INTO importacoes (criada_em, arquivo, formato, tipo) VALUES (?, ?, ?, 'investimentos')",
                               (agora(), nome[:200], extrato["formato"])).lastrowid
        fonte = extrato.get("assinatura") or "posicoes"
        for instituicao, lista in por_instituicao.items():
            item_id = garantir_item(conexao, instituicao)
            # A posição nova substitui a anterior do mesmo tipo de arquivo (ex.: B3 não apaga a planilha manual).
            conexao.execute("DELETE FROM investimentos WHERE item_id = ? AND coalesce(json_extract(bruto, '$._fonte'), ?) = ?",
                            (item_id, fonte, fonte))
            vistos = Counter()
            for p in lista:
                vistos[(p["nome"], p["vencimento"])] += 1
                pid = PREFIXO + hash_curto(item_id, fonte, p["nome"], p["vencimento"], vistos[(p["nome"], p["vencimento"])])
                bruto = {"id": pid, "itemId": item_id, "name": p["nome"], "type": p["tipo"], "subtype": p["subtipo"],
                         "balance": p["saldo"], "currencyCode": "BRL", "dueDate": p["vencimento"], "rateType": p["indexador"],
                         "rate": p["taxa"], "issuer": p["emissor"], "status": "ACTIVE", "origem": ORIGEM,
                         "_lote": lote, "_dataPosicao": data_posicao, "_fonte": fonte}
                if p.get("quantidade"):  # ações e FIIs da planilha da B3: preço do dia e proventos a receber
                    bruto.update(code=p.get("codigo"), quantity=p["quantidade"], value=round(p["saldo"] / p["quantidade"], 6))
                conexao.execute("INSERT OR REPLACE INTO investimentos (id, item_id, saldo, bruto) VALUES (?, ?, ?, ?)",
                                (pid, item_id, p["saldo"], para_json(bruto)))
                conexao.execute("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) VALUES (?, ?, 'INVESTIMENTO', ?)",
                                (data_posicao, pid, p["saldo"]))
        limpar_itens_vazios(conexao)
        resumo = {"posicoes": len(posicoes), "instituicoes": sorted(por_instituicao), "total": round(sum(p["saldo"] for p in posicoes), 2),
                  "dataPosicao": data_posicao}
        conexao.execute("UPDATE importacoes SET inicio = ?, fim = ?, novas = ?, existentes = 0, resumo = ? WHERE id = ?",
                        (data_posicao, data_posicao, len(posicoes), para_json(resumo), lote))
    resumo["lote"] = lote
    return resumo


# ============================================================ desfazer, editar e excluir
def desfazer(conexao, lote):
    lote = int(lote)
    importacao = conexao.execute("SELECT * FROM importacoes WHERE id = ?", (lote,)).fetchone()
    if not importacao:
        raise ValueError("importação não encontrada")
    with conexao:
        ids = json.dumps([r["id"] for r in conexao.execute(
            "SELECT id FROM transacoes WHERE json_extract(bruto, '$._lote') = ?", (lote,))])
        conexao.execute("DELETE FROM ajustes WHERE transacao_id IN (SELECT value FROM json_each(?))", (ids,))
        removidas = conexao.execute("DELETE FROM transacoes WHERE json_extract(bruto, '$._lote') = ?", (lote,)).rowcount
        conexao.execute("DELETE FROM faturas WHERE json_extract(bruto, '$._lote') = ?", (lote,))
        conexao.execute("DELETE FROM investimentos WHERE json_extract(bruto, '$._lote') = ?", (lote,))
        conta_id = importacao["conta_id"]
        conta = ler_conta(conexao, conta_id) if conta_id else None
        if conta:
            vazia = not conexao.execute("SELECT 1 FROM transacoes WHERE conta_id = ? AND coalesce(json_extract(bruto, '$._projetada'), 0) = 0 "
                                        "LIMIT 1", (conta_id,)).fetchone()
            if vazia and conta["bruto"].get("_criadaPorLote") == lote:
                apagar_conta(conexao, conta_id)
            elif conta["origem"] == ORIGEM:
                if conta["tipo"] == "CREDIT":
                    projetar_parcelas(conexao, conta_id)
                else:
                    desancorar_lote(conexao, conta_id, lote)
                    recalcular_saldo(conexao, conta_id)
        conexao.execute("DELETE FROM importacoes WHERE id = ?", (lote,))
        limpar_itens_vazios(conexao)
    return {"ok": True, "removidas": removidas}


def apagar_conta(conexao, conta_id):
    ids = json.dumps([r["id"] for r in conexao.execute("SELECT id FROM transacoes WHERE conta_id = ?", (conta_id,))])
    conexao.execute("DELETE FROM ajustes WHERE transacao_id IN (SELECT value FROM json_each(?))", (ids,))
    conexao.execute("DELETE FROM transacoes WHERE conta_id = ?", (conta_id,))
    conexao.execute("DELETE FROM faturas WHERE conta_id = ?", (conta_id,))
    conexao.execute("DELETE FROM historico_saldos WHERE ref_id = ?", (conta_id,))
    conexao.execute("DELETE FROM contas WHERE id = ?", (conta_id,))
    conexao.execute("DELETE FROM importacoes WHERE conta_id = ?", (conta_id,))
    conexao.execute("UPDATE formatos_arquivo SET conta_id = NULL WHERE conta_id = ?", (conta_id,))


def excluir_conta(conexao, conta_id):
    conta = ler_conta(conexao, conta_id)
    if not conta or conta["origem"] != ORIGEM:
        raise ValueError("só contas importadas podem ser excluídas por aqui")
    with conexao:
        apagar_conta(conexao, conta_id)
        limpar_itens_vazios(conexao)
    return {"ok": True}


def editar_conta(conexao, corpo):
    """Apelido, instituição, final, saldo atual, limite e dias de fechamento/vencimento de uma conta importada."""
    conta_id = str(corpo["contaId"])
    conta = ler_conta(conexao, conta_id)
    if not conta or conta["origem"] != ORIGEM:
        raise ValueError("só contas importadas podem ser editadas (as da Pluggy vêm do banco)")
    b = conta["bruto"]
    hoje_iso = date.today().isoformat()
    with conexao:
        if "nome" in corpo:
            apelido = (corpo.get("nome") or "").strip()[:40] or None
            b["_apelido"], b["marketingName"] = apelido, apelido
            b["name"] = apelido or ("Cartão" if b["type"] == "CREDIT" else conta["instituicao"])
        if "final" in corpo:
            b["number"] = regras.so_digitos(corpo.get("final"))[-4:] or b.get("number")
        if b["type"] == "CREDIT":
            credito = b.setdefault("creditData", {}) or {}
            if "limite" in corpo:
                credito["creditLimit"] = numero(corpo.get("limite"))
            if "disponivel" in corpo:
                credito["availableCreditLimit"] = numero(corpo.get("disponivel"))
            b["creditData"] = credito
            fatura = b.get("_fatura") or {}
            for campo in ("diaVencimento", "diaFechamento"):
                if corpo.get(campo):
                    dia = int(corpo[campo])
                    if not 1 <= dia <= 31:
                        raise ValueError("dia inválido")
                    fatura[campo] = dia
            b["_fatura"] = fatura
        gravar_conta(conexao, conta_id, b)
        if b["type"] == "BANK" and corpo.get("saldo") not in (None, ""):
            b["_saldoData"], b["_ancoras"] = None, []  # saldo digitado agora vale mais que qualquer âncora anterior
            gravar_conta(conexao, conta_id, b)
            ancorar_saldo(conexao, conta_id, numero(corpo["saldo"]), hoje_iso)
            recalcular_saldo(conexao, conta_id)
        instituicao = (corpo.get("instituicao") or "").strip()[:40]
        if instituicao and instituicao != conta["instituicao"]:
            item_id = garantir_item(conexao, instituicao)
            b = ler_conta(conexao, conta_id)["bruto"]
            b["itemId"] = item_id
            conexao.execute("UPDATE contas SET item_id = ?, bruto = ? WHERE id = ?", (item_id, para_json(b), conta_id))
            limpar_itens_vazios(conexao)
    return {"ok": True}
