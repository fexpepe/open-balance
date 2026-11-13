"""
Validação dos dados da Pluggy (via MeuPluggy) — Open Balance.

Para cada Item ID configurado, puxa: status da conexão, contas, transações,
faturas de cartão, investimentos e empréstimos. Mostra um resumo no terminal
e salva o JSON bruto em ./dados_brutos/<data-hora>/ para inspeção.

Uso:
    1. Copie .env.example para .env e preencha.
    2. python validar_pluggy.py              (últimos 365 dias de transações)
       python validar_pluggy.py --dias 90
       python validar_pluggy.py --sem-salvar (não grava o JSON bruto)

Somente leitura: além do POST /auth (que gera a API key), o script só faz GET.
Usa apenas a biblioteca padrão do Python.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from openbalance.config import carregar_env
from openbalance.pluggy import ErroApi, Pluggy

PASTA = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------------

def brl(valor):
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def dia(iso):
    return (iso or "")[:10] or "—"


def final_numero(numero):
    return f"…{numero[-4:]}" if numero else ""


def titulo(texto):
    print("\n" + "=" * 78)
    print(f" {texto}")
    print("=" * 78)


# ----------------------------------------------------------------------------
# Validação
# ----------------------------------------------------------------------------

def resumir_transacoes(txs, cartao):
    """Imprime o resumo das transações e devolve uma lista de problemas encontrados."""
    if not txs:
        print("    Transações: nenhuma no período")
        return ["nenhuma transação no período"]

    datas = sorted(t["date"][:10] for t in txs)
    saidas = sum(abs(t.get("amount") or 0) for t in txs if t.get("type") == "DEBIT")
    entradas = sum(abs(t.get("amount") or 0) for t in txs if t.get("type") == "CREDIT")
    com_categoria = sum(1 for t in txs if t.get("category"))
    pendentes = sum(1 for t in txs if t.get("status") == "PENDING")

    print(f"    Transações: {len(txs)} de {datas[0]} a {datas[-1]}")
    print(f"      saídas {brl(saidas)} · entradas {brl(entradas)} · pendentes {pendentes}")
    print(f"      com categoria: {com_categoria * 100 // len(txs)}%")

    problemas = []
    if cartao:
        meta = [t.get("creditCardMetadata") or {} for t in txs]
        parceladas = sum(1 for m in meta if (m.get("totalInstallments") or 0) > 1)
        com_fatura = sum(1 for m in meta if m.get("billId"))
        print(f"      parceladas: {parceladas} · ligadas a uma fatura (billId): {com_fatura * 100 // len(txs)}%")
        if com_fatura == 0:
            problemas.append("cartão sem vínculo transação→fatura (billId)")

    print("      mais recentes:")
    for t in sorted(txs, key=lambda t: t["date"], reverse=True)[:5]:
        categoria = t.get("category") or "sem categoria"
        print(f"        {t['date'][:10]} {brl(t.get('amount')):>15}  {t.get('description', '')[:38]:<38} [{categoria}]")
    return problemas


def validar_conta(api, conta, data_inicio, bruto):
    problemas = []
    cartao = conta.get("type") == "CREDIT"
    nome = conta.get("marketingName") or conta.get("name") or "?"
    print(f"\n  ▸ {nome} {final_numero(conta.get('number'))} [{conta.get('subtype')}]  saldo {brl(conta.get('balance'))}")

    if cartao:
        cd = conta.get("creditData") or {}
        print(f"    Limite {brl(cd.get('creditLimit'))} · disponível {brl(cd.get('availableCreditLimit'))}"
              f" · fecha {dia(cd.get('balanceCloseDate'))} · vence {dia(cd.get('balanceDueDate'))}")

    try:
        txs = api.transacoes(conta["id"], data_inicio)
        bruto["transacoes"] = txs
        problemas += resumir_transacoes(txs, cartao)
    except ErroApi as e:
        print(f"    Transações: erro — {e}")
        problemas.append(f"transações: {e}")

    if cartao:
        try:
            faturas = api.get_paginado("/bills", {"accountId": conta["id"]})
            bruto["faturas"] = faturas
            print(f"    Faturas: {len(faturas)}")
            for f in sorted(faturas, key=lambda f: f.get("dueDate") or "", reverse=True)[:3]:
                print(f"      vence {dia(f.get('dueDate'))}  {brl(f.get('totalAmount')):>15}"
                      f"  fecha {dia(f.get('billClosingDate'))}")
            if not faturas:
                problemas.append("nenhuma fatura retornada")
        except ErroApi as e:
            print(f"    Faturas: erro — {e}")
            problemas.append(f"faturas: {e}")

    return [f"{nome}: {p}" for p in problemas], len(bruto.get("transacoes", [])), len(bruto.get("faturas", []))


def validar_investimentos(api, item_id, bruto):
    try:
        invs = api.get_paginado("/investments", {"itemId": item_id})
    except ErroApi as e:
        print(f"\n  Investimentos: erro — {e}")
        return [f"investimentos: {e}"], 0
    bruto["investimentos"] = invs
    ativos = [i for i in invs if i.get("status") != "TOTAL_WITHDRAWAL"]
    if not invs:
        print("\n  Investimentos: nenhum")
        return [], 0

    por_tipo = defaultdict(float)
    for i in ativos:
        por_tipo[i.get("type") or "?"] += i.get("balance") or 0
    print(f"\n  Investimentos: {len(ativos)} ativos (de {len(invs)}) · total {brl(sum(por_tipo.values()))}")
    for tipo, total in sorted(por_tipo.items(), key=lambda x: -x[1]):
        print(f"    {tipo:<14} {brl(total):>18}")
    print("    maiores posições:")
    for i in sorted(ativos, key=lambda i: -(i.get("balance") or 0))[:8]:
        taxa = i.get("lastTwelveMonthsRate")
        rent = f" · 12m {taxa:.2f}%" if taxa is not None else ""
        print(f"      {(i.get('name') or '?')[:40]:<40} {i.get('subtype') or i.get('type') or '':<16}"
              f" {brl(i.get('balance')):>15}{rent}")

    problemas = []
    sem_saldo = sum(1 for i in ativos if not i.get("balance"))
    if sem_saldo:
        problemas.append(f"investimentos: {sem_saldo} posições ativas sem saldo")
    return problemas, len(ativos)


def validar_emprestimos(api, item_id, bruto):
    try:
        emprestimos = api.get("/loans", {"itemId": item_id}).get("results", [])
    except ErroApi as e:
        # Muitos bancos não liberam esse produto; não é bloqueante.
        print(f"\n  Empréstimos: indisponível — {e}")
        return
    bruto["emprestimos"] = emprestimos
    if emprestimos:
        print(f"\n  Empréstimos/financiamentos: {len(emprestimos)}")
        for emp in emprestimos:
            print(f"    {(emp.get('productName') or '?')[:40]:<40} contratado {brl(emp.get('contractAmount'))}")


def validar_item(api, item_id, data_inicio):
    bruto = {"itemId": item_id}
    resumo = {"id": item_id, "nome": "?", "contas": 0, "transacoes": 0, "faturas": 0, "investimentos": 0, "problemas": []}

    try:
        item = api.get(f"/items/{item_id}")
    except ErroApi as e:
        dica = " (confira se o Item ID está certo)" if e.status in (400, 404) else ""
        titulo(f"Item {item_id}")
        print(f"  ERRO ao buscar o item: {e}{dica}")
        resumo["problemas"].append(f"item inacessível: {e}")
        return resumo, bruto

    bruto["item"] = item
    conector = item.get("connector") or {}
    resumo["nome"] = conector.get("name") or resumo["nome"]
    titulo(f"{resumo['nome']}  ({item_id})")
    # O conector 200 (MeuPluggy) é um proxy da conexão Open Finance feita no meu.pluggy.ai.
    origem = "via MeuPluggy" if conector.get("id") == 200 else ("sim" if conector.get("isOpenFinance") else "não")
    print(f"  Status: {item.get('status')} · execução: {item.get('executionStatus')} · Open Finance: {origem}")
    print(f"  Última atualização: {dia(item.get('lastUpdatedAt'))}"
          f" · próxima sync: {dia(item.get('nextAutoSyncAt'))}"
          f" · consentimento expira: {dia(item.get('consentExpiresAt'))}")

    if item.get("status") != "UPDATED":
        resumo["problemas"].append(f"status do item é {item.get('status')}")
    for produto, info in (item.get("statusDetail") or {}).items():
        for aviso in (info or {}).get("warnings") or []:
            msg = aviso.get("message") or aviso.get("providerMessage") or aviso.get("code") or str(aviso)
            print(f"  ⚠ {produto}: {msg}")
            resumo["problemas"].append(f"aviso em {produto}: {msg}")

    try:
        contas = api.get("/accounts", {"itemId": item_id}).get("results", [])
    except ErroApi as e:
        print(f"  Contas: erro — {e}")
        resumo["problemas"].append(f"contas: {e}")
        contas = []

    bruto["contas"] = []
    resumo["contas"] = len(contas)
    if not contas:
        print("  Contas: nenhuma")
    for conta in contas:
        bruto_conta = {"conta": conta}
        bruto["contas"].append(bruto_conta)
        problemas, n_tx, n_fat = validar_conta(api, conta, data_inicio, bruto_conta)
        resumo["problemas"] += problemas
        resumo["transacoes"] += n_tx
        resumo["faturas"] += n_fat

    problemas, n_inv = validar_investimentos(api, item_id, bruto)
    resumo["problemas"] += problemas
    resumo["investimentos"] = n_inv

    validar_emprestimos(api, item_id, bruto)
    return resumo, bruto


def salvar_bruto(pasta_saida, resumo, bruto):
    pasta_saida.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^A-Za-z0-9_-]+", "_", resumo["nome"]).strip("_") or "item"
    arquivo = pasta_saida / f"{nome}_{bruto['itemId'][:8]}.json"
    arquivo.write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Valida os dados da Pluggy (somente leitura).")
    parser.add_argument("--dias", type=int, default=365, help="dias de histórico de transações (padrão: 365)")
    parser.add_argument("--sem-salvar", action="store_true", help="não grava o JSON bruto em disco")
    args = parser.parse_args()

    carregar_env(PASTA / ".env")
    client_id = os.environ.get("PLUGGY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("PLUGGY_CLIENT_SECRET", "").strip()
    item_ids = [i.strip() for i in os.environ.get("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]

    faltando = [nome for nome, valor in (("PLUGGY_CLIENT_ID", client_id),
                                         ("PLUGGY_CLIENT_SECRET", client_secret),
                                         ("PLUGGY_ITEM_IDS", item_ids)) if not valor]
    if faltando:
        sys.exit(f"Faltam variáveis: {', '.join(faltando)}.\n"
                 f"Copie .env.example para {PASTA / '.env'} e preencha.")

    if any(p in str(PASTA).lower() for p in ("meu drive", "my drive", "google drive", "onedrive", "dropbox")):
        print("⚠ Esta pasta parece sincronizada com a nuvem. O .env e os dados brutos vão junto.\n")

    data_inicio = (date.today() - timedelta(days=args.dias)).isoformat()
    print(f"Autenticando na Pluggy… (transações desde {data_inicio}, {len(item_ids)} item(s))")
    try:
        api = Pluggy(client_id, client_secret)
    except ErroApi as e:
        sys.exit(f"Falha ao autenticar: {e}\nConfira PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no .env.")

    pasta_saida = PASTA / "dados_brutos" / datetime.now().strftime("%Y%m%d-%H%M%S")
    resumos = []
    for item_id in item_ids:
        resumo, bruto = validar_item(api, item_id, data_inicio)
        resumos.append(resumo)
        if not args.sem_salvar:
            salvar_bruto(pasta_saida, resumo, bruto)

    titulo("RESUMO")
    print(f"  {'Instituição (item)':<28} {'Contas':>6} {'Transações':>11} {'Faturas':>8} {'Invest.':>8}")
    for r in resumos:
        rotulo = f"{r['nome'][:19]} {r['id'][:8]}"
        print(f"  {rotulo:<28} {r['contas']:>6} {r['transacoes']:>11} {r['faturas']:>8} {r['investimentos']:>8}")

    problemas = [(f"{r['nome']} {r['id'][:8]}", p) for r in resumos for p in r["problemas"]]
    if problemas:
        print("\n  Pontos de atenção:")
        for nome, p in problemas:
            print(f"    • {nome}: {p}")
    else:
        print("\n  Nenhum problema encontrado.")

    if not args.sem_salvar:
        print(f"\n  JSON bruto salvo em: {pasta_saida}")
        print("  (contém seus dados financeiros — não compartilhe nem suba para o git)")


if __name__ == "__main__":
    main()
