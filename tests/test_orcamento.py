"""Orçamento mensal (openbalance/orcamento.py): sugestão pela mediana e gravação dos limites."""

from datetime import date

from openbalance import orcamento
from tests.ajudantes import TesteComBanco

CATEGORIAS = {
    "05000000": {"nome": "Compras", "grupo": "05000000"},
    "05010000": {"nome": "Eletrônicos", "grupo": "05000000"},
    "08000000": {"nome": "Lazer", "grupo": "08000000"},
}


def tx(data, valor, categoria="05010000", natureza="despesa", entrada=False, oculto=False):
    return {"data": data, "valor": valor, "categoriaId": categoria, "natureza": natureza, "entrada": entrada,
            "oculto": oculto}


class TestSugestoes(TesteComBanco):
    def test_mediana_dos_meses_fechados(self):
        transacoes = [
            tx("2026-05-02", 999),  # maio fica de fora: só os últimos 6 meses fechados (jun–nov)
            tx("2026-06-03", 100), tx("2026-07-03", 200), tx("2026-08-03", 300),
            tx("2026-09-03", 400), tx("2026-10-03", 500), tx("2026-11-03", 600),
            tx("2026-11-04", 50, entrada=True),  # estorno abate
            tx("2026-11-05", 5000, natureza="investimento"),  # não é gasto
            tx("2026-11-06", 5000, oculto=True),
            tx("2026-12-10", 10_000),  # mês corrente não entra
            tx("2026-10-10", 80, categoria="08000000"),
        ]
        sugestoes, meses = orcamento.sugestoes(transacoes, CATEGORIAS, date(2026, 12, 15))
        self.assertEqual(meses, ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"])
        self.assertEqual(sugestoes["05010000"], 350)  # mediana de 100, 200, 300, 400, 500, 550
        self.assertEqual(sugestoes["05000000"], 350)  # o grupo soma as subcategorias
        self.assertNotIn("08000000", sugestoes)  # gasto em 1 de 6 meses: mediana zero, sem sugestão

    def test_primeiro_mes_incompleto_nao_conta(self):
        transacoes = [tx("2026-09-20", 900), tx("2026-10-03", 100), tx("2026-11-03", 300)]
        _, meses = orcamento.sugestoes(transacoes, CATEGORIAS, date(2026, 12, 1))
        self.assertEqual(meses, ["2026-10", "2026-11"])


class TestSalvar(TesteComBanco):
    def test_grava_altera_e_remove(self):
        orcamento.salvar(self.conexao, {"limites": {"05000000": 1500, "08000000": "300.5"}})
        self.assertEqual(orcamento.carregar(self.conexao), {"05000000": 1500, "08000000": 300.5})
        orcamento.salvar(self.conexao, {"limites": {"05000000": None, "08000000": 400}})
        self.assertEqual(orcamento.carregar(self.conexao), {"08000000": 400})

    def test_valores_invalidos(self):
        with self.assertRaises(ValueError):
            orcamento.salvar(self.conexao, {"limites": {"05000000": -10}})
        with self.assertRaises(ValueError):
            orcamento.salvar(self.conexao, {"limites": "1000"})
        self.assertEqual(orcamento.carregar(self.conexao), {})
