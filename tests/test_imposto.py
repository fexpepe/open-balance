"""Imposto de renda dos investimentos (openbalance/imposto.py): apuração mensal da renda variável e custo médio.

Os ativos são montados aqui mesmo, no formato que _ativos() entrega a apurar() e _calcular().
"""

import unittest

from openbalance import imposto

HOJE = "2026-12-15"


def ativo(categoria, ticker, vendas, compras=()):
    """Ativo já calculado: vendas = [(data, valor, resultado)], compras = [data] (para o aviso de day trade)."""
    return {"categoria": categoria, "ticker": ticker, "codigo": ticker,
            "vendas": [{"data": d, "quantidade": 1, "valor": v, "custoValor": v - r, "resultado": r} for d, v, r in vendas],
            "_movimentos": [{"type": "BUY", "date": d} for d in compras]}


def apurar(*ativos, prejuizo=None):
    meses = imposto.apurar(list(ativos), prejuizo or {}, HOJE)
    return {m["mes"]: m for m in meses}


class TestIsencao(unittest.TestCase):
    def test_acoes_ate_20_mil_no_mes_sao_isentas(self):
        m = apurar(ativo("acao", "ABCD3", [("2026-03-10", 18_000, 3_000)]))["2026-03"]
        self.assertTrue(m["isento"])
        self.assertEqual(m["ganhoIsento"], 3_000)
        self.assertEqual((m["imposto"], m["darf"]), (0, 0))

    def test_acoes_acima_de_20_mil_pagam_15_por_cento(self):
        m = apurar(ativo("acao", "ABCD3", [("2026-03-10", 25_000, 2_000)]))["2026-03"]
        self.assertFalse(m["isento"])
        self.assertEqual(m["impostoComum"], 300.0)
        # dedo-duro: 0,005% de 25.000 = 1,25, descontado do DARF
        self.assertEqual(m["irrf"], 1.25)
        self.assertEqual(m["darf"], 298.75)
        self.assertEqual(m["codigo"], "6015")
        self.assertEqual(m["vencimento"], "2026-04-30")

    def test_fii_paga_20_por_cento_mesmo_abaixo_de_20_mil(self):
        m = apurar(ativo("fii", "WXYZ11", [("2026-03-10", 5_000, 1_000)]))["2026-03"]
        self.assertEqual(m["impostoFii"], 200.0)
        self.assertEqual(m["impostoComum"], 0.0)
        self.assertEqual(m["darf"], 200.0)

    def test_etf_e_bdr_nao_tem_isencao(self):
        for categoria, tk in (("etf", "ETFX11"), ("bdr", "ABCD34")):
            with self.subTest(categoria=categoria):
                m = apurar(ativo(categoria, tk, [("2026-03-10", 5_000, 1_000)]))["2026-03"]
                self.assertEqual(m["impostoComum"], 150.0)
                self.assertEqual(m["ganhoIsento"], 0.0)

    def test_vendas_de_etf_nao_contam_no_limite_das_acoes(self):
        meses = apurar(ativo("acao", "ABCD3", [("2026-03-10", 15_000, 1_000)]),
                       ativo("etf", "ETFX11", [("2026-03-11", 10_000, 500)]))
        m = meses["2026-03"]
        self.assertTrue(m["isento"])
        self.assertEqual(m["vendasAcoes"], 15_000)
        self.assertEqual(m["ganhoIsento"], 1_000)
        self.assertEqual(m["impostoComum"], 75.0)


class TestPrejuizo(unittest.TestCase):
    def test_prejuizo_compensa_ganho_de_mes_seguinte(self):
        meses = apurar(ativo("acao", "ABCD3", [("2026-03-10", 30_000, -2_000), ("2026-05-10", 30_000, 3_000)]))
        self.assertEqual(meses["2026-03"]["prejuizoComum"], 2_000)
        self.assertEqual(meses["2026-04"]["prejuizoComum"], 2_000)  # mês sem venda mantém o saldo
        maio = meses["2026-05"]
        self.assertEqual((maio["compensadoComum"], maio["baseComum"], maio["impostoComum"]), (2_000, 1_000, 150.0))
        self.assertEqual(maio["prejuizoComum"], 0)

    def test_prejuizo_de_mes_isento_tambem_compensa(self):
        meses = apurar(ativo("acao", "ABCD3", [("2026-03-10", 10_000, -500), ("2026-04-10", 30_000, 1_000)]))
        self.assertTrue(meses["2026-03"]["isento"])
        self.assertEqual(meses["2026-03"]["prejuizoComum"], 500)
        self.assertEqual(meses["2026-04"]["baseComum"], 500)

    def test_prejuizo_de_fii_nao_compensa_acoes(self):
        meses = apurar(ativo("fii", "WXYZ11", [("2026-03-10", 5_000, -1_000)]),
                       ativo("acao", "ABCD3", [("2026-04-10", 30_000, 1_000)]))
        abril = meses["2026-04"]
        self.assertEqual(abril["impostoComum"], 150.0)
        self.assertEqual(abril["prejuizoFii"], 1_000)

    def test_prejuizo_da_declaracao_anterior(self):
        m = apurar(ativo("acao", "ABCD3", [("2026-03-10", 30_000, 1_000)]), prejuizo={"comum": 400})["2026-03"]
        self.assertEqual((m["compensadoComum"], m["baseComum"]), (400, 600))


class TestDarf(unittest.TestCase):
    def test_darf_abaixo_de_10_reais_acumula(self):
        meses = apurar(ativo("fii", "WXYZ11", [("2026-03-10", 1_000, 40), ("2026-04-10", 1_000, 20)]))
        marco, abril = meses["2026-03"], meses["2026-04"]
        self.assertEqual((marco["imposto"], marco["darf"], marco["acumulado"]), (8.0, 0.0, 8.0))
        self.assertEqual((abril["acumuladoAnterior"], abril["darf"], abril["acumulado"]), (8.0, 12.0, 0.0))

    def test_situacao_do_darf(self):
        meses = apurar(ativo("fii", "WXYZ11", [("2026-03-10", 5_000, 1_000), ("2026-11-10", 5_000, 1_000)]))
        self.assertEqual(meses["2026-03"]["situacao"], "vencido")
        self.assertEqual(meses["2026-11"]["situacao"], "a pagar")
        self.assertTrue(meses["2026-12"]["emAndamento"])

    def test_aviso_de_day_trade_e_venda_sem_custo(self):
        sem_custo = ativo("acao", "EFGH3", [("2026-03-11", 30_000, 0)])
        sem_custo["vendas"][0]["resultado"] = None
        m = apurar(ativo("acao", "ABCD3", [("2026-03-10", 1_000, 10)], compras=["2026-03-10"]), sem_custo)["2026-03"]
        self.assertTrue(m["incompleto"])
        self.assertEqual(len(m["avisos"]), 2)

    def test_ativo_fora_da_apuracao(self):
        self.assertEqual(imposto.apurar([ativo("fora", "XPTO", [("2026-03-10", 50_000, 9_000)])], {}, HOJE), [])

    def test_ultimo_dia_util(self):
        self.assertEqual(imposto.ultimo_dia_util("2026-08"), "2026-08-31")
        self.assertEqual(imposto.ultimo_dia_util("2026-10"), "2026-10-30")  # 31 é sábado
        self.assertEqual(imposto.ultimo_dia_util("2026-12"), "2026-12-30")  # 31/12 sem expediente bancário


class TestCategoriaFiscal(unittest.TestCase):
    def test_categorias(self):
        casos = [
            ({}, "fiis", "WXYZ11", "fii"),
            ({"subtype": "STOCK"}, "acoes", "ABCD3", "acao"),
            ({"subtype": "ETF"}, "acoes", "ETFX11", "etf"),
            ({"subtype": "STOCK"}, "acoes", "ABCD34", "bdr"),
            ({"subtype": "BDR"}, "acoes_exterior", "ABCD34", "bdr"),
            ({"subtype": "CDB"}, "renda_fixa", None, "fora"),
        ]
        for i, classe, tk, esperado in casos:
            with self.subTest(tk=tk, classe=classe):
                self.assertEqual(imposto.categoria_fiscal(i, classe, tk, None)[0], esperado)

    def test_fundo_de_infraestrutura_listado(self):
        i = {"subtype": "STOCK", "isin": "BRABCDCTF000", "name": "FUNDO INCENTIVADO INFRA EXEMPLO"}
        self.assertEqual(imposto.categoria_fiscal(i, "acoes", "ABCD11", None), ("isento", True))


def movimento(tipo, dia, quantidade, valor):
    return {"type": tipo, "date": dia, "quantity": quantidade, "amount": valor}


def para_calcular(movimentos, quantidade, manual=None, aplicado=None, subtipo="STOCK"):
    return {"codigo": "ABCD3", "ticker": "ABCD3", "nome": "ACAO EXEMPLO", "nomeB3": None, "classe": "acoes",
            "subtipo": subtipo, "categoria": "acao", "categoriaAuto": "acao", "categoriaIncerta": False,
            "quantidade": quantidade, "semQuantidade": False, "movimentos": movimentos, "instituicoes": {"Corretora"},
            "importada": False, "dataPosicao": None, "compra": None, "_bruto": {}, "aplicado": aplicado,
            "manual": manual, "inicioJanela": None}


class TestCustoMedio(unittest.TestCase):
    def test_venda_pelo_custo_medio(self):
        movs = [movimento("BUY", "2026-01-10", 100, 1_000), movimento("BUY", "2026-02-10", 100, 1_200),
                movimento("SELL", "2026-03-10", 50, 700)]
        a = imposto._calcular(para_calcular(movs, 150), HOJE)
        (venda,) = a["vendas"]
        self.assertAlmostEqual(venda["custoValor"], 550)  # 50 × 11,00
        self.assertEqual(venda["resultado"], 150)
        self.assertEqual(a["custo"], 1_650)
        self.assertAlmostEqual(a["precoMedio"], 11.0)
        self.assertEqual(a["origemCusto"], "movimentações")
        self.assertFalse(a["precisaCusto"])

    def test_zerar_a_posicao_recomeca_o_custo(self):
        movs = [movimento("BUY", "2026-01-10", 10, 100), movimento("SELL", "2026-02-10", 10, 150),
                movimento("BUY", "2026-03-10", 10, 200)]
        a = imposto._calcular(para_calcular(movs, 10), HOJE)
        self.assertEqual(a["vendas"][0]["resultado"], 50)
        self.assertEqual(a["custo"], 200)

    def test_lote_anterior_sem_custo_pede_o_custo(self):
        # 100 ações hoje, mas as movimentações só mostram a venda de 50: havia 150 antes delas
        movs = [movimento("SELL", "2026-03-10", 50, 700)]
        a = imposto._calcular(para_calcular(movs, 100), HOJE)
        self.assertEqual(a["quantidadeInicial"], 150)
        self.assertTrue(a["precisaCusto"])
        self.assertIsNone(a["vendas"][0]["resultado"])

    def test_custo_informado_pelo_usuario(self):
        movs = [movimento("SELL", "2026-03-10", 50, 700)]
        a = imposto._calcular(para_calcular(movs, 100, manual={"data": "2026-01-01", "custo": 1_500}), HOJE)
        self.assertEqual(a["origemCusto"], "informado")
        self.assertEqual(a["vendas"][0]["resultado"], 200)  # custo 50 × 10,00
        self.assertEqual(a["custo"], 1_000)

    def test_valor_aplicado_informado_pelo_banco(self):
        a = imposto._calcular(para_calcular([], 100, aplicado=1_234.0), HOJE)
        self.assertEqual((a["origemCusto"], a["custo"]), ("banco", 1_234.0))

    def test_venda_maior_que_as_compras_supoe_lote_anterior_sem_custo(self):
        movs = [movimento("BUY", "2026-01-10", 10, 100), movimento("SELL", "2026-02-10", 20, 300)]
        a = imposto._calcular(para_calcular(movs, 0), HOJE)
        self.assertEqual(a["quantidadeInicial"], 10)
        self.assertIsNone(a["vendas"][0]["resultado"])
        self.assertTrue(a["precisaCusto"])


if __name__ == "__main__":
    unittest.main()
