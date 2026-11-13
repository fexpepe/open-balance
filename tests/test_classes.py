"""Classe de cada investimento na carteira (carteira.classe_investimento, carteira.fundo_listado) e a categoria
para o IR (imposto.categoria_fiscal). Tickers e ISINs inventados, no formato da B3.

Regras: ETF tem classe própria; cota listada de fundo (ISIN com 'CTF') sem sinal de ETF e que a B3 diz não ser
FII ('outro') é fundo de infraestrutura — fica junto dos FIIs na carteira, mas é isenta no imposto.
"""

import json
import unittest

from openbalance import carteira, imposto
from tests.ajudantes import TesteComBanco

ISIN_COTA = "BRWXYZCTF001"  # 'CTF' nas posições 7 a 9: cota de fundo


def acao_do_banco(ticker, **extra):
    """Como o banco manda ETFs e fundos listados: como se fossem ação."""
    return {"id": f"inv-{ticker}", "code": ticker, "name": ticker, "type": "EQUITY", "subtype": "STOCK", **extra}


class TestFundoListado(unittest.TestCase):
    def test_etf_pelo_subtipo_ou_pelo_nome(self):
        self.assertEqual(carteira.fundo_listado({"code": "ETFA11", "subtype": "ETF"}), "etf")
        self.assertEqual(carteira.fundo_listado(acao_do_banco("ETFA11", name="ETFA11 FUNDO DE ÍNDICE EXEMPLO")), "etf")
        self.assertEqual(carteira.fundo_listado(acao_do_banco("ETFA11", _b3="outro", _b3_nome="ISHARES EXEMPLO")), "etf")

    def test_infra_quando_a_b3_diz_que_nao_e_fii(self):
        self.assertEqual(carteira.fundo_listado(acao_do_banco("WXYZ11", isin=ISIN_COTA, _b3="outro")), "infra")

    def test_cota_sem_resposta_da_b3_fica_indefinida(self):
        self.assertIsNone(carteira.fundo_listado(acao_do_banco("WXYZ11", isin=ISIN_COTA)))

    def test_fii_e_acao_nao_sao_fundo_listado(self):
        self.assertIsNone(carteira.fundo_listado(acao_do_banco("WXYZ11", isin=ISIN_COTA, _b3="fii")))
        self.assertIsNone(carteira.fundo_listado({"code": "WXYZ11", "subtype": "REAL_ESTATE_FUND"}))
        self.assertIsNone(carteira.fundo_listado(acao_do_banco("ABCD3", isin="BRABCDACNOR0", _b3="outro")))


class TestClasseNaCarteira(unittest.TestCase):
    def test_classes(self):
        casos = [
            (acao_do_banco("ABCD3"), "acoes"),
            (acao_do_banco("ETFA11", name="ETFA11 ETF EXEMPLO"), "etf"),
            (acao_do_banco("WXYZ11", isin=ISIN_COTA, _b3="outro"), "fiis"),  # infra junto dos FIIs
            (acao_do_banco("HIJK11", _b3="fii"), "fiis"),
            (acao_do_banco("HIJK11", name="FII HIJK EXEMPLO"), "fiis"),
            ({"code": "ABCD34", "subtype": "BDR"}, "acoes_exterior"),
            ({"name": "Tesouro Selic 2031", "subtype": "TREASURY"}, "tesouro"),
            ({"name": "CDB Banco Exemplo", "type": "FIXED_INCOME", "subtype": "CDB"}, "renda_fixa"),
            ({"name": "Fundo Exemplo", "type": "MUTUAL_FUND", "subtype": "MULTIMARKET_FUND"}, "fundos"),
            ({"name": "Bitcoin", "type": "OTHER", "subtype": "CRYPTO"}, "cripto"),
        ]
        for i, esperado in casos:
            with self.subTest(i=i):
                self.assertEqual(carteira.classe_investimento(i), esperado)

    def test_etf_e_negociado_em_bolsa(self):
        self.assertIn("etf", carteira.BOLSA)
        self.assertIn("etf", carteira.CLASSES)


class TestCategoriaNoImposto(unittest.TestCase):
    def categoria(self, i):
        return imposto.categoria_fiscal(i, carteira.classe_investimento(i), carteira.ticker(i), None)

    def test_infra_listado_e_isento_mesmo_na_classe_dos_fiis(self):
        self.assertEqual(self.categoria(acao_do_banco("WXYZ11", isin=ISIN_COTA, _b3="outro")), ("isento", True))

    def test_etf_sem_isencao(self):
        self.assertEqual(self.categoria(acao_do_banco("ETFA11", name="ETFA11 ETF EXEMPLO")), ("etf", False))

    def test_fii_e_acao(self):
        self.assertEqual(self.categoria(acao_do_banco("HIJK11", _b3="fii")), ("fii", False))
        self.assertEqual(self.categoria(acao_do_banco("ABCD3")), ("acao", False))


class TestClasseComDadosDaB3(TesteComBanco):
    """_brutas acrescenta o tipo e o nome de pregão que a B3 informou (tabela ativos_b3) antes de decidir a classe."""

    def test_infra_e_etf_pelo_que_a_b3_respondeu(self):
        c = self.conexao
        carteira.garantir_tabelas(c)
        carteira.b3.garantir_tabelas(c)
        c.execute("INSERT INTO itens (id, instituicao, status, atualizado_em, bruto, origem) "
                  "VALUES ('imp-corretora', 'Corretora Exemplo', 'IMPORTADO', '2026-10-09', '{}', 'importacao')")
        posicoes = [acao_do_banco("WXYZ11", isin=ISIN_COTA), acao_do_banco("ETFA11"), acao_do_banco("ABCD3")]
        for i in posicoes:
            c.execute("INSERT INTO investimentos (id, item_id, saldo, bruto) VALUES (?, 'imp-corretora', 100, ?)",
                      (i["id"], json.dumps(i)))
        c.executemany("INSERT INTO ativos_b3 (emissor, nome, tipo, atualizado_em) VALUES (?, ?, ?, '2026-10-09')",
                      [("WXYZ", "FUNDO WXYZ INFRA", "outro"), ("ETFA", "ISHARES EXEMPLO", "outro"),
                       ("ABCD", "ABCD EXEMPLO SA", "outro")])
        itens = {"imp-corretora": {"instituicao": "Corretora Exemplo", "origem": "importacao"}}
        classes = {i["code"]: carteira.classe_investimento(i) for _, i in carteira._brutas(c, itens)}
        self.assertEqual(classes, {"WXYZ11": "fiis", "ETFA11": "etf", "ABCD3": "acoes"})


if __name__ == "__main__":
    unittest.main()
