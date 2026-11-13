"""Rentabilidade da carteira (openbalance/carteira.py e openbalance/historico.py): índices mensais, custo médio e cotas (TWR).

As séries de preço são pequenas e montadas aqui; nada é baixado.
"""

import json
import unittest
from datetime import date

from openbalance import carteira, historico
from tests.ajudantes import TesteComBanco


class TestIndiceMensal(unittest.TestCase):
    def setUp(self):
        self.cdi = carteira.Indice({"2026-01": 1.0, "2026-02": 1.0, "2026-03": 2.0}, "2026-06-15")

    def test_meses_inteiros(self):
        self.assertAlmostEqual(self.cdi.fator("2026-01-01", "2026-03-01"), 1.01 ** 2)

    def test_mes_parcial_e_pro_rata(self):
        self.assertAlmostEqual(self.cdi.fator("2026-01-16", "2026-02-01"), 1.01 ** (16 / 31))

    def test_mes_nao_publicado_para_a_conta(self):
        self.assertAlmostEqual(self.cdi.fator("2026-03-01", "2026-06-01"), 1.02)

    def test_acumulado_12_meses(self):
        pct, inicio, fim = self.cdi.acumulado_12m()
        self.assertAlmostEqual(pct, (1.01 * 1.01 * 1.02 - 1) * 100)
        self.assertEqual((inicio, fim), ("2026-01", "2026-03"))

    def test_sem_dados(self):
        vazio = carteira.Indice({}, "2026-06-15")
        self.assertFalse(vazio)
        self.assertEqual(vazio.acumulado_12m(), (None, None, None))


class TestCustoMedioDaCarteira(unittest.TestCase):
    def test_compras_e_vendas(self):
        movs = [{"type": "BUY", "date": "2026-01-10", "quantity": 10, "amount": 100},
                {"type": "BUY", "date": "2026-02-10", "quantity": 10, "amount": 200},
                {"type": "SELL", "date": "2026-03-10", "quantity": 5, "amount": 90}]
        r = carteira._custo_medio(movs, 15)
        self.assertAlmostEqual(r["custo"], 225)  # 300 − 5 × 15
        self.assertTrue(r["completo"])
        self.assertEqual(r["fluxos"], [("2026-01-10", 100), ("2026-02-10", 200), ("2026-03-10", -90)])

    def test_movimentacoes_que_nao_explicam_a_posicao(self):
        movs = [{"type": "BUY", "date": "2026-01-10", "quantity": 10, "amount": 100}]
        self.assertFalse(carteira._custo_medio(movs, 30)["completo"])

    def test_quantidade_num_dia_passado(self):
        movs = [{"type": "BUY", "date": "2026-02-10", "quantity": 10}, {"type": "SELL", "date": "2026-03-10", "quantity": 4}]
        self.assertEqual(carteira._quantidade_no_dia(26, movs, "2026-01-31"), 20)
        self.assertEqual(carteira._quantidade_no_dia(26, movs, "2026-02-28"), 30)
        self.assertEqual(carteira._quantidade_no_dia(26, movs, "2026-03-31"), 26)

    def test_comparar_com_o_indice(self):
        cdi = carteira.Indice({"2026-01": 1.0, "2026-02": 1.0}, "2026-03-01")
        r = carteira._comparar([("2026-01-01", 1_000)], 1_030, [], cdi, "2026-03-01")
        self.assertAlmostEqual(r["ganhoIndice"], 1_000 * (1.01 ** 2 - 1))
        self.assertAlmostEqual(r["ganhoReal"], 30)
        self.assertAlmostEqual(r["pct"], 30 / (1_000 * (1.01 ** 2 - 1)) * 100)

    def test_meses(self):
        self.assertEqual(carteira._somar_meses("2026-11", 2), "2027-01")
        self.assertEqual(carteira._somar_meses_data("2026-01-31", 1), "2026-02-28")


def serie(valores):
    return {"valor": [q * p for q, p in zip(*valores)], "qtd": valores[0], "preco": valores[1], "indice": valores[1]}


class TestCotas(unittest.TestCase):
    """historico._agregar: aportes e resgates mudam o valor, mas não a cota."""

    def test_aporte_nao_conta_como_ganho(self):
        a = serie(([1, 1, 1], [100, 110, 110]))
        b = serie(([0, 0, 10], [100, 100, 100]))  # aporte de 1.000 no 3º dia
        r = historico._agregar([a, b], 3)
        self.assertEqual(r["cota"], [1.0, 1.1, 1.1])
        self.assertEqual(r["valor"], [100, 110, 1110])
        self.assertEqual(r["fluxo"], [0, 0, 1000])
        self.assertEqual(r["ganho"], [0, 10, 0])

    def test_resgate_nao_conta_como_perda(self):
        a = serie(([10, 10, 5], [100, 100, 100]))
        r = historico._agregar([a], 3)
        self.assertEqual(r["cota"], [1.0, 1.0, 1.0])
        self.assertEqual(r["fluxo"], [0, 0, -500])

    def test_retorno_ponderado_pelo_valor_da_vespera(self):
        a = serie(([1, 1], [300, 330]))  # +10%
        b = serie(([1, 1], [100, 90]))   # −10%
        r = historico._agregar([a, b], 2)
        self.assertAlmostEqual(r["cota"][1], 1 + (30 - 10) / 400)

    def test_indice_ajustado_inclui_proventos(self):
        a = {"qtd": [10, 10], "preco": [10, 10], "valor": [100, 100], "indice": [10, 10.5]}  # 5% de dividendos
        r = historico._agregar([a], 2)
        self.assertAlmostEqual(r["cota"][1], 1.05)
        self.assertEqual(r["ganho"][1], 5)


class TestSeriesDiarias(unittest.TestCase):
    def test_repete_o_ultimo_valor_nos_dias_sem_cotacao(self):
        pontos = [("2026-10-02", 10), ("2026-10-05", 11)]
        datas = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05", "2026-10-06"]
        self.assertEqual(historico._no_calendario(pontos, datas), [None, 10, 10, 11, 11])

    def test_normalizar(self):
        self.assertEqual(historico._normalizar([None, 0, 50, 100]), [None, None, 1.0, 2.0])

    def test_quantidades_por_dia(self):
        p = {"qAntes": 5, "inicio": "2026-10-02",
             "eventos": [("2026-10-05", 10, {}), ("2026-10-07", -3, {})]}
        datas = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
        self.assertEqual(historico._quantidades(p, datas), [0.0, 5, 15, 15, 12])

    def test_calendario_de_dias_uteis(self):
        cdi = [("2026-10-01", 0.05), ("2026-10-02", 0.05)]
        dias = historico._calendario(cdi, {}, {}, "2026-10-01", "2026-10-06")
        self.assertEqual([d[0] for d in dias], ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
        # depois do último CDI publicado, repete a última taxa
        self.assertEqual([d[1] for d in dias], [0.05] * 4)
        self.assertEqual([d[2] for d in dias], [1.0] * 4)

    def test_curva_de_cdb_100_por_cento_do_cdi(self):
        dias = [["2026-10-01", 0.05, 1.0], ["2026-10-02", 0.05, 1.0], ["2026-10-05", 0.05, 1.0]]
        curva = historico._curva({"rateType": "CDI", "rate": 100}, dias)
        self.assertAlmostEqual(curva[-1], 1.0005 ** 2)
        curva_120 = historico._curva({"rateType": "CDI", "rate": 120}, dias)
        self.assertAlmostEqual(curva_120[-1], 1.0006 ** 2)

    def test_curva_prefixada(self):
        dias = [["2026-10-01", 0.05, 1.0]] * 253
        curva = historico._curva({"fixedAnnualRate": 10}, dias)
        self.assertAlmostEqual(curva[-1], 1.10)


class TestHistoricoCompleto(TesteComBanco):
    """historico.montar com uma ação comprada em duas vezes e a cotação guardada no banco."""

    PRECOS = {"2026-10-01": 10, "2026-10-02": 10.5, "2026-10-05": 10.5, "2026-10-06": 11, "2026-10-07": 11,
              "2026-10-08": 11.5, "2026-10-09": 12}

    def setUp(self):
        super().setUp()
        c = self.conexao
        historico.garantir_tabelas(c)
        carteira.garantir_tabelas(c)
        c.execute("INSERT INTO itens (id, instituicao, status, atualizado_em, bruto, origem) "
                  "VALUES ('imp-corretora', 'Corretora Exemplo', 'IMPORTADO', '2026-10-09', '{}', 'importacao')")
        acao = {"id": "imp-abcd", "itemId": "imp-corretora", "name": "ABCD3", "code": "ABCD3", "type": "EQUITY",
                "subtype": "STOCK", "quantity": 20, "value": 12, "amount": 240, "balance": 240, "status": "ACTIVE",
                "date": "2026-10-09"}
        c.execute("INSERT INTO investimentos (id, item_id, saldo, bruto) VALUES (?, ?, ?, ?)",
                  (acao["id"], "imp-corretora", 240, json.dumps(acao)))
        for k, (dia, q, valor) in enumerate([("2026-10-01", 10, 100), ("2026-10-06", 10, 110)]):
            m = {"type": "BUY", "date": dia, "quantity": q, "amount": valor, "value": valor / q}
            c.execute("INSERT INTO movimentos_investimento VALUES (?, ?, ?, ?, ?, ?)",
                      (f"m{k}", "imp-abcd", "imp-corretora", "ABCD3", dia, json.dumps(m)))
        for dia, preco in self.PRECOS.items():
            for serie_ in ("yahoo:ABCD3.SA", "yahoo_aj:ABCD3.SA"):
                c.execute("INSERT INTO series_diarias VALUES (?, ?, ?)", (serie_, dia, preco))
        c.commit()

    def test_cota_mede_so_a_variacao_do_preco(self):
        r = historico.montar(self.conexao, date(2026, 10, 9))
        self.assertEqual(r["datas"], list(self.PRECOS))
        cart = r["carteira"]
        self.assertEqual(cart["valor"], [100, 105, 105, 220, 220, 230, 240])
        self.assertEqual(cart["fluxo"], [0, 0, 0, 110, 0, 0, 0])
        # de 10 para 12: +20%, apesar de o valor ter ido de 100 para 240 com o aporte
        self.assertAlmostEqual(cart["cota"][-1], 1.2)
        self.assertEqual(r["confiavelDesde"], "2026-10-01")
        self.assertEqual(r["semPreco"], [])

    def test_sem_posicoes(self):
        self.conexao.execute("DELETE FROM investimentos")
        self.assertEqual(historico.montar(self.conexao, date(2026, 10, 9)), {"vazio": True})


if __name__ == "__main__":
    unittest.main()
