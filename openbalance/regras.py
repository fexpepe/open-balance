"""Regras de classificação.

Cada transação recebe uma *natureza*, que decide onde ela entra nas contas do painel:

    despesa                gasto de verdade (no cartão, estorno entra como despesa negativa)
    receita                dinheiro que entrou de fora (salário, Pix de terceiros…)
    rendimento             juros, dividendos, JCP
    investimento           aplicação/resgate (só muda o dinheiro de lugar)
    transferencia_propria  entre contas suas
    pagamento_fatura       pagamento do cartão (a despesa já está nas compras do cartão)
    emprestimo             dinheiro emprestado a alguém (saída) ou devolvido (entrada); só por regra/ajuste

Só despesa, receita e rendimento entram nos totais; as demais são movimentações internas.
"""

import re
import unicodedata

DESPESA = "despesa"
RECEITA = "receita"
RENDIMENTO = "rendimento"
INVESTIMENTO = "investimento"
PROPRIA = "transferencia_propria"
FATURA = "pagamento_fatura"
EMPRESTIMO = "emprestimo"
NATUREZAS = (DESPESA, RECEITA, RENDIMENTO, INVESTIMENTO, PROPRIA, FATURA, EMPRESTIMO)

CAT_SALARIO = "01010000"
CAT_FINANCIAMENTO_IMOBILIARIO = "02030001"
CAT_INVESTIMENTOS = "03000000"
CAT_RENDIMENTOS = "03060000"
CAT_MESMA_TITULARIDADE = "04000000"
CAT_PAGAMENTO_CARTAO = "05100000"
CAT_OUTROS = "99999999"

CODIGOS_BANCO = {
    "001": "Banco do Brasil", "033": "Santander", "041": "Banrisul", "070": "BRB", "077": "Inter",
    "102": "XP", "104": "Caixa", "197": "Stone", "208": "BTG Pactual", "212": "Banco Original",
    "237": "Bradesco", "260": "Nubank", "290": "PagBank", "318": "BMG", "323": "Mercado Pago",
    "336": "C6 Bank", "341": "Itaú", "348": "XP", "380": "PicPay", "403": "Cora", "422": "Safra",
    "623": "Banco Pan", "655": "Votorantim", "735": "Neon", "748": "Sicredi", "756": "Sicoob",
}
PALAVRAS_INSTITUICAO = [
    ("NU PAGAMENTOS", "Nubank"), ("NUBANK", "Nubank"), ("ITAU", "Itaú"), ("BRADESCO", "Bradesco"),
    ("SANTANDER", "Santander"), ("CAIXA", "Caixa"), ("BANCO DO BRASIL", "Banco do Brasil"), ("INTER", "Inter"),
    ("C6", "C6 Bank"), ("BTG", "BTG Pactual"), ("XP", "XP"), ("MERCADO PAGO", "Mercado Pago"),
]

# Serviços conhecidos: agrupam descrições diferentes do mesmo serviço (inclusive a linha de IOF).
MARCAS = [(re.compile(p), nome) for p, nome in [
    (r"CLAUDE|ANTHROPIC", "Claude"), (r"OPENAI|CHATGPT", "OpenAI"), (r"NETFLIX", "Netflix"),
    (r"SPOTIFY", "Spotify"), (r"YOUTUBE", "YouTube Premium"), (r"GOOGLE ?ONE", "Google One"),
    (r"\bAWS\b|AMAZON WEB", "AWS"), (r"AMAZON PRIME|PRIMEVIDEO|PRIME VIDEO", "Amazon Prime"),
    (r"WELLHUB|GYMPASS", "Wellhub"), (r"MELIMAIS|MELI\+|MELI MAIS", "Meli+"), (r"DISNEY", "Disney+"),
    (r"HBO ?MAX|\bMAX\.COM", "Max"), (r"APPLE\.COM", "Apple"), (r"MUBI", "Mubi"), (r"SPLICE", "Splice"),
    (r"ARTLIST", "Artlist"), (r"CRUNCHYROLL", "Crunchyroll"), (r"UBER\W*ONE", "Uber One"),
    (r"GLOBOPLAY", "Globoplay"), (r"DEEZER", "Deezer"), (r"PARAMOUNT", "Paramount+"), (r"CANVA", "Canva"),
    (r"ADOBE", "Adobe"), (r"NOTION", "Notion"), (r"GITHUB", "GitHub"), (r"DROPBOX", "Dropbox"),
    (r"MICROSOFT|XBOX", "Microsoft"), (r"PLAYSTATION", "PlayStation"), (r"NINTENDO", "Nintendo"),
    (r"SEM ?PARAR", "Sem Parar"), (r"CONECTCAR", "ConectCar"), (r"VELOE", "Veloe"),
    (r"IFOOD ?CLUB", "iFood Clube"), (r"LINKEDIN", "LinkedIn"), (r"DUOLINGO", "Duolingo"),
]]

RE_PARCELA = re.compile(r"\s*\d{2}/\d{2}\s*$")
RE_PREFIXO_IOF = re.compile(r"^(CANC )?(IOF|COMPRA) INTERNACIONAL - ")
RE_FATURA = re.compile(r"PAGAMENTO DE FATURA|PAGTO FATURA|FATURA CART|DEBITO AUTOMATICO FATURA")
RE_RESGATE = re.compile(r"\bRESGATE\b|\bVENCIMENTO\b|\bRES APLIC\b|DINHEIRO RESGATADO")
RE_RENDIMENTO = re.compile(r"REND PAGO|RENDIMENTO|DIVIDENDO|\bJSCP\b|\bJCP\b|JUROS S/ ?CAP")
RE_INVESTIMENTO = re.compile(r"\bAPLIC|ITAUCOR|\bCOR OPERACOES|COMPRA TD\b|TESOURO|\bCDB\b|\bLCI\b|\bLCA\b|"
                             r"CORRETORA|DINHEIRO GUARDADO|CAIXINHA")
CORRECOES_CATEGORIA = [
    # (padrão na descrição, só para entradas?, categoria correta)
    (re.compile(r"SALARI"), True, CAT_SALARIO),
    (re.compile(r"IMOBILI"), None, CAT_FINANCIAMENTO_IMOBILIARIO),
]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def so_digitos(valor):
    if isinstance(valor, dict):
        valor = valor.get("value")
    return re.sub(r"\D", "", valor or "")


def nome_instituicao(contas):
    for conta in contas:
        numero = (conta.get("bankData") or {}).get("transferNumber") or ""
        codigo = numero.split("/")[0].strip().zfill(3) if "/" in numero else ""
        if codigo in CODIGOS_BANCO:
            return CODIGOS_BANCO[codigo]
    texto = normalizar(" ".join(f"{c.get('marketingName') or ''} {c.get('name') or ''}" for c in contas))
    for chave, nome in PALAVRAS_INSTITUICAO:
        if re.search(rf"\b{chave}\b", texto):
            return nome
    return None


def limpar_descricao(descricao):
    return re.sub(r"\s+", " ", RE_PARCELA.sub("", descricao or "")).strip()


def marca(descricao_normalizada):
    for padrao, nome in MARCAS:
        if padrao.search(descricao_normalizada):
            return nome
    return None


def chave_estabelecimento(descricao, nome_marca=None):
    """Chave estável para agrupar cobranças do mesmo estabelecimento ao longo dos meses."""
    if nome_marca:
        return nome_marca.upper()
    d = RE_PREFIXO_IOF.sub("", RE_PARCELA.sub("", normalizar(descricao)))
    d = re.sub(r"[\d*#.\-_/|]", " ", d)
    return re.sub(r"\s+", " ", d).strip()[:24]


def eh_mesmo_titular(tx, cpf_titular):
    if len(cpf_titular) != 11:
        return False
    pagamento = tx.get("paymentData") or {}
    outro = pagamento.get("receiver") if tx.get("type") == "DEBIT" else pagamento.get("payer")
    return so_digitos((outro or {}).get("documentNumber")) == cpf_titular


PARTICULAS_NOME = {"DE", "DA", "DO", "DAS", "DOS", "E"}
RE_TRANSFERENCIA = re.compile(r"\bPIX\b|\bTED\b|\bDOC\b|TRANSF")


def eh_mesmo_titular_por_nome(tx, nome_titular):
    """Arquivos importados não trazem CPF: 'Pix enviado FULANO DE TAL' com o seu primeiro e último nome conta como seu."""
    partes = [p for p in normalizar(nome_titular).split() if p not in PARTICULAS_NOME]
    if len(partes) < 2 or tx.get("paymentData"):
        return False
    desc = normalizar(tx.get("description"))
    return bool(RE_TRANSFERENCIA.search(desc)) and all(re.search(rf"\b{re.escape(p)}\b", desc) for p in (partes[0], partes[-1]))


def classificar(tx, conta, cpf_titular="", nome_titular=""):
    """Devolve (natureza, categoria_id) aplicando as regras automáticas."""
    desc = normalizar(tx.get("description"))
    cat = tx.get("categoryId") or CAT_OUTROS
    entrada = tx.get("type") == "CREDIT"

    for padrao, so_entrada, nova in CORRECOES_CATEGORIA:
        if padrao.search(desc) and (so_entrada is None or so_entrada == entrada):
            cat = nova
            break

    if conta.get("type") == "CREDIT":
        if entrada and (desc.startswith("PAGAMENTO") or cat == CAT_PAGAMENTO_CARTAO):
            return FATURA, CAT_PAGAMENTO_CARTAO
        return DESPESA, cat

    if cat == CAT_PAGAMENTO_CARTAO or RE_FATURA.search(desc):
        return FATURA, CAT_PAGAMENTO_CARTAO
    if cat.startswith("04") or eh_mesmo_titular(tx, cpf_titular) or eh_mesmo_titular_por_nome(tx, nome_titular):
        return PROPRIA, cat if cat.startswith("04") else CAT_MESMA_TITULARIDADE
    if RE_RESGATE.search(desc):
        return INVESTIMENTO, cat if cat.startswith("03") else CAT_INVESTIMENTOS
    if entrada and RE_RENDIMENTO.search(desc):
        return RENDIMENTO, CAT_RENDIMENTOS
    if cat.startswith("03"):
        if cat == CAT_RENDIMENTOS:
            return (RENDIMENTO, cat) if entrada else (INVESTIMENTO, CAT_INVESTIMENTOS)
        return INVESTIMENTO, cat
    if RE_INVESTIMENTO.search(desc):
        return INVESTIMENTO, CAT_INVESTIMENTOS
    return (RECEITA if entrada else DESPESA), cat


RE_PREFIXO_TRANSFERENCIA = re.compile(
    r"^(PIX (ENVIADO|RECEBIDO)|PAGAMENTO DE PIX QR CODE|TRANSFERENCIA (ENVIADA|RECEBIDA)( PELO PIX)?|"
    r"TED (ENVIADA|RECEBIDA)|DOC (ENVIADO|RECEBIDO))\s*\|?\s*")


def nome_contraparte(descricao):
    """'Pix enviado FULANO DE TAL' -> 'Fulano De Tal'."""
    return RE_PREFIXO_TRANSFERENCIA.sub("", normalizar(descricao)).strip().title()


def regra_casa(padrao, descricao):
    """Regras criadas por você: casam por trecho da descrição, sem diferenciar maiúsculas/acentos."""
    return normalizar(padrao).strip() in normalizar(descricao)
