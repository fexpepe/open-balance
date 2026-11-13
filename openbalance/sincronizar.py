"""Puxa os dados da Pluggy e grava no SQLite local."""

import json
import threading
from datetime import date, datetime, timedelta

from . import carteira, regras
from .analise import itens_visiveis
from .banco import para_json
from .config import credenciais
from .pluggy import ErroApi, Pluggy

# Janela relida a cada sincronização. O Open Finance entrega até 12 meses;
# o que for mais antigo que isso continua salvo no banco.
DIAS_JANELA = 365

_trava = threading.Lock()


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sincronizar(conexao, dias=DIAS_JANELA, log=print):
    """Sincroniza todos os itens do .env. Devolve um resumo (dict)."""
    if not _trava.acquire(blocking=False):
        raise RuntimeError("Já existe uma sincronização em andamento.")
    try:
        return _sincronizar(conexao, dias, log)
    finally:
        _trava.release()


def _sincronizar(conexao, dias, log):
    inicio = agora()
    hoje = date.today().isoformat()
    inicio_janela = (date.today() - timedelta(days=dias)).isoformat()
    resumo = {"itens": [], "erros": []}

    client_id, client_secret, item_ids = credenciais()
    log("Autenticando na Pluggy…")
    api = Pluggy(client_id, client_secret)

    try:
        categorias = api.get("/categories").get("results", [])
        with conexao:
            conexao.executemany(
                "INSERT OR REPLACE INTO categorias (id, descricao, descricao_pt, pai_id, propria) VALUES (?, ?, ?, ?, 0)",
                [(c["id"], c.get("description"), c.get("descriptionTranslated"), c.get("parentId")) for c in categorias])
    except ErroApi as e:
        resumo["erros"].append(f"categorias: {e}")

    for item_id in item_ids:
        try:
            resumo["itens"].append(_sincronizar_item(conexao, api, item_id, inicio_janela, hoje, resumo, log))
        except ErroApi as e:
            log(f"Item {item_id[:8]}: {e}")
            resumo["erros"].append(f"item {item_id[:8]}: {e}")

    resumo["consolidados"] = consolidar_itens_antigos(conexao, item_ids)
    for nome in resumo["consolidados"]:
        log(f"{nome}: conexão antiga substituída pela nova (duplicados removidos)")

    # CDI e IPCA para comparar a carteira (fontes públicas; se falharem, a carteira só fica sem a comparação).
    resumo["indices"] = carteira.atualizar_indices(conexao)
    # Preço de mercado do dia dos títulos do Tesouro (o valor que vem do banco é o da curva).
    resumo["indices"]["tesouro"] = carteira.atualizar_precos_tesouro(conexao)
    sem_indice = [s.upper() for s, fonte in resumo["indices"].items() if fonte is None]
    if sem_indice:
        log(f"Índices indisponíveis agora: {', '.join(sem_indice)}")
    # Na B3: quais tickers são FIIs e os proventos já anunciados (o "a receber" da carteira).
    resumo["b3"] = carteira.atualizar_proventos_b3(conexao, itens_visiveis(conexao))
    if resumo["b3"]["erros"]:
        log(f"B3 indisponível para {len(resumo['b3']['erros'])} ativo(s); ficam os proventos já guardados")

    with conexao:
        conexao.execute("INSERT INTO sincronizacoes (inicio, fim, ok, resumo) VALUES (?, ?, ?, ?)",
                        (inicio, agora(), int(not resumo["erros"]), para_json(resumo)))
    return resumo


def chave_conta(linha):
    """Mesma conta física = mesmo tipo + mesmo número, independentemente do Item ID."""
    return linha["tipo"], regras.so_digitos(json.loads(linha["bruto"]).get("number"))


def consolidar_itens_antigos(conexao, item_ids):
    """Item que saiu do .env (ex.: banco reconectado ganhou um Item ID novo).

    Cada conta antiga que corresponde a uma conta atual é fundida nela: o histórico mais antigo
    que o da conta nova é preservado, os ajustes manuais são remapeados e o resto (duplicado) é apagado.
    Contas sem correspondente ficam guardadas (só não aparecem no painel).
    """
    marcadores = ",".join("?" * len(item_ids))
    atuais = {chave_conta(r): r["id"] for r in conexao.execute(
        f"SELECT id, tipo, bruto FROM contas WHERE item_id IN ({marcadores})", item_ids)}
    # Arquivos importados não são conexões da Pluggy: nunca entram na consolidação.
    antigos = conexao.execute(f"SELECT id, instituicao FROM itens WHERE id NOT IN ({marcadores}) AND origem = 'pluggy'",
                              item_ids).fetchall()
    consolidados = []
    with conexao:
        for item in antigos:
            restantes = 0
            for conta in conexao.execute("SELECT id, tipo, bruto FROM contas WHERE item_id = ?", (item["id"],)).fetchall():
                nova = atuais.get(chave_conta(conta))
                if nova:
                    fundir_conta(conexao, conta["id"], nova)
                else:
                    restantes += 1
            if not restantes:
                conexao.execute("DELETE FROM investimentos WHERE item_id = ?", (item["id"],))
                conexao.execute("DELETE FROM itens WHERE id = ?", (item["id"],))
                consolidados.append(item["instituicao"])
    return consolidados


def fundir_conta(conexao, antiga, nova):
    inicio = conexao.execute("SELECT min(data) FROM transacoes WHERE conta_id = ?", (nova,)).fetchone()[0] or "9999"

    # Ajustes manuais de transações que serão apagadas passam para a equivalente na conta nova.
    for aj in conexao.execute("SELECT a.transacao_id, t.data, t.bruto FROM ajustes a JOIN transacoes t "
                              "ON t.id = a.transacao_id WHERE t.conta_id = ? AND t.data >= ?", (antiga, inicio)).fetchall():
        velha = json.loads(aj["bruto"])
        for candidata in conexao.execute("SELECT id, bruto FROM transacoes WHERE conta_id = ? AND data = ?", (nova, aj["data"])):
            c = json.loads(candidata["bruto"])
            if c.get("amount") == velha.get("amount") and c.get("description") == velha.get("description"):
                conexao.execute("UPDATE OR IGNORE ajustes SET transacao_id = ? WHERE transacao_id = ?",
                                (candidata["id"], aj["transacao_id"]))
                break

    conexao.execute("UPDATE transacoes SET conta_id = ? WHERE conta_id = ? AND data < ?", (nova, antiga, inicio))
    conexao.execute("DELETE FROM transacoes WHERE conta_id = ?", (antiga,))
    vencimento = conexao.execute("SELECT min(vencimento) FROM faturas WHERE conta_id = ?", (nova,)).fetchone()[0] or "9999"
    conexao.execute("UPDATE faturas SET conta_id = ? WHERE conta_id = ? AND vencimento < ?", (nova, antiga, vencimento))
    conexao.execute("DELETE FROM faturas WHERE conta_id = ?", (antiga,))
    conexao.execute("UPDATE OR IGNORE historico_saldos SET ref_id = ? WHERE ref_id = ?", (nova, antiga))
    conexao.execute("DELETE FROM historico_saldos WHERE ref_id = ?", (antiga,))
    conexao.execute("DELETE FROM contas WHERE id = ?", (antiga,))


def _sincronizar_item(conexao, api, item_id, inicio_janela, hoje, resumo, log):
    item = api.get(f"/items/{item_id}")
    contas = api.get("/accounts", {"itemId": item_id}).get("results", [])
    instituicao = regras.nome_instituicao(contas) or f"Instituição {item_id[:4]}"
    log(f"{instituicao}: {len(contas)} conta(s)")
    info = {"item": item_id, "instituicao": instituicao, "contas": len(contas), "transacoes": 0, "faturas": 0,
            "investimentos": 0}

    # Busca tudo antes de escrever, para gravar o item numa transação só.
    por_conta = []
    for conta in contas:
        txs = api.transacoes(conta["id"], inicio_janela)
        faturas = api.get_paginado("/bills", {"accountId": conta["id"]}) if conta.get("type") == "CREDIT" else []
        por_conta.append((conta, txs, faturas))
        info["transacoes"] += len(txs)
        info["faturas"] += len(faturas)

    investimentos = None
    try:
        investimentos = api.get_paginado("/investments", {"itemId": item_id})
        info["investimentos"] = len(investimentos)
    except ErroApi as e:
        resumo["erros"].append(f"{instituicao} — investimentos: {e}")

    with conexao:
        conexao.execute(
            "INSERT OR REPLACE INTO itens (id, instituicao, status, atualizado_em, consentimento_expira, bruto) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, instituicao, item.get("status"), item.get("lastUpdatedAt"), item.get("consentExpiresAt"),
             para_json(item)))
        for conta, txs, faturas in por_conta:
            conexao.execute("INSERT OR REPLACE INTO contas (id, item_id, tipo, saldo, bruto) VALUES (?, ?, ?, ?, ?)",
                            (conta["id"], item_id, conta.get("type"), conta.get("balance"), para_json(conta)))
            conexao.execute("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) VALUES (?, ?, ?, ?)",
                            (hoje, conta["id"], conta.get("type"), conta.get("balance")))
            conexao.executemany("INSERT OR REPLACE INTO transacoes (id, conta_id, data, bruto) VALUES (?, ?, ?, ?)",
                                [(t["id"], conta["id"], t["date"][:10], para_json(t)) for t in txs])
            # Dentro da janela relida, some o que a Pluggy não devolveu mais
            # (ex.: lançamento pendente que virou outro ao ser confirmado).
            ids = json.dumps([t["id"] for t in txs])
            conexao.execute("DELETE FROM transacoes WHERE conta_id = ? AND data >= ? "
                            "AND id NOT IN (SELECT value FROM json_each(?))", (conta["id"], inicio_janela, ids))
            conexao.executemany("INSERT OR REPLACE INTO faturas (id, conta_id, vencimento, total, bruto) "
                                "VALUES (?, ?, ?, ?, ?)",
                                [(f["id"], conta["id"], (f.get("dueDate") or "")[:10], f.get("totalAmount"),
                                  para_json(f)) for f in faturas])
        if investimentos is not None:
            ids = json.dumps([i["id"] for i in investimentos])
            conexao.execute("DELETE FROM investimentos WHERE item_id = ? AND id NOT IN (SELECT value FROM json_each(?))",
                            (item_id, ids))
            conexao.executemany("INSERT OR REPLACE INTO investimentos (id, item_id, saldo, bruto) VALUES (?, ?, ?, ?)",
                                [(i["id"], item_id, i.get("balance"), para_json(i)) for i in investimentos])
            conexao.executemany("INSERT OR REPLACE INTO historico_saldos (data, ref_id, tipo, saldo) "
                                "VALUES (?, ?, 'INVESTIMENTO', ?)",
                                [(hoje, i["id"], i.get("balance")) for i in investimentos])
    if investimentos:
        # Compras, vendas e proventos de cada posição: custo médio, lucro e renda mensal na carteira.
        info["movimentosInvestimento"] = carteira.sincronizar_movimentos(conexao, api, item_id, investimentos)
    return info
