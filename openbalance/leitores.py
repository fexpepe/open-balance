"""Leitura dos arquivos que os bancos exportam: OFX, CSV/TXT, XLSX e o "XLS" que na verdade é HTML.

Só biblioteca padrão. Cada leitor devolve uma lista de *extratos* neutros (um OFX pode trazer conta e
cartão juntos):

    {"formato", "tipo" (conta | cartao | investimentos | None), "instituicao", "banco", "agencia",
     "numero", "saldo", "saldoData", "lancamentos": [...], "posicoes": [...], "avisos": [...],
     "assinatura", "cabecalho", "amostra", "colunas", "precisaMapeamento"}

Cada lançamento: {"idOrigem", "data", "descricao", "valor", "parcela", "trechoParcela", "parcelaSufixo"}.
`valor` vem com o sinal do arquivo (em extrato de conta, negativo = saída). Quem decide o que é compra
ou pagamento no cartão é importar.py, que sabe o tipo da conta de destino.
"""

import csv
import hashlib
import html
import html.parser
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path

from . import regras


class ErroLeitura(ValueError):
    pass


# ============================================================ texto, números e datas
def decodificar(conteudo):
    if conteudo[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return conteudo.decode("utf-16")
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            pass
    return conteudo.decode("latin-1")


def norm(texto):
    """Minúsculas, sem acento e com espaços simples — para comparar nomes de coluna."""
    return re.sub(r"\s+", " ", regras.normalizar(str(texto or "")).lower()).strip()


def adivinhar_decimal(textos):
    """',' ou '.' — decide pelo arquivo inteiro, não por valor isolado."""
    virgula = ponto = 0.0
    for t in textos:
        if isinstance(t, (int, float)):
            continue
        t = re.sub(r"[^\d.,]", "", str(t))
        if re.search(r",\d{1,2}$", t):
            virgula += 1
        elif re.search(r"\.\d{1,2}$", t):
            ponto += 1
        elif re.search(r"\.\d{3}$", t) and "," not in t:
            virgula += 0.1  # "1.234" sem centavos = milhar no padrão brasileiro
    return "," if virgula > 0 and virgula >= ponto else "."


def ler_valor(texto, decimal=None):
    """'R$ -1.234,56' → -1234.56 · '1.234,56 D' → -1234.56 · '(50,00)' → -50.0. Devolve None se não for número."""
    if isinstance(texto, bool):
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    t = regras.normalizar(str(texto or "")).replace("R$", "").replace("BRL", "")
    t = re.sub(r"\s+", "", t)
    if not t or not re.search(r"\d", t):
        return None
    negativo = False
    if t.startswith("(") and t.endswith(")"):
        negativo, t = True, t[1:-1]
    if t[-1:] in ("D", "C") and re.search(r"\d[DC]$", t):
        negativo, t = t[-1] == "D", t[:-1]
    if t.endswith("-"):
        negativo, t = True, t[:-1]
    if t.startswith("-"):
        negativo, t = True, t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    if (decimal or adivinhar_decimal([t])) == ",":
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        valor = float(t)
    except ValueError:
        return None
    return -valor if negativo else valor


MESES = {"JAN": 1, "FEV": 2, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAI": 5, "MAY": 5, "JUN": 6, "JUL": 7,
         "AGO": 8, "AUG": 8, "SET": 9, "SEP": 9, "OUT": 10, "OCT": 10, "NOV": 11, "DEZ": 12, "DEC": 12}


def _data_valida(a, m, d):
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def ler_data(texto, ordem="dmy", hoje=None):
    """Aceita AAAA-MM-DD, DD/MM/AAAA, DD/MM/AA, DD/MM (ano atual), '19 OUT 2026', AAAAMMDD e série do Excel."""
    if isinstance(texto, date):
        return texto.isoformat()
    if isinstance(texto, (int, float)) and not isinstance(texto, bool):
        if 20000 < texto < 80000:  # data gravada como número no Excel
            return (date(1899, 12, 30) + timedelta(days=int(texto))).isoformat()
        return None
    t = str(texto or "").strip()
    if not t:
        return None
    hoje = hoje or date.today()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        return _data_valida(*m.groups())
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", t)
    if m:
        a, b, ano = m.groups()
        dia, mes = (b, a) if ordem == "mdy" else (a, b)
        ano = int(ano) + (2000 if len(ano) == 2 else 0)
        return _data_valida(ano, mes, dia)
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", t)
    if m:
        return _sem_ano(int(m.group(1)), int(m.group(2)), hoje)
    m = re.match(r"^(\d{1,2})\s*(?:DE\s+)?([A-Z]{3})[A-Z]*\.?(?:\s*(?:DE\s+)?(\d{2,4}))?$", regras.normalizar(t).replace("/", " "))
    if m and m.group(2) in MESES:
        dia, mes, ano = int(m.group(1)), MESES[m.group(2)], m.group(3)
        if not ano:
            return _sem_ano(dia, mes, hoje)
        return _data_valida(int(ano) + (2000 if len(ano) == 2 else 0), mes, dia)
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", t)
    if m:
        return _data_valida(*m.groups())
    return None


def _sem_ano(dia, mes, hoje):
    """Data sem ano (alguns extratos de cartão): ano atual, ou o anterior se cairia muito no futuro."""
    iso = _data_valida(hoje.year, mes, dia)
    if iso and iso > (hoje + timedelta(days=60)).isoformat():
        iso = _data_valida(hoje.year - 1, mes, dia)
    return iso


def ordem_datas(textos):
    """'mdy' só quando o arquivo deixa claro (algum segundo número > 12 e nenhum primeiro > 12)."""
    primeiro = segundo = False
    for t in textos:
        m = re.match(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}", str(t))
        if m:
            primeiro |= int(m.group(1)) > 12
            segundo |= int(m.group(2)) > 12
    return "mdy" if segundo and not primeiro else "dmy"


def data_no_nome(nome):
    """'Nubank_2026-10-10.csv' → '2026-10-10'."""
    m = re.search(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", nome) or None
    if m:
        return _data_valida(*m.groups())
    m = re.search(r"(\d{2})[-_.](\d{2})[-_.](20\d{2})", nome)
    return _data_valida(m.group(3), m.group(2), m.group(1)) if m else None


# ============================================================ parcelas e linhas de saldo
RE_PARCELA_EXPLICITA = re.compile(r"[\s\-–(]*\b(?:PARCELA|PARC\.?|PRC)\s*(\d{1,2})\s*(?:/|DE)\s*(\d{1,2})\)?", re.I)
RE_PARCELA_SUFIXO = re.compile(r"\s*\b(\d{1,2})/(\d{1,2})\s*$")
RE_SO_PARCELA = re.compile(r"^\s*(\d{1,2})\s*(?:/|DE)\s*(\d{1,2})\s*$", re.I)
RE_SALDO = re.compile(r"^(S ?A ?L ?D ?O\b|SDO\b|SALDO (ANTERIOR|DO DIA|FINAL|TOTAL|DISPONIVEL|EM CONTA|INICIAL|ATUAL|BLOQ\w*|"
                      r"APLIC\w*)|SALDO$|TOTAL\b)")


def parcela_valida(k, n):
    return 1 <= k <= n and 2 <= n <= 72


def achar_parcela(descricao, texto_coluna=None):
    """Devolve (parcela [k, n] | None, trecho a remover da descrição, parcela só pelo sufixo 'NN/NN')."""
    if texto_coluna:
        m = RE_PARCELA_EXPLICITA.search(texto_coluna) or RE_SO_PARCELA.match(texto_coluna)
        if m and parcela_valida(int(m.group(1)), int(m.group(2))):
            return [int(m.group(1)), int(m.group(2))], "", None
    m = RE_PARCELA_EXPLICITA.search(descricao)
    if m and parcela_valida(int(m.group(1)), int(m.group(2))):
        return [int(m.group(1)), int(m.group(2))], m.group(0), None
    m = RE_PARCELA_SUFIXO.search(descricao)
    if m and parcela_valida(int(m.group(1)), int(m.group(2))):
        return None, m.group(0), [int(m.group(1)), int(m.group(2))]
    return None, "", None


def novo_extrato(formato, **campos):
    extrato = {"formato": formato, "tipo": None, "instituicao": None, "banco": None, "agencia": None,
               "numero": None, "saldo": None, "saldoData": None, "lancamentos": [], "posicoes": [], "avisos": [],
               "assinatura": None, "cabecalho": None, "amostra": None, "colunas": None,
               "precisaMapeamento": False, "dataNoNome": None, "dataPosicao": None}
    extrato.update(campos)
    return extrato


def lancamento(data, descricao, valor, id_origem=None, texto_parcela=None):
    descricao = re.sub(r"\s+", " ", html.unescape(str(descricao or ""))).strip()
    parcela, trecho, sufixo = achar_parcela(descricao, texto_parcela)
    return {"idOrigem": id_origem or None, "data": data, "descricao": descricao, "valor": round(valor, 2),
            "parcela": parcela, "trechoParcela": trecho, "parcelaSufixo": sufixo}


# ============================================================ instituição
PALAVRAS_EXTRAS = [
    ("NU PAGAMENTOS", "Nubank"), ("NUBANK", "Nubank"), ("NU INVEST", "Nubank"), ("NUCONTA", "Nubank"),
    ("ITAU", "Itaú"), ("UNIBANCO", "Itaú"), ("ITAUCARD", "Itaú"), ("BRADESCO", "Bradesco"), ("SANTANDER", "Santander"),
    ("CAIXA", "Caixa"), ("BANCO DO BRASIL", "Banco do Brasil"), ("BANCO INTER", "Inter"), ("INTER", "Inter"),
    ("C6", "C6 Bank"), ("BTG", "BTG Pactual"), ("XP", "XP"), ("RICO", "Rico"), ("CLEAR", "Clear"),
    ("MERCADO ?PAGO", "Mercado Pago"), ("MERCADOPAGO", "Mercado Pago"), ("PICPAY", "PicPay"), ("SICOOB", "Sicoob"),
    ("SICREDI", "Sicredi"), ("NEON", "Neon"), ("PAGBANK", "PagBank"), ("PAGSEGURO", "PagBank"), ("ORIGINAL", "Banco Original"),
    ("SAFRA", "Safra"), ("BANRISUL", "Banrisul"), ("WILL ?BANK", "Will Bank"), ("GENIAL", "Genial"), ("ORAMA", "Órama"),
    ("WARREN", "Warren"), ("AGORA", "Ágora"), ("TORO", "Toro"), ("MODAL", "Modal"), ("AVENUE", "Avenue"),
    ("BB", "Banco do Brasil"), ("NU", "Nubank"),
]


def adivinhar_instituicao(*textos):
    t = regras.normalizar(" ".join(str(x or "") for x in textos)).replace("_", " ")
    for chave, nome in PALAVRAS_EXTRAS:
        if re.search(rf"(^|[^A-Z0-9]){chave}([^A-Z]|$)", t):
            return nome
    return None


def nome_instituicao_livre(texto):
    """'XP INVESTIMENTOS CCTVM S/A' → 'XP'; desconhecida → duas primeiras palavras em formato de título."""
    if not texto:
        return None
    conhecida = adivinhar_instituicao(texto)
    if conhecida:
        return conhecida
    palavras = [p for p in re.split(r"\s+", str(texto).strip()) if p]
    return " ".join(palavras[:2]).title() if palavras else None


def instituicao_por_codigo(codigo):
    digitos = regras.so_digitos(codigo)
    return regras.CODIGOS_BANCO.get(str(int(digitos)).zfill(3)) if digitos else None


# ============================================================ OFX
def _campo(bloco, tag):
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, re.I)
    return html.unescape(m.group(1)).strip() if m and m.group(1).strip() else None


def ler_ofx(texto, nome=""):
    corpo = texto[texto.upper().find("<OFX>"):] if "<OFX>" in texto.upper() else texto
    org = _campo(corpo, "ORG")
    blocos = [(m.group(1).upper(), m.group(2)) for m in re.finditer(r"<(STMTRS|CCSTMTRS)>(.*?)</\1>", corpo, re.S | re.I)]
    if not blocos:
        blocos = [("CCSTMTRS" if re.search(r"<CCACCTFROM>", corpo, re.I) else "STMTRS", corpo)]
    extratos = []
    for raiz, bloco in blocos:
        cartao = raiz == "CCSTMTRS"
        banco = regras.so_digitos(_campo(bloco, "BANKID"))
        banco = str(int(banco)).zfill(3) if banco else None
        extrato = novo_extrato("OFX", tipo="cartao" if cartao else "conta", banco=banco,
                               agencia=_campo(bloco, "BRANCHID"), numero=_campo(bloco, "ACCTID"),
                               dataNoNome=data_no_nome(nome))
        extrato["instituicao"] = instituicao_por_codigo(banco) or adivinhar_instituicao(org, nome)
        if _campo(bloco, "ACCTTYPE") == "SAVINGS":
            extrato["subtipo"] = "SAVINGS_ACCOUNT"
        saldo = re.search(r"<LEDGERBAL>(.*?)(</LEDGERBAL>|$)", bloco, re.S | re.I)
        if saldo:
            extrato["saldo"] = ler_valor(_campo(saldo.group(1), "BALAMT"))
            extrato["saldoData"] = ler_data(_campo(saldo.group(1), "DTASOF") or "")
        brutos = []
        for pedaco in re.split(r"<STMTTRN>", bloco, flags=re.I)[1:]:
            pedaco = re.split(r"</STMTTRN>|</BANKTRANLIST>", pedaco, flags=re.I)[0]
            data = ler_data((_campo(pedaco, "DTPOSTED") or _campo(pedaco, "DTUSER") or "")[:8])
            valor = ler_valor(_campo(pedaco, "TRNAMT"))
            nome_tx, memo = _campo(pedaco, "NAME"), _campo(pedaco, "MEMO")
            if nome_tx and memo and regras.normalizar(nome_tx) not in regras.normalizar(memo):
                descricao = f"{nome_tx} {memo}"
            else:
                descricao = memo or nome_tx or _campo(pedaco, "TRNTYPE") or ""
            if not data or not valor or RE_SALDO.search(regras.normalizar(descricao)):
                continue
            brutos.append((_campo(pedaco, "FITID"), data, descricao, valor))
        # Há bancos que repetem o FITID; aí ele não serve para identificar o lançamento.
        fitids = [b[0] for b in brutos if b[0]]
        confiavel = len(fitids) == len(brutos) and len(set(fitids)) == len(fitids)
        if brutos and not confiavel:
            extrato["avisos"].append("O arquivo não traz um identificador único por lançamento; "
                                     "duplicados são detectados por data, valor e descrição.")
        extrato["lancamentos"] = [lancamento(d, desc, v, fitid if confiavel else None) for fitid, d, desc, v in brutos]
        extrato["assinatura"] = "ofx:" + ("cartao" if cartao else "conta") + f":{banco or ''}:{regras.so_digitos(extrato['numero'])}"
        extratos.append(extrato)
    return extratos


# ============================================================ planilhas (CSV, XLSX, HTML)
def ler_csv(texto):
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    amostra = linhas[:40]
    melhor, pontos = ",", -1
    for sep in (";", ",", "\t", "|"):
        contagens = [len(next(csv.reader([l], delimiter=sep))) for l in amostra]
        repetidas = max(set(contagens), key=contagens.count)
        nota = contagens.count(repetidas) * (repetidas > 1) * min(repetidas, 12)
        if nota > pontos:
            melhor, pontos = sep, nota
    return [[c.strip() for c in linha] for linha in csv.reader(io.StringIO("\n".join(linhas)), delimiter=melhor)]


NS_PLANILHA = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_RELACAO = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
FORMATOS_DATA = set(range(14, 23)) | {45, 46, 47}


def _indice_coluna(referencia):
    letras = re.match(r"[A-Z]+", referencia or "A").group(0)
    indice = 0
    for letra in letras:
        indice = indice * 26 + ord(letra) - 64
    return indice - 1


def ler_xlsx(conteudo):
    """Lê todas as abas de um .xlsx. Números viram float; células com formato de data viram 'AAAA-MM-DD'."""
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        raise ErroLeitura("Arquivo .xlsx corrompido ou incompleto.") from None
    nomes = set(arquivo.namelist())

    compartilhadas = []
    if "xl/sharedStrings.xml" in nomes:
        for si in ET.fromstring(arquivo.read("xl/sharedStrings.xml")).iter(f"{NS_PLANILHA}si"):
            compartilhadas.append("".join(t.text or "" for t in si.iter(f"{NS_PLANILHA}t")))

    estilos_data = set()
    if "xl/styles.xml" in nomes:
        estilos = ET.fromstring(arquivo.read("xl/styles.xml"))
        proprios = {int(f.get("numFmtId")) for f in estilos.iter(f"{NS_PLANILHA}numFmt")
                    if re.search(r"[dy]", re.sub(r'"[^"]*"|\[[^\]]*\]', "", f.get("formatCode", "")), re.I)}
        xfs = estilos.find(f"{NS_PLANILHA}cellXfs")
        for i, xf in enumerate(xfs if xfs is not None else []):
            formato = int(xf.get("numFmtId", 0))
            if formato in FORMATOS_DATA or formato in proprios:
                estilos_data.add(i)

    alvos = {}
    if "xl/_rels/workbook.xml.rels" in nomes:
        for rel in ET.fromstring(arquivo.read("xl/_rels/workbook.xml.rels")):
            alvo = rel.get("Target", "")
            alvos[rel.get("Id")] = alvo.lstrip("/") if alvo.startswith("/") else "xl/" + alvo
    abas = []
    livro = ET.fromstring(arquivo.read("xl/workbook.xml"))
    for folha in livro.iter(f"{NS_PLANILHA}sheet"):
        caminho = alvos.get(folha.get(f"{NS_RELACAO}id"))
        if not caminho or caminho not in nomes:
            continue
        linhas = []
        for row in ET.fromstring(arquivo.read(caminho)).iter(f"{NS_PLANILHA}row"):
            celulas = {}
            for c in row.iter(f"{NS_PLANILHA}c"):
                tipo, v = c.get("t"), c.find(f"{NS_PLANILHA}v")
                if tipo == "inlineStr":
                    valor = "".join(t.text or "" for t in c.iter(f"{NS_PLANILHA}t"))
                elif v is None or v.text is None:
                    continue
                elif tipo == "s":
                    valor = compartilhadas[int(v.text)]
                elif tipo in ("str", "e"):
                    valor = v.text
                elif tipo == "b":
                    valor = v.text == "1"
                else:
                    try:
                        valor = float(v.text)
                    except ValueError:
                        valor = v.text
                    if isinstance(valor, float) and int(c.get("s", 0)) in estilos_data:
                        valor = ler_data(valor) or valor
                celulas[_indice_coluna(c.get("r"))] = valor
            if celulas:
                linhas.append([celulas.get(i, "") for i in range(max(celulas) + 1)])
        abas.append((folha.get("name") or "", linhas))
    return abas


class _LeitorHtml(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tabelas, self.linha, self.celula = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tabelas.append([])
        elif tag == "tr" and self.tabelas:
            self.linha = []
        elif tag in ("td", "th") and self.linha is not None:
            self.celula = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.celula is not None:
            self.linha.append(re.sub(r"\s+", " ", "".join(self.celula)).strip())
            self.celula = None
        elif tag == "tr" and self.linha is not None:
            if any(self.linha):
                self.tabelas[-1].append(self.linha)
            self.linha = None

    def handle_data(self, dados):
        if self.celula is not None:
            self.celula.append(dados)


def ler_html(texto):
    leitor = _LeitorHtml()
    leitor.feed(texto)
    return [(f"tabela {i + 1}", t) for i, t in enumerate(leitor.tabelas) if t]


# ---- papéis das colunas
PAPEIS = [
    ("data", r"^(data|date|dt|dia)$|^data (do |da |de )?(lancamento|compra|transacao|movimento|mov\.?|ocorrencia|operacao|pagamento)|"
             r"^dt\.? ?(lanc|mov)|^release_date|^data$"),
    ("parcela", r"^(n.? ?)?parcelas?$|^parc\.?$|^parcela|installment"),
    ("final", r"final do cartao|^final$|^cartao final|^ultimos digitos"),
    ("categoria", r"^categoria|^category"),
    ("credito", r"^(valor )?(credito|entrada|receita)s?( \(r\$\))?$|^credito"),
    ("debito", r"^(valor )?(debito|saida|despesa)s?( \(r\$\))?$|^debito"),
    ("saldo", r"^saldo|balance$"),
    ("valor", r"^valor|^amount|^value$|net_amount|^montante|^quantia"),
    ("sinal", r"^(tipo|d/c|c/d|deb/cred|cred/deb|natureza|tipo (de )?(lancamento|transacao|movimento|operacao))$"),
    ("id", r"^identificador|^id$|reference_id|^fitid|documento|^n.? ?doc|^docto|^autenticacao|^codigo da transacao"),
    ("descricao", r"descri|historico|^lancamento|^title$|estabelecimento|detalhe|^memo$|transaction_type|complemento|"
                  r"^titulo$|^favorecido|^beneficiario|^contraparte|^nome do (favorecido|estabelecimento)"),
]
IGNORAR_VALOR = re.compile(r"us\$|usd|dolar|cotacao|moeda estrangeira|iof")


def papel_da_coluna(nome):
    n = norm(nome)
    if not n:
        return None
    for papel, padrao in PAPEIS:
        if re.search(padrao, n):
            if papel in ("valor", "credito", "debito") and IGNORAR_VALOR.search(n):
                return None
            return papel
    return None


def _eh_sinal(textos):
    validos = [norm(t) for t in textos if str(t).strip()]
    bons = [t for t in validos if re.fullmatch(r"(d|c|-|\+|debito|credito|saida|entrada|deb|cred)\.?", t)]
    return validos and len(bons) / len(validos) >= 0.8


def _eh_parcela(textos):
    validos = [str(t) for t in textos if str(t).strip()]
    return validos and any(RE_PARCELA_EXPLICITA.search(t) or RE_SO_PARCELA.match(t) for t in validos) and all(
        RE_PARCELA_EXPLICITA.search(t) or RE_SO_PARCELA.match(t) or re.search(r"vista|unica|^-$|^0$", norm(t)) or len(t) < 25
        for t in validos)


def mapear_por_cabecalho(cabecalho, linhas):
    """{papel: [índices]} pelos nomes das colunas, conferindo o conteúdo das colunas ambíguas."""
    papeis = {}
    for i, nome in enumerate(cabecalho):
        papel = papel_da_coluna(nome)
        coluna = [l[i] for l in linhas[:200] if i < len(l)]
        if papel == "sinal" and not _eh_sinal(coluna):
            papel = "parcela" if _eh_parcela(coluna) else None
        if papel is None and norm(nome) in ("tipo", "situacao") and _eh_parcela(coluna):
            papel = "parcela"
        if papel:
            papeis.setdefault(papel, []).append(i)
    # 'Data' repetida (ex.: data da compra e data de lançamento): fica a primeira.
    return papeis


def mapear_por_conteudo(linhas):
    """Sem cabeçalho reconhecível: acha data, valor e descrição pelo que tem dentro de cada coluna."""
    if not linhas:
        return {}
    ncol = max(len(l) for l in linhas)
    amostra = linhas[:200]
    stats = []
    for i in range(ncol):
        coluna = [l[i] for l in amostra if i < len(l) and str(l[i]).strip()]
        if not coluna:
            stats.append((0, 0, 0))
            continue
        datas = sum(1 for c in coluna if ler_data(c)) / len(coluna)
        valores = sum(1 for c in coluna if not ler_data(c) and ler_valor(c) is not None
                      and re.search(r"[.,]\d{2}$|^-?\d+$", re.sub(r"[^\d.,-]", "", str(c)))) / len(coluna)
        texto = sum(len(re.sub(r"[^A-Za-zÀ-ú ]", "", str(c))) for c in coluna) / len(coluna)
        stats.append((datas, valores, texto))
    papeis = {}
    datas = [i for i, s in enumerate(stats) if s[0] >= 0.8]
    if datas:
        papeis["data"] = [datas[0]]
    valores = [i for i, s in enumerate(stats) if s[1] >= 0.8 and i not in datas]
    if valores:
        papeis["valor"] = [valores[0]]
        if len(valores) > 1 and _parece_saldo(amostra, valores[0], valores[-1]):
            papeis["saldo"] = [valores[-1]]
    textos = sorted((s[2], i) for i, s in enumerate(stats) if i not in datas and i not in valores and s[2] >= 3)
    if textos:
        papeis["descricao"] = [textos[-1][1]]
    return papeis


def _parece_saldo(linhas, col_valor, col_saldo):
    """A coluna de saldo é o acumulado da coluna de valor (em qualquer ordem)."""
    pares = [(ler_valor(l[col_valor]), ler_valor(l[col_saldo])) for l in linhas
             if max(col_valor, col_saldo) < len(l)]
    pares = [p for p in pares if None not in p]
    if len(pares) < 3:
        return False
    acertos = sum(1 for (_, s0), (v1, s1) in zip(pares, pares[1:]) if abs(s0 + v1 - s1) < 0.01 or abs(s1 + v1 - s0) < 0.01)
    return acertos / (len(pares) - 1) >= 0.6


def achar_cabecalho(linhas):
    """Índice da linha de cabeçalho (bancos costumam pôr agência, conta e período antes)."""
    melhor, pontos = -1, 0
    for i, linha in enumerate(linhas[:40]):
        papeis = {papel_da_coluna(c) for c in linha if isinstance(c, str)} - {None}
        nota = len(papeis) + 2 * ("data" in papeis) + 2 * bool(papeis & {"valor", "credito", "debito"})
        if "data" in papeis and papeis & {"valor", "credito", "debito"} and nota > pontos:
            melhor, pontos = i, nota
    return melhor


def saldo_no_preambulo(linhas):
    """'Saldo atual: R$ 1.234,56' ou 'FINAL_BALANCE' com o valor ao lado/abaixo, antes da tabela."""
    rotulo = re.compile(r"saldo (atual|final|disponivel|em conta)|final_balance|^saldo$")
    for i, linha in enumerate(linhas):
        for j, celula in enumerate(linha):
            if not isinstance(celula, str) or not rotulo.search(norm(celula.split(":")[0])):
                continue
            candidatos = [celula.split(":", 1)[1]] if ":" in celula else []
            candidatos += linha[j + 1:j + 2]
            if i + 1 < len(linhas) and j < len(linhas[i + 1]):
                candidatos.append(linhas[i + 1][j])
            for c in candidatos:
                v = ler_valor(c)
                if v is not None and not ler_data(c):
                    return v
    return None


def assinatura(cabecalho, ncol):
    chave = "|".join(norm(c) for c in cabecalho) if cabecalho else f"sem-cabecalho:{ncol}"
    return "tab:" + hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def interpretar_lancamentos(linhas, papeis, hoje=None):
    """Converte as linhas em lançamentos usando o mapeamento {papel: [índices]}."""
    pega = lambda linha, papel: [linha[i] for i in papeis.get(papel, []) if i < len(linha)]
    primeiro = lambda linha, papel: next(iter(pega(linha, papel)), "")
    colunas_valor = [i for p in ("valor", "credito", "debito") for i in papeis.get(p, [])]
    decimal = adivinhar_decimal(l[i] for l in linhas for i in colunas_valor + papeis.get("saldo", []) if i < len(l))
    ordem = ordem_datas(primeiro(l, "data") for l in linhas)
    resultado, saldos, saldo_linhas = [], [], []
    for n, linha in enumerate(linhas):
        data = ler_data(primeiro(linha, "data"), ordem, hoje)
        descricao = " ".join(str(c).strip() for c in pega(linha, "descricao") if str(c).strip())
        if papeis.get("valor"):
            valor = ler_valor(primeiro(linha, "valor"), decimal)
        else:
            credito, debito = ler_valor(primeiro(linha, "credito"), decimal), ler_valor(primeiro(linha, "debito"), decimal)
            valor = None if credito is None and debito is None else abs(credito or 0) - abs(debito or 0)
        if valor is not None and papeis.get("sinal"):
            s = norm(primeiro(linha, "sinal"))
            if re.match(r"(d|-|deb|saida)", s):
                valor = -abs(valor)
            elif re.match(r"(c|\+|cred|entrada)", s):
                valor = abs(valor)
        if not data:
            # Linha só com texto logo abaixo de um lançamento = continuação da descrição (Bradesco faz isso).
            if valor is None and descricao and resultado and resultado[-1]["_linha"] == n - 1:
                resultado[-1]["descricao"] += " " + descricao
                resultado[-1]["_linha"] = n
            continue
        if papeis.get("saldo"):
            s = ler_valor(primeiro(linha, "saldo"), decimal)
            if s is not None:
                saldos.append((data, n, s))
        if RE_SALDO.search(regras.normalizar(descricao)):
            if valor is not None:
                saldo_linhas.append((data, n, valor))
            continue
        if not valor:
            continue
        tx = lancamento(data, descricao, valor, primeiro(linha, "id") or None, primeiro(linha, "parcela") or None)
        tx["_linha"] = n
        resultado.append(tx)
    for tx in resultado:
        tx.pop("_linha")
    ids = [t["idOrigem"] for t in resultado]
    if any(ids) and (None in ids or len(set(ids)) != len(ids)):
        for t in resultado:  # identificador repetido ou faltando não serve para deduplicar
            t["idOrigem"] = None
    saldo = None
    for lista in (saldos, saldo_linhas):
        if lista:
            # Saldo do lançamento mais recente; com datas empatadas, depende da ordem do arquivo.
            decrescente = lista[0][0] > lista[-1][0]
            ultimo = max(lista, key=lambda x: (x[0], -x[1] if decrescente else x[1]))
            saldo = (ultimo[2], ultimo[0])
            break
    return resultado, saldo


# ---- posições de investimento
COLUNAS_POSICAO = [
    ("nome", r"^produto$|^nome|^ativo$|^papel|^titulo$|^investimento$|^aplicacao$|^descricao do (ativo|produto)"),
    ("codigo", r"codigo de negociacao|^codigo$|^ticker"),
    ("saldo", r"valor atualizado curva|^valor atualizado$|^saldo|valor liquido|valor bruto|^valor atual|^posicao|"
              r"^valor atualizado|^valor$|^total$"),
    ("instituicao", r"^instituicao|corretora|^banco$|^custodiante"),
    ("tipo", r"^tipo$|^classe|^categoria|^tipo de (ativo|investimento|produto)"),
    ("vencimento", r"vencimento"),
    ("indexador", r"indexador|^index"),
    ("taxa", r"^taxa|rentabilidade contratada|^remuneracao"),
    ("emissor", r"^emissor"),
    ("quantidade", r"^quantidade$|^qtde?\.?$|^cotas$"),
]


def _colunas_posicao(cabecalho):
    colunas = {}
    prioridade_saldo = None
    for i, nome in enumerate(cabecalho):
        n = norm(nome)
        for papel, padrao in COLUNAS_POSICAO:
            if not re.search(padrao, n):
                continue
            if papel == "saldo":
                # Entre várias colunas de valor, vale a que aparece antes na lista de padrões.
                ordem = next(k for k, p in enumerate(COLUNAS_POSICAO[2][1].split("|")) if re.search(p, n))
                if prioridade_saldo is None or ordem < prioridade_saldo:
                    colunas["saldo"], prioridade_saldo = i, ordem
            else:
                colunas.setdefault(papel, i)
            break
    return colunas


def tipo_investimento(*textos):
    t = regras.normalizar(" ".join(str(x or "") for x in textos))
    regras_tipo = [
        # Exterior primeiro: "Renda fixa internacional" e "Ações EUA" não podem cair na renda fixa e nas ações daqui.
        (r"\bREITS?\b", ("EQUITY", "REIT")),
        (r"\b(ACAO|ACOES|STOCKS?)\W+(INTERNACION|EXTERIOR|EUA|AMERICAN|GLOBA)|(INTERNACION|EXTERIOR)\w*\W+(\w+\W+)?(ACAO|ACOES|STOCKS?)\b",
         ("EQUITY", "FOREIGN_STOCK")),
        (r"RENDA FIXA\W+(INTERNACION|EXTERIOR|GLOBA)|(INTERNACION|EXTERIOR)\w*\W+(\w+\W+)?RENDA FIXA|\bBONDS?\b|\bT-?BILLS?\b|\bTREASUR(Y|IES)\b",
         ("FIXED_INCOME", "FOREIGN_FIXED_INCOME")),
        (r"TESOURO|\bLTN\b|\bNTN|\bLFT\b", ("FIXED_INCOME", "TREASURY")), (r"\bCDB\b", ("FIXED_INCOME", "CDB")),
        (r"\bLCI\b", ("FIXED_INCOME", "LCI")), (r"\bLCA\b", ("FIXED_INCOME", "LCA")), (r"\bLCD\b|\bLC\b", ("FIXED_INCOME", "LC")),
        (r"DEBENTURE", ("FIXED_INCOME", "DEBENTURES")), (r"\bCRI\b", ("FIXED_INCOME", "CRI")), (r"\bCRA\b", ("FIXED_INCOME", "CRA")),
        (r"LETRA FINANCEIRA|\bLF\b", ("FIXED_INCOME", "LF")), (r"POUPANCA", ("FIXED_INCOME", "SAVINGS")),
        (r"PREVIDENCIA|\bPGBL\b|\bVGBL\b", ("SECURITY", "RETIREMENT")), (r"CRIPTO|CRYPTO|BITCOIN|ETHEREUM|\bBTC\b|\bETH\b|\bUSD[TC]\b", ("OTHER", "CRYPTO")),
        (r"\bFII\b|IMOBILIARI|\bFDO\.? INV\.? IMOB", ("MUTUAL_FUND", "REAL_ESTATE_FUND")), (r"\bETF\b", ("ETF", "ETF")), (r"\bBDR\b", ("EQUITY", "BDR")),
        (r"MULTIMERCADO", ("MUTUAL_FUND", "MULTIMARKET_FUND")), (r"FUNDO.*RENDA FIXA|\bFIRF\b", ("MUTUAL_FUND", "FIXED_INCOME_FUND")),
        (r"FUNDO.*ACOES|\bFIA\b", ("MUTUAL_FUND", "STOCK_FUND")), (r"FUNDO|\bFIC\b|\bFIM\b", ("MUTUAL_FUND", "INVESTMENT_FUND")),
        (r"\bACOES\b|\bACAO\b|\bSTOCK", ("EQUITY", "STOCK")), (r"RENDA FIXA", ("FIXED_INCOME", None)),
        (r"\b[A-Z]{4}\d{1,2}\b", ("EQUITY", "STOCK")),
    ]
    for padrao, tipo in regras_tipo:
        if re.search(padrao, t):
            return tipo
    return "OTHER", None


def interpretar_posicoes(abas):
    posicoes = []
    for nome_aba, linhas in abas:
        for i, linha in enumerate(linhas[:30]):
            colunas = _colunas_posicao([c if isinstance(c, str) else "" for c in linha])
            if "saldo" in colunas and ("nome" in colunas or "codigo" in colunas):
                break
        else:
            continue
        if any(papel_da_coluna(c) == "data" for c in linha if isinstance(c, str)):
            continue  # tem data de lançamento: é extrato, não posição
        pega = lambda l, papel: l[colunas[papel]] if papel in colunas and colunas[papel] < len(l) else ""
        decimal = adivinhar_decimal(pega(l, "saldo") for l in linhas[i + 1:])
        for l in linhas[i + 1:]:
            nome, codigo = str(pega(l, "nome")).strip(), str(pega(l, "codigo")).strip()
            saldo = ler_valor(pega(l, "saldo"), decimal)
            rotulo = nome or codigo
            if not rotulo or saldo is None or re.match(r"^(TOTAL|SUBTOTAL)\b", regras.normalizar(rotulo)):
                continue
            if codigo and nome and regras.normalizar(codigo) not in regras.normalizar(nome):
                rotulo = f"{codigo} · {nome}"
            tipo, subtipo = tipo_investimento(pega(l, "tipo"), nome_aba, rotulo)
            taxa = ler_valor(pega(l, "taxa"))
            quantidade = ler_valor(pega(l, "quantidade"), decimal)
            posicoes.append({
                "nome": rotulo[:120], "tipo": tipo, "subtipo": subtipo, "saldo": round(saldo, 2),
                "instituicao": nome_instituicao_livre(pega(l, "instituicao")), "vencimento": ler_data(pega(l, "vencimento")),
                "indexador": str(pega(l, "indexador")).strip() or None, "taxa": taxa, "emissor": str(pega(l, "emissor")).strip() or None,
                # Ações e FIIs: ticker e quantidade dão o preço do dia e os proventos a receber.
                "codigo": codigo.upper() if re.fullmatch(r"[A-Za-z]{4}\d{1,2}F?", codigo) else None,
                "quantidade": quantidade if quantidade and quantidade > 0 else None,
            })
    return posicoes


# ---- tipo e instituição de planilhas conhecidas
def reconhecer(cabecalho, preambulo, nome):
    """(tipo, instituição) por assinaturas de bancos conhecidos, nome do arquivo e texto antes da tabela."""
    c = [norm(x) for x in cabecalho]
    texto = " ".join(str(x) for linha in preambulo for x in linha)
    if c[:3] == ["date", "title", "amount"] or c == ["date", "category", "title", "amount"]:
        return "cartao", "Nubank"
    if c == ["data", "valor", "identificador", "descricao"]:
        return "conta", "Nubank"
    if "nome no cartao" in c or "final do cartao" in c:
        return "cartao", adivinhar_instituicao(nome, texto) or "C6 Bank"
    if c and c[0] == "release_date":
        return "conta", "Mercado Pago"
    instituicao = adivinhar_instituicao(nome, texto)
    if (any(papel_da_coluna(x) == "parcela" for x in cabecalho) or re.search(r"fatura|cartao|card", norm(nome))
            or "fatura" in norm(texto)):
        return "cartao", instituicao
    return "conta", instituicao


def interpretar_tabelas(abas, nome, formato, mapeamento=None, hoje=None):
    abas = [(n, [[c if not isinstance(c, str) else c.strip() for c in l] for l in linhas]) for n, linhas in abas]
    abas = [(n, linhas) for n, linhas in abas if linhas]
    if not abas:
        raise ErroLeitura("O arquivo está vazio.")

    if not mapeamento:
        posicoes = interpretar_posicoes(abas)
        if posicoes:
            # Identifica o tipo de planilha (B3, modelo, planilha do banco) pelos nomes das abas e colunas.
            estrutura = "|".join(f"{n}:{','.join(norm(c) for c in (l[0] if l else []) if isinstance(c, str))}" for n, l in abas)
            return [novo_extrato(formato, tipo="investimentos", posicoes=posicoes, dataNoNome=data_no_nome(nome),
                                 dataPosicao=data_no_nome(nome),
                                 assinatura="posicoes:" + hashlib.sha1(estrutura.encode("utf-8")).hexdigest()[:12])]

    candidatos = abas
    if mapeamento and mapeamento.get("aba"):
        candidatos = [a for a in abas if a[0] == mapeamento["aba"]] or abas
    primeiro_vazio = None
    for nome_aba, linhas in candidatos:
        if mapeamento:
            topo = int(mapeamento.get("cabecalho", -1))
            papeis = {p: [int(i) for i in ids] for p, ids in mapeamento["papeis"].items() if ids}
        else:
            topo = achar_cabecalho(linhas)
            papeis = mapear_por_cabecalho(linhas[topo], linhas[topo + 1:]) if topo >= 0 else {}
            if "data" not in papeis or not papeis.keys() & {"valor", "credito", "debito"}:
                topo_conteudo = topo
                papeis_conteudo = mapear_por_conteudo(linhas[topo + 1:])
                if papeis_conteudo.keys() >= {"data", "valor"}:
                    papeis = {**papeis_conteudo, **{k: v for k, v in papeis.items() if k not in papeis_conteudo}}
                    topo = topo_conteudo
            if "descricao" not in papeis and papeis:
                livres = [i for i in range(len(linhas[topo + 1] if topo + 1 < len(linhas) else []))
                          if i not in {j for ids in papeis.values() for j in ids}]
                texto = mapear_por_conteudo([[l[i] if i < len(l) else "" for i in livres] for l in linhas[topo + 1:]])
                if texto.get("descricao"):
                    papeis["descricao"] = [livres[texto["descricao"][0]]]
        cabecalho = linhas[topo] if topo >= 0 else []
        corpo = linhas[topo + 1:]
        ncol = max((len(l) for l in corpo[:50]), default=len(cabecalho))
        base = dict(assinatura=assinatura(cabecalho, ncol), aba=nome_aba,
                    cabecalho=[str(c) for c in cabecalho] or [f"Coluna {i + 1}" for i in range(ncol)],
                    linhaCabecalho=topo, amostra=[[str(c) for c in l] for l in corpo[:8]], dataNoNome=data_no_nome(nome))
        prontos = "data" in papeis and papeis.keys() & {"valor", "credito", "debito"} and "descricao" in papeis
        if not prontos:
            primeiro_vazio = primeiro_vazio or novo_extrato(formato, precisaMapeamento=True, colunas=papeis, **base)
            continue
        lancamentos, saldo = interpretar_lancamentos(corpo, papeis, hoje)
        if not lancamentos:
            primeiro_vazio = primeiro_vazio or novo_extrato(formato, precisaMapeamento=True, colunas=papeis, **base)
            continue
        tipo, instituicao = reconhecer(cabecalho, linhas[:max(topo, 0)], nome)
        extrato = novo_extrato(formato, tipo=tipo, instituicao=instituicao, lancamentos=lancamentos, colunas=papeis, **base)
        if saldo:
            extrato["saldo"], extrato["saldoData"] = saldo
        elif topo > 0:
            extrato["saldo"] = saldo_no_preambulo(linhas[:topo])
        if "final" in papeis:
            finais = {regras.so_digitos(str(l[papeis["final"][0]]))[-4:] for l in corpo if papeis["final"][0] < len(l)} - {""}
            if len(finais) == 1:
                extrato["numero"] = finais.pop()
        if not papeis.get("sinal") and not papeis.get("credito") and all(t["valor"] > 0 for t in lancamentos) and tipo == "conta":
            extrato["avisos"].append("Todos os valores são positivos: confira se as saídas não estão sendo lidas como entradas.")
        return [extrato]
    if primeiro_vazio:
        return [primeiro_vazio]
    raise ErroLeitura("Não encontrei lançamentos nem posições de investimento neste arquivo.")


# ============================================================ entrada
def ler_arquivo(nome, conteudo, mapeamento=None, hoje=None):
    """Lê o arquivo e devolve a lista de extratos. Levanta ErroLeitura com uma mensagem para a tela."""
    extensao = Path(nome).suffix.lower()
    if conteudo[:4] == b"%PDF" or extensao == ".pdf":
        raise ErroLeitura("PDF não dá para ler com segurança. No app ou site do banco, procure a opção de exportar "
                          "em OFX (às vezes chamado de Money/Quicken), CSV ou Excel.")
    if conteudo[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ErroLeitura("Esse é o formato .xls antigo do Excel. Abra o arquivo no Excel ou no Google Planilhas e salve "
                          "como .xlsx ou .csv — ou exporte do banco em OFX.")
    if conteudo[:2] == b"PK":
        return interpretar_tabelas(ler_xlsx(conteudo), nome, "XLSX", mapeamento, hoje)
    texto = decodificar(conteudo)
    if re.search(r"<OFX>|OFXHEADER", texto[:5000], re.I):
        return ler_ofx(texto, nome)
    if re.search(r"<table", texto[:50000], re.I):
        return interpretar_tabelas(ler_html(texto), nome, "XLS/HTML", mapeamento, hoje)
    return interpretar_tabelas([("", ler_csv(texto))], nome, "CSV", mapeamento, hoje)
