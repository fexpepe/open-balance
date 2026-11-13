"""Leitura dos arquivos dos bancos (openbalance/leitores.py): OFX, CSV/TXT, XLSX e o "XLS" que é HTML."""

import unittest
from datetime import date

from openbalance import leitores
from tests.ajudantes import arquivo, gerar_xlsx

HOJE = date(2026, 10, 15)


def ler(nome, conteudo=None):
    return leitores.ler_arquivo(nome, conteudo if conteudo is not None else arquivo(nome), hoje=HOJE)


class TestNumerosEDatas(unittest.TestCase):
    def test_valores_no_formato_brasileiro_e_americano(self):
        casos = {
            "R$ -1.234,56": -1234.56, "1.234,56 D": -1234.56, "1.234,56 C": 1234.56, "(50,00)": -50.0,
            "1234.56": 1234.56, "-89,90": -89.9, "10,00-": -10.0, "+7,5": 7.5, 12.5: 12.5,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertAlmostEqual(leitores.ler_valor(texto), esperado)

    def test_texto_que_nao_e_numero(self):
        for texto in ("", "abc", None, True, "SALDO"):
            with self.subTest(texto=texto):
                self.assertIsNone(leitores.ler_valor(texto))

    def test_decimal_decidido_pelo_arquivo_inteiro(self):
        self.assertEqual(leitores.adivinhar_decimal(["1.234,56", "10,00", "3"]), ",")
        self.assertEqual(leitores.adivinhar_decimal(["1,234.56", "10.00"]), ".")
        # "1.234" sozinho é milhar no padrão brasileiro
        self.assertEqual(leitores.adivinhar_decimal(["1.234"]), ",")

    def test_datas(self):
        casos = {
            "2026-09-05": "2026-09-05", "05/09/2026": "2026-09-05", "05/09/26": "2026-09-05",
            "19 OUT 2026": "2026-10-19", "19 de outubro de 2026": "2026-10-19", "20260905": "2026-09-05",
            46270: "2026-09-05",  # número de série do Excel
            "31/02/2026": None, "": None,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(leitores.ler_data(texto, hoje=HOJE), esperado)

    def test_data_sem_ano_nao_cai_no_futuro(self):
        self.assertEqual(leitores.ler_data("05/09", hoje=HOJE), "2026-09-05")
        # 20/12 estaria a mais de 60 dias de 15/10: é do ano anterior
        self.assertEqual(leitores.ler_data("20/12", hoje=HOJE), "2025-12-20")

    def test_ordem_mes_dia_so_quando_o_arquivo_deixa_claro(self):
        self.assertEqual(leitores.ordem_datas(["09/25/2026", "10/01/2026"]), "mdy")
        self.assertEqual(leitores.ordem_datas(["05/09/2026", "25/09/2026"]), "dmy")
        self.assertEqual(leitores.ordem_datas(["05/09/2026", "06/09/2026"]), "dmy")

    def test_data_no_nome_do_arquivo(self):
        self.assertEqual(leitores.data_no_nome("Fatura_2026-10-10.csv"), "2026-10-10")
        self.assertEqual(leitores.data_no_nome("extrato 10-10-2026.ofx"), "2026-10-10")
        self.assertIsNone(leitores.data_no_nome("extrato.ofx"))


class TestParcelas(unittest.TestCase):
    def test_parcela_explicita(self):
        parcela, trecho, sufixo = leitores.achar_parcela("Loja Exemplo - Parcela 2/4")
        self.assertEqual(parcela, [2, 4])
        self.assertEqual(trecho, " - Parcela 2/4")
        self.assertIsNone(sufixo)

    def test_sufixo_nn_nn_fica_separado(self):
        # "03/10" no fim pode ser data: quem decide se é parcela é o tipo da conta (importar.py)
        parcela, trecho, sufixo = leitores.achar_parcela("LOJA EXEMPLO 03/10")
        self.assertIsNone(parcela)
        self.assertEqual(sufixo, [3, 10])

    def test_coluna_de_parcela(self):
        self.assertEqual(leitores.achar_parcela("LOJA", "3 de 6")[0], [3, 6])

    def test_parcela_invalida(self):
        self.assertEqual(leitores.achar_parcela("LOJA 5/3"), (None, "", None))
        self.assertEqual(leitores.achar_parcela("LOJA PARCELA 1/1")[0], None)


class TestOfx(unittest.TestCase):
    def setUp(self):
        self.conta, self.cartao = ler("conta_e_cartao.ofx")

    def test_um_extrato_por_bloco(self):
        self.assertEqual(self.conta["formato"], "OFX")
        self.assertEqual(self.conta["tipo"], "conta")
        self.assertEqual(self.cartao["tipo"], "cartao")

    def test_dados_da_conta_e_saldo(self):
        self.assertEqual(self.conta["banco"], "999")
        self.assertEqual(self.conta["agencia"], "0001")
        self.assertEqual(self.conta["numero"], "12345-6")
        self.assertEqual(self.conta["saldo"], 3560.10)
        self.assertEqual(self.conta["saldoData"], "2026-09-30")
        self.assertEqual(self.cartao["numero"], "4321")

    def test_lancamentos_sem_a_linha_de_saldo(self):
        descricoes = [l["descricao"] for l in self.conta["lancamentos"]]
        self.assertEqual(len(descricoes), 4)
        self.assertNotIn("SALDO DO DIA", descricoes)
        primeiro = self.conta["lancamentos"][0]
        self.assertEqual((primeiro["idOrigem"], primeiro["data"], primeiro["valor"]), ("EX0001", "2026-09-05", 5000.0))
        self.assertEqual(self.conta["lancamentos"][1]["valor"], -1200.0)

    def test_parcela_no_cartao(self):
        loja = self.cartao["lancamentos"][1]
        self.assertEqual(loja["parcela"], [2, 5])

    def test_fitid_repetido_nao_serve_de_identificador(self):
        texto = arquivo("conta_e_cartao.ofx").decode("ascii").replace("<FITID>EX0002", "<FITID>EX0001")
        conta = leitores.ler_arquivo("x.ofx", texto.encode("ascii"))[0]
        self.assertTrue(all(l["idOrigem"] is None for l in conta["lancamentos"]))
        self.assertTrue(conta["avisos"])

    def test_assinatura_identifica_o_formato(self):
        self.assertEqual(self.conta["assinatura"], "ofx:conta:999:123456")


class TestCsv(unittest.TestCase):
    def test_extrato_com_preambulo_e_saldo(self):
        (extrato,) = ler("extrato_conta.csv")
        self.assertEqual(extrato["formato"], "CSV")
        self.assertEqual(extrato["tipo"], "conta")
        self.assertFalse(extrato["precisaMapeamento"])
        lanc = extrato["lancamentos"]
        self.assertEqual([l["data"] for l in lanc], ["2026-09-05", "2026-09-08", "2026-09-10", "2026-09-20"])
        self.assertEqual([l["valor"] for l in lanc], [5000.0, -1200.0, -89.9, -150.0])
        self.assertNotIn("SALDO ANTERIOR", [l["descricao"] for l in lanc])
        self.assertEqual((extrato["saldo"], extrato["saldoData"]), (3560.10, "2026-09-20"))

    def test_fatura_do_nubank(self):
        (fatura,) = ler("fatura_cartao.csv")
        self.assertEqual((fatura["tipo"], fatura["instituicao"]), ("cartao", "Nubank"))
        self.assertEqual(len(fatura["lancamentos"]), 5)
        parcelada = fatura["lancamentos"][2]
        self.assertEqual(parcelada["parcela"], [2, 4])
        self.assertEqual(parcelada["valor"], 250.0)

    def test_separador_virgula_e_tab(self):
        for sep in (",", "\t", "|"):
            with self.subTest(sep=sep):
                texto = sep.join(["Data", "Descrição", "Valor"]) + "\n" + sep.join(["01/09/2026", "LOJA A", "-10.50"]) + "\n" \
                        + sep.join(["02/09/2026", "LOJA B", "20.00"]) + "\n"
                (extrato,) = ler("x.csv", texto.encode("utf-8"))
                self.assertEqual([l["valor"] for l in extrato["lancamentos"]], [-10.5, 20.0])

    def test_colunas_de_credito_e_debito_com_sinal(self):
        texto = "Data;Histórico;Valor;D/C\n01/09/2026;LOJA A;10,00;D\n02/09/2026;DEPOSITO;30,00;C\n"
        (extrato,) = ler("x.csv", texto.encode("cp1252"))
        self.assertEqual([l["valor"] for l in extrato["lancamentos"]], [-10.0, 30.0])

    def test_sem_cabecalho_acha_as_colunas_pelo_conteudo(self):
        texto = "01/09/2026;MERCADO EXEMPLO;-10,00\n02/09/2026;PADARIA EXEMPLO;-5,50\n03/09/2026;PIX RECEBIDO;100,00\n"
        (extrato,) = ler("x.txt", texto.encode("utf-8"))
        self.assertEqual(len(extrato["lancamentos"]), 3)
        self.assertEqual(extrato["lancamentos"][1]["descricao"], "PADARIA EXEMPLO")

    def test_sem_colunas_reconheciveis_pede_mapeamento(self):
        texto = "a;b;c\nxx;yy;zz\nww;kk;ll\n"
        (extrato,) = ler("x.csv", texto.encode("utf-8"))
        self.assertTrue(extrato["precisaMapeamento"])

    def test_mapeamento_informado_pelo_usuario(self):
        texto = "a;b;c\n01/09/2026;LOJA A;-10,00\n02/09/2026;LOJA B;-20,00\n"
        mapeamento = {"cabecalho": 0, "papeis": {"data": [0], "descricao": [1], "valor": [2]}}
        (extrato,) = leitores.ler_arquivo("x.csv", texto.encode("utf-8"), mapeamento)
        self.assertEqual([l["valor"] for l in extrato["lancamentos"]], [-10.0, -20.0])

    def test_aviso_quando_todos_os_valores_sao_positivos(self):
        texto = "Data;Descrição;Valor\n01/09/2026;LOJA A;10,00\n02/09/2026;LOJA B;20,00\n"
        (extrato,) = ler("extrato.csv", texto.encode("utf-8"))
        self.assertTrue(extrato["avisos"])


class TestXlsx(unittest.TestCase):
    def test_extrato_com_datas_do_excel(self):
        conteudo = gerar_xlsx({"Extrato": [
            ["Banco Exemplo"],
            ["Data", "Descrição", "Valor"],
            [("data", 46270), "MERCADO BOM PRECO", -55.3],
            [("data", 46271), "PIX RECEBIDO", 100],
        ]})
        (extrato,) = ler("extrato.xlsx", conteudo)
        self.assertEqual(extrato["formato"], "XLSX")
        self.assertEqual([(l["data"], l["valor"]) for l in extrato["lancamentos"]],
                         [("2026-09-05", -55.3), ("2026-09-06", 100.0)])

    def test_planilha_de_posicao_de_investimentos(self):
        conteudo = gerar_xlsx({"Posição": [
            ["Produto", "Código de Negociação", "Quantidade", "Valor Atualizado", "Instituição"],
            ["ACAO EXEMPLO ON", "ABCD3", 100, "1.234,50", "CORRETORA EXEMPLO S.A."],
            ["FII EXEMPLO", "WXYZ11", 10, 980.0, "CORRETORA EXEMPLO S.A."],
            ["TOTAL", "", None, 2214.5, ""],
        ]})
        (extrato,) = ler("posicao_2026-10-01.xlsx", conteudo)
        self.assertEqual(extrato["tipo"], "investimentos")
        self.assertEqual(extrato["dataPosicao"], "2026-10-01")
        acao, fii = extrato["posicoes"]
        self.assertEqual((acao["codigo"], acao["quantidade"], acao["saldo"]), ("ABCD3", 100.0, 1234.5))
        self.assertEqual((acao["tipo"], acao["subtipo"]), ("EQUITY", "STOCK"))
        self.assertEqual(fii["subtipo"], "REAL_ESTATE_FUND")
        self.assertEqual(acao["instituicao"], "Corretora Exemplo")

    def test_arquivo_corrompido(self):
        with self.assertRaises(leitores.ErroLeitura):
            leitores.ler_arquivo("x.xlsx", b"PK\x03\x04 isto nao e um zip")


class TestHtml(unittest.TestCase):
    def test_xls_que_e_html(self):
        (extrato,) = ler("extrato_html.xls")
        self.assertEqual(extrato["formato"], "XLS/HTML")
        lanc = extrato["lancamentos"]
        self.assertEqual([l["valor"] for l in lanc], [1000.0, -29.9, -200.0])
        # linha só com texto continua a descrição da anterior
        self.assertEqual(lanc[0]["descricao"], "TED RECEBIDA BELTRANO FICTICIO")


class TestArquivosRecusados(unittest.TestCase):
    def test_pdf(self):
        with self.assertRaises(leitores.ErroLeitura):
            leitores.ler_arquivo("extrato.pdf", b"%PDF-1.4 ...")

    def test_xls_antigo(self):
        with self.assertRaises(leitores.ErroLeitura):
            leitores.ler_arquivo("extrato.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)

    def test_vazio(self):
        with self.assertRaises(leitores.ErroLeitura):
            leitores.ler_arquivo("vazio.csv", b"")


class TestTipoDeInvestimento(unittest.TestCase):
    def test_classificacao_pelo_nome(self):
        casos = {
            "Tesouro IPCA+ 2035": ("FIXED_INCOME", "TREASURY"), "CDB BANCO EXEMPLO": ("FIXED_INCOME", "CDB"),
            "LCI EXEMPLO": ("FIXED_INCOME", "LCI"), "FII EXEMPLO": ("MUTUAL_FUND", "REAL_ESTATE_FUND"),
            "ETF EXEMPLO": ("ETF", "ETF"), "BDR EXEMPLO": ("EQUITY", "BDR"), "ABCD3": ("EQUITY", "STOCK"),
            "Ações EUA": ("EQUITY", "FOREIGN_STOCK"), "Bitcoin": ("OTHER", "CRYPTO"), "???": ("OTHER", None),
        }
        for nome, esperado in casos.items():
            with self.subTest(nome=nome):
                self.assertEqual(leitores.tipo_investimento(nome), esperado)


if __name__ == "__main__":
    unittest.main()
