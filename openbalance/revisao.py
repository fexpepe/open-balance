"""Revisão das despesas em categorias genéricas ("Serviços", "Transferência - PIX", "Boleto", "Outros"…).

Agrupa os lançamentos por recebedor (descrição sem prefixo de Pix/boleto, números e sufixos) e propõe,
para cada grupo, um trecho de descrição que vira regra comum (tabela `regras`, a mesma do ⋮ das transações).
Assim a decisão vale para o histórico todo e para o que chegar depois, da Pluggy ou de arquivo importado.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import date

from . import analise, categorizar, regras
from .banco import bruto, gravar_preferencia, preferencia

# Categorias que não dizem no que o dinheiro foi gasto (só o meio de pagamento, ou nada).
GENERICAS = {
    "07000000",  # Serviços
    "05000000", "05010000", "05030000", "05040000", "05060000", "05070000", "05080000",  # Transferências, boleto…
    "05090000", "05090001", "05090002", "05090003", "05090004", "05090005",  # Transferências para terceiros
    regras.CAT_OUTROS,
}
PREF_IGNORADOS = "revisao_ignorados"

# Prefixos de extrato que só dizem o meio de pagamento. Removidos repetidamente:
# "Pagamento de boleto PAG BOLETO FULANO" -> "FULANO".
RE_PREFIXO = re.compile(
    r"^(PIX (ENVIADO|RECEBIDO|TRANSF|QR ?CODE)|PAGAMENTO DE PIX( QR CODE)?|PAGAMENTO PIX|"
    r"TRANSFERENCIA (ENVIADA|RECEBIDA)( PELO PIX)?|TRANSF(ERENCIA)? PIX|PIX|TED (ENVIADA|RECEBIDA)|TED|"
    r"DOC (ENVIADO|RECEBIDO)|DOC|PAGAMENTO DE BOLETO|PAG(TO|AMENTO)? (DE )?BOLETO|BOLETO|PAGAMENTO EFETUADO|"
    r"PAGAMENTO DE TITULO|PAG(TO)? TIT(ULO)?|DEBITO AUTOMATICO|DEB AUT|SISPAG)\b[\s|:\-/]*")
RE_SUFIXO_EMPRESA = re.compile(r"\b(LTDA|LTD|LT|S ?A|ME|EPP|EIRELI|MEI)$")
TAMANHO_CHAVE = 20


def contraparte(descricao_normalizada):
    """'PAGAMENTO DE BOLETO PAG BOLETO FULANO LTDA' -> 'FULANO LTDA' (mantém espaçamento e números)."""
    d = regras.RE_PARCELA.sub("", descricao_normalizada).strip()
    while True:
        novo = RE_PREFIXO.sub("", d, count=1).strip()
        if novo == d:
            return d
        d = novo


def chave_grupo(texto_contraparte):
    """Chave estável: sem números, pontuação e sufixo de empresa; cortada para juntar nomes truncados pelo banco."""
    d = re.sub(r"[^A-Z ]", " ", texto_contraparte)
    d = re.sub(r"\s+", " ", d).strip()
    d = RE_SUFIXO_EMPRESA.sub("", d).strip()
    return d[:TAMANHO_CHAVE].strip()


def prefixo_comum(textos):
    if not textos:
        return ""
    menor, maior = min(textos), max(textos)
    i = 0
    while i < len(menor) and menor[i] == maior[i]:
        i += 1
    return menor[:i]


def padrao_do_grupo(contrapartes):
    """Trecho que aparece em todas as descrições do grupo (o começo comum do nome do recebedor)."""
    p = prefixo_comum(contrapartes)
    p = re.sub(r"[\d\s*#.\-_/|]+$", "", p)  # sem número ou separador pendurado no fim
    if len(p) < 4:  # nomes muito diferentes dentro do grupo: fica com o mais frequente
        p = re.sub(r"[\d\s*#.\-_/|]+$", "", Counter(contrapartes).most_common(1)[0][0])
    return p


def juntar_truncados(grupos):
    """'LIGASEGURA' e 'LIGASEGURA COBRANCAS' são o mesmo recebedor (um banco corta o nome, outro não)."""
    for curta in sorted(grupos, key=len):
        if len(curta) < 6 or curta not in grupos:
            continue
        longas = [k for k in grupos if k != curta and k.startswith(curta + " ")]
        if len(longas) == 1:  # só junta quando não há ambiguidade
            grupos[longas[0]].extend(grupos.pop(curta))


def carregar(conexao, hoje):
    """Transações classificadas como no painel (regras e ajustes já aplicados), com a descrição original."""
    hoje_iso = hoje.isoformat()
    itens = analise.itens_visiveis(conexao)
    contas = {r["id"]: (r["item_id"], bruto(r)) for r in conexao.execute("SELECT id, item_id, bruto FROM contas")
              if r["item_id"] in itens}
    cpf_por_item = {}
    for item_id, conta in contas.values():
        cpf = regras.so_digitos(conta.get("taxNumber"))
        if len(cpf) == 11:
            cpf_por_item[item_id] = cpf
    nome_titular = preferencia(conexao, "titular", "")
    ajustes = {r["transacao_id"]: dict(r) for r in conexao.execute("SELECT * FROM ajustes")}
    regras_usuario = [dict(r) for r in conexao.execute("SELECT * FROM regras ORDER BY id")]
    lista = []
    for linha in conexao.execute("SELECT conta_id, bruto FROM transacoes"):
        if linha["conta_id"] not in contas:
            continue
        item_id, conta = contas[linha["conta_id"]]
        t = bruto(linha)
        tx = analise.enriquecer(t, conta, cpf_por_item.get(item_id, ""), regras_usuario, ajustes, hoje_iso, nome_titular)
        tx["bruta"] = t.get("description") or ""
        tx["cartao"] = conta.get("type") == "CREDIT"
        lista.append(tx)
    return lista


def ignorados(conexao):
    try:
        return set(json.loads(preferencia(conexao, PREF_IGNORADOS, "[]") or "[]"))
    except ValueError:
        return set()


def montar(conexao, hoje=None):
    hoje = hoje or date.today()
    hoje_iso = hoje.isoformat()
    inicio = f"{hoje.year - 1}-{hoje.month:02d}-01"  # últimos 12 meses e o corrente
    transacoes = carregar(conexao, hoje)
    pulados = ignorados(conexao)

    grupos = defaultdict(list)
    for t in transacoes:
        if (t["categoriaId"] not in GENERICAS or t["natureza"] != regras.DESPESA or t["entrada"] or t["oculto"]
                or t["ajustada"] or t["regraId"] or not inicio <= t["data"] <= hoje_iso):
            continue
        cp = contraparte(regras.normalizar(t["bruta"]))
        chave = chave_grupo(cp)
        grupos[chave or "—"].append((t, cp))
    juntar_truncados(grupos)

    aprendido = {k: v for k, v in categorizar.aprender(conexao).items() if v not in GENERICAS}
    descricoes_todas = [regras.normalizar(t["bruta"]) for t in transacoes]
    resultado = []
    for chave, membros in grupos.items():
        sem_nome = len(chave) < 3
        contrapartes = [cp for _, cp in membros]
        padrao = "" if sem_nome else padrao_do_grupo(contrapartes)
        if len(padrao) < 3:
            sem_nome = True
        normalizado = regras.normalizar(padrao)
        cobertos = sum(1 for t, _ in membros if normalizado and normalizado in regras.normalizar(t["bruta"]))
        alcance = sum(1 for d in descricoes_todas if normalizado and normalizado in d)
        txs = sorted((t for t, _ in membros), key=lambda t: t["data"], reverse=True)
        nome = Counter(regras.limpar_descricao(cp) for cp in contrapartes).most_common(1)[0][0].title()
        resultado.append({
            "chave": chave,
            "nome": nome if not sem_nome else (txs[0]["descricao"] or "Sem descrição"),
            "padrao": padrao.title() if not sem_nome else "",
            "semNome": sem_nome,
            "total": round(sum(t["valor"] for t in txs), 2),
            "quantidade": len(txs),
            "cobertos": cobertos,
            "alcance": alcance,
            "ultima": txs[0]["data"],
            "categorias": dict(Counter(t["categoriaId"] for t in txs)),
            "sugestao": None if sem_nome else sugerir(txs, contrapartes, aprendido),
            "ignorado": chave in pulados,
            "exemplos": [{"id": t["id"], "data": t["data"], "descricao": t["descricao"], "valor": t["valor"],
                          "contaId": t["contaId"]} for t in txs[:6]],
        })
    resultado.sort(key=lambda g: -g["total"])
    return {"genericas": sorted(GENERICAS), "inicio": inicio, "grupos": resultado}


def sugerir(txs, contrapartes, aprendido):
    """Categoria provável: a que o seu histórico já usa para esse recebedor, senão uma palavra-chave do nome."""
    votos = Counter()
    for t in txs:
        cat = aprendido.get((categorizar.chave_aprendizado(t["bruta"]), False))
        if cat:
            votos[(cat, "historico")] += 1
    if votos:
        (cat, origem), _ = votos.most_common(1)[0]
        return {"categoriaId": cat, "origem": origem}
    for cp in Counter(contrapartes):
        for padrao, cat in categorizar.PALAVRAS:
            if cat not in GENERICAS and padrao.search(cp):
                return {"categoriaId": cat, "origem": "palavra"}
    return None


def ignorar(conexao, corpo):
    """Tira (ou devolve, com 'desfazer') um grupo da lista. Não muda nenhum lançamento."""
    chave = str(corpo.get("chave") or "").strip()[:60]
    if not chave:
        raise ValueError("grupo inválido")
    atuais = ignorados(conexao)
    if corpo.get("desfazer"):
        atuais.discard(chave)
    else:
        atuais.add(chave)
    gravar_preferencia(conexao, PREF_IGNORADOS, json.dumps(sorted(atuais), ensure_ascii=False))
    return {"ok": True}
