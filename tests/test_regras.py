"""Natureza e categoria das transações (openbalance/regras.py e openbalance/categorizar.py)."""

import json
import unittest

from openbalance import categorizar, regras
from tests.ajudantes import TesteComBanco

CONTA = {"type": "BANK"}
CARTAO = {"type": "CREDIT"}


def tx(descricao, tipo="DEBIT", categoria=None, pagamento=None):
    return {"description": descricao, "type": tipo, "categoryId": categoria, "paymentData": pagamento}


class TestTexto(unittest.TestCase):
    def test_normalizar_e_digitos(self):
        self.assertEqual(regras.normalizar("Pão de Açúcar"), "PAO DE ACUCAR")
        self.assertEqual(regras.so_digitos("123.456.789-00"), "12345678900")
        self.assertEqual(regras.so_digitos({"value": "12-3"}), "123")
        self.assertEqual(regras.so_digitos(None), "")

    def test_limpar_descricao_tira_a_parcela(self):
        self.assertEqual(regras.limpar_descricao("LOJA  EXEMPLO 02/05"), "LOJA EXEMPLO")

    def test_chave_do_estabelecimento(self):
        self.assertEqual(regras.chave_estabelecimento("PADARIA*EXEMPLO 123"), regras.chave_estabelecimento("Padaria Exemplo 456"))
        self.assertEqual(regras.chave_estabelecimento("NETFLIX.COM", "Netflix"), "NETFLIX")
        # a linha de IOF de compra internacional cai no mesmo serviço
        self.assertEqual(regras.chave_estabelecimento("IOF INTERNACIONAL - LOJA EXEMPLO"),
                         regras.chave_estabelecimento("LOJA EXEMPLO"))

    def test_marca(self):
        self.assertEqual(regras.marca("PG *SPOTIFY BR"), "Spotify")
        self.assertIsNone(regras.marca("PADARIA EXEMPLO"))

    def test_nome_da_contraparte(self):
        self.assertEqual(regras.nome_contraparte("Pix enviado FULANO DE TAL"), "Fulano De Tal")
        self.assertEqual(regras.nome_contraparte("TED RECEBIDA | Ciclano Exemplo"), "Ciclano Exemplo")

    def test_regra_do_usuario_casa_sem_acento_e_caixa(self):
        self.assertTrue(regras.regra_casa("padaria são", "PADARIA SAO JOAO"))
        self.assertFalse(regras.regra_casa("mercado", "PADARIA SAO JOAO"))

    def test_instituicao_pelo_codigo_ou_nome(self):
        self.assertEqual(regras.nome_instituicao([{"bankData": {"transferNumber": "341/0001/12345-6"}}]), "Itaú")
        self.assertEqual(regras.nome_instituicao([{"name": "Conta Banco Inter"}]), "Inter")
        self.assertIsNone(regras.nome_instituicao([{"name": "Conta"}]))


class TestNatureza(unittest.TestCase):
    def test_despesa_e_receita(self):
        self.assertEqual(regras.classificar(tx("PADARIA EXEMPLO", categoria="11010000"), CONTA), (regras.DESPESA, "11010000"))
        self.assertEqual(regras.classificar(tx("PIX RECEBIDO CLIENTE", "CREDIT", "05070000"), CONTA)[0], regras.RECEITA)

    def test_pagamento_da_fatura_na_conta(self):
        self.assertEqual(regras.classificar(tx("PAGTO FATURA CARTAO"), CONTA), (regras.FATURA, regras.CAT_PAGAMENTO_CARTAO))

    def test_no_cartao(self):
        self.assertEqual(regras.classificar(tx("Pagamento recebido", "CREDIT"), CARTAO)[0], regras.FATURA)
        # estorno no cartão continua despesa (negativa)
        self.assertEqual(regras.classificar(tx("ESTORNO LOJA", "CREDIT", "08010000"), CARTAO), (regras.DESPESA, "08010000"))
        self.assertEqual(regras.classificar(tx("TESOURO DIRETO"), CARTAO)[0], regras.DESPESA)

    def test_investimentos_e_rendimentos(self):
        self.assertEqual(regras.classificar(tx("APLICACAO CDB"), CONTA)[0], regras.INVESTIMENTO)
        self.assertEqual(regras.classificar(tx("RESGATE CDB", "CREDIT"), CONTA)[0], regras.INVESTIMENTO)
        self.assertEqual(regras.classificar(tx("DIVIDENDOS ABCD3", "CREDIT"), CONTA), (regras.RENDIMENTO, regras.CAT_RENDIMENTOS))
        self.assertEqual(regras.classificar(tx("REND PAGO APLIC AUT", "CREDIT", regras.CAT_RENDIMENTOS), CONTA)[0], regras.RENDIMENTO)

    def test_salario_corrige_a_categoria(self):
        self.assertEqual(regras.classificar(tx("SALARIO EMPRESA", "CREDIT", "05070000"), CONTA), (regras.RECEITA, regras.CAT_SALARIO))

    def test_transferencia_entre_contas_proprias(self):
        self.assertEqual(regras.classificar(tx("TRANSF", categoria="04000000"), CONTA)[0], regras.PROPRIA)
        pela_conta = tx("PIX ENVIADO", pagamento={"receiver": {"documentNumber": "111.222.333-44"}})
        self.assertEqual(regras.classificar(pela_conta, CONTA, cpf_titular="11122233344"),
                         (regras.PROPRIA, regras.CAT_MESMA_TITULARIDADE))
        self.assertEqual(regras.classificar(pela_conta, CONTA, cpf_titular="99999999999")[0], regras.DESPESA)

    def test_transferencia_propria_pelo_nome(self):
        nome = "Fulana de Tal Exemplo"
        self.assertTrue(regras.eh_mesmo_titular_por_nome(tx("Pix enviado FULANA EXEMPLO"), nome))
        self.assertFalse(regras.eh_mesmo_titular_por_nome(tx("Pix enviado FULANA SOUZA"), nome))
        self.assertFalse(regras.eh_mesmo_titular_por_nome(tx("COMPRA FULANA EXEMPLO"), nome))  # não é transferência
        self.assertFalse(regras.eh_mesmo_titular_por_nome(tx("Pix enviado FULANA EXEMPLO"), "Fulana"))  # nome curto demais


class TestCategoriaAutomatica(unittest.TestCase):
    def test_palavras_chave(self):
        casos = [
            ("IFOOD *RESTAURANTE", False, False, "11020000"),
            ("SUPERMERCADO EXEMPLO", False, True, "10000000"),
            ("MERCADO LIVRE", False, True, "08010000"),  # compra online, não supermercado
            ("UBER *TRIP", False, True, "19010000"),
            ("UBER EATS", False, True, "11020000"),
            ("NETFLIX.COM", False, True, "09020000"),
            ("IOF COMPRA INTERNACIONAL", False, True, "15030000"),
            ("SALARIO EMPRESA", True, False, "01010000"),
            ("PIX ENVIADO FULANO", False, False, "05070000"),
            ("XYZ123", False, False, categorizar.CAT_OUTROS),
        ]
        for descricao, entrada, cartao, esperado in casos:
            with self.subTest(descricao=descricao):
                self.assertEqual(categorizar.categorizar(descricao, entrada, cartao, {})[0], esperado)

    def test_pagamento_de_fatura(self):
        self.assertEqual(categorizar.categorizar("Pagamento recebido", True, True, {}),
                         (categorizar.CAT_PAGAMENTO_CARTAO, "palavra"))
        self.assertEqual(categorizar.categorizar("PAGTO FATURA CARTAO", False, False, {})[0], categorizar.CAT_PAGAMENTO_CARTAO)
        # na conta, "pagamento" sozinho não é fatura
        self.assertNotEqual(categorizar.categorizar("PAGAMENTO BOLETO", False, False, {})[0], categorizar.CAT_PAGAMENTO_CARTAO)

    def test_historico_vale_mais_que_palavra_chave(self):
        chave = categorizar.chave_aprendizado("PADARIA EXEMPLO")
        aprendido = {(chave, False): "08010000"}
        self.assertEqual(categorizar.categorizar("PADARIA EXEMPLO", False, True, aprendido), ("08010000", "historico"))
        # entrada e saída aprendem separado
        self.assertEqual(categorizar.categorizar("PADARIA EXEMPLO", True, True, aprendido)[1], "palavra")

    def test_operacao(self):
        self.assertEqual(categorizar.operacao("Pix enviado X"), "PIX")
        self.assertEqual(categorizar.operacao("TED RECEBIDA"), "TED")
        self.assertEqual(categorizar.operacao("PAG TIT BANCO"), "BOLETO")
        self.assertIsNone(categorizar.operacao("PADARIA"))


class TestAprender(TesteComBanco):
    def gravar(self, tid, descricao, categoria, tipo="DEBIT", **extra):
        bruto = {"id": tid, "description": descricao, "type": tipo, "categoryId": categoria, **extra}
        self.conexao.execute("INSERT INTO transacoes (id, conta_id, data, bruto) VALUES (?, 'c', '2026-09-01', ?)",
                             (tid, json.dumps(bruto)))

    def test_aprende_pela_maioria_e_pelos_ajustes(self):
        self.gravar("t1", "Pix enviado FULANO EXEMPLO", "05070000")
        self.gravar("t2", "PIX ENVIADO | Fulano Exemplo", "05070000")
        self.gravar("t3", "Pix enviado FULANO EXEMPLO", "05070000")
        # os três foram ajustados à mão para Aluguel
        for t in ("t1", "t2", "t3"):
            self.conexao.execute("INSERT INTO ajustes (transacao_id, categoria_id) VALUES (?, '17010000')", (t,))
        aprendido = categorizar.aprender(self.conexao)
        self.assertEqual(aprendido[(categorizar.chave_aprendizado("Pix enviado FULANO EXEMPLO"), False)], "17010000")
        self.assertEqual(categorizar.categorizar("PIX ENVIADO FULANO EXEMPLO", False, False, aprendido)[0], "17010000")

    def test_sem_maioria_clara_nao_aprende(self):
        self.gravar("t1", "LOJA EXEMPLO", "08010000")
        self.gravar("t2", "LOJA EXEMPLO", "08040000")
        self.assertEqual(categorizar.aprender(self.conexao), {})

    def test_ignora_outros_e_projetadas(self):
        self.gravar("t1", "LOJA EXEMPLO", categorizar.CAT_OUTROS)
        self.gravar("t2", "LOJA PROJETADA", "08010000", _projetada=1)
        self.assertEqual(categorizar.aprender(self.conexao), {})


if __name__ == "__main__":
    unittest.main()
