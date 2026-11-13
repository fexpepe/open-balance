"""Importação de arquivos (openbalance/importar.py): prévia, gravação, deduplicação ao reimportar e desfazer."""

import json
import unittest
from datetime import date

from openbalance import importar
from tests.ajudantes import TesteComBanco, arquivo, gerar_xlsx

HOJE = date(2026, 10, 15)


class TesteImportacao(TesteComBanco):
    def confirmar(self, nome, opcoes, conteudo=None):
        return importar.confirmar(self.conexao, nome, conteudo if conteudo is not None else arquivo(nome), opcoes, hoje=HOJE)

    def analisar(self, nome, opcoes=None):
        return importar.analisar(self.conexao, nome, arquivo(nome), opcoes, hoje=HOJE)

    def nova_conta_ofx(self):
        return self.confirmar("conta_e_cartao.ofx", {"parte": 0, "tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})

    def transacoes(self, conta_id, projetadas=False):
        lista = [json.loads(r["bruto"]) for r in self.conexao.execute(
            "SELECT bruto FROM transacoes WHERE conta_id = ? ORDER BY data", (conta_id,))]
        return [t for t in lista if bool(t.get("_projetada")) == projetadas]

    def saldo(self, conta_id):
        return importar.ler_conta(self.conexao, conta_id)["bruto"]["balance"]


class TestPrevia(TesteImportacao):
    def test_previa_nao_grava_nada(self):
        previas = self.analisar("conta_e_cartao.ofx")
        self.assertEqual([p["tipo"] for p in previas], ["conta", "cartao"])
        conta = previas[0]
        self.assertEqual((conta["novas"], conta["duplicadas"], conta["atualizadas"]), (4, 0, 0))
        self.assertEqual(conta["periodo"], ["2026-09-05", "2026-09-20"])
        self.assertEqual(conta["saldo"], 3560.10)
        self.assertEqual(self.contar("transacoes"), 0)
        self.assertEqual(self.contar("contas"), 0)

    def test_previa_sugere_a_conta_pelo_numero(self):
        resumo = self.nova_conta_ofx()
        previa = self.analisar("conta_e_cartao.ofx")[0]
        self.assertEqual(previa["contaId"], resumo["conta"])
        self.assertEqual((previa["novas"], previa["atualizadas"]), (0, 4))


class TestContaCorrente(TesteImportacao):
    def test_importa_e_cria_a_conta_com_saldo(self):
        resumo = self.nova_conta_ofx()
        self.assertEqual((resumo["novas"], resumo["duplicadas"]), (4, 0))
        self.assertEqual(resumo["instituicao"], "Banco Exemplo")
        self.assertEqual(resumo["saldo"], 3560.10)
        txs = self.transacoes(resumo["conta"])
        self.assertEqual([t["type"] for t in txs], ["CREDIT", "DEBIT", "DEBIT", "DEBIT"])
        self.assertEqual(txs[1]["amount"], -1200.0)

    def test_categoria_automatica(self):
        txs = {t["description"]: t for t in self.transacoes(self.nova_conta_ofx()["conta"])}
        self.assertEqual(txs["SALARIO EMPRESA FICTICIA LTDA"]["categoryId"], "01010000")
        self.assertEqual(txs["PAGTO FATURA CARTAO"]["categoryId"], importar.CAT_PAGAMENTO_CARTAO)
        self.assertEqual(txs["COMPRA CARTAO SUPERMERCADO MODELO"]["categoryId"], "10000000")

    def test_reimportar_o_mesmo_arquivo_nao_duplica(self):
        conta = self.nova_conta_ofx()["conta"]
        resumo = self.confirmar("conta_e_cartao.ofx", {"parte": 0, "tipo": "conta", "contaId": conta})
        self.assertEqual((resumo["novas"], resumo["atualizadas"], resumo["duplicadas"]), (0, 4, 0))
        self.assertEqual(self.contar("transacoes"), 4)

    def test_reimportar_csv_sem_identificador_nao_duplica(self):
        primeiro = self.confirmar("extrato_conta.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})
        segundo = self.confirmar("extrato_conta.csv", {"tipo": "conta", "contaId": primeiro["conta"]})
        self.assertEqual((segundo["novas"], segundo["atualizadas"]), (0, 4))
        self.assertEqual(self.contar("transacoes"), 4)

    def test_mesmo_periodo_em_outro_formato_e_reconhecido(self):
        # OFX e CSV do mesmo mês: ids diferentes, mas mesma data e valor
        conta = self.nova_conta_ofx()["conta"]
        resumo = self.confirmar("extrato_conta.csv", {"tipo": "conta", "contaId": conta})
        self.assertEqual((resumo["novas"], resumo["duplicadas"]), (0, 4))
        self.assertEqual(self.contar("transacoes"), 4)

    def test_periodo_que_se_sobrepoe_ao_anterior(self):
        conta = self.confirmar("extrato_conta.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})["conta"]
        resumo = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "contaId": conta})
        self.assertEqual(resumo["novas"], 2)
        self.assertEqual(resumo["atualizadas"] + resumo["duplicadas"], 2)
        self.assertEqual(self.contar("transacoes"), 6)
        # saldo: o do arquivo mais recente
        self.assertEqual(self.saldo(conta), 3774.60)

    def test_lancamentos_iguais_no_mesmo_dia_sao_dois(self):
        texto = ("Data;Descrição;Valor\n01/09/2026;CAFE EXEMPLO;-5,00\n01/09/2026;CAFE EXEMPLO;-5,00\n"
                 "02/09/2026;PIX RECEBIDO;10,00\n").encode("utf-8")
        resumo = self.confirmar("x.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}}, texto)
        self.assertEqual(resumo["novas"], 3)
        de_novo = self.confirmar("x.csv", {"tipo": "conta", "contaId": resumo["conta"]}, texto)
        self.assertEqual((de_novo["novas"], de_novo["atualizadas"]), (0, 3))

    def test_saldo_de_arquivo_antigo_nao_volta_o_saldo(self):
        conta = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})["conta"]
        self.confirmar("extrato_conta.csv", {"tipo": "conta", "contaId": conta})
        self.assertEqual(self.saldo(conta), 3774.60)

    def test_desfazer_a_primeira_importacao_apaga_a_conta(self):
        resumo = self.nova_conta_ofx()
        importar.desfazer(self.conexao, resumo["lote"])
        self.assertEqual(self.contar("transacoes"), 0)
        self.assertEqual(self.contar("contas"), 0)
        self.assertEqual(self.contar("itens"), 0)
        self.assertEqual(self.contar("importacoes"), 0)

    def test_desfazer_so_remove_o_que_a_importacao_acrescentou(self):
        conta = self.nova_conta_ofx()["conta"]
        resumo = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "contaId": conta})
        self.assertEqual(self.contar("transacoes"), 6)
        retorno = importar.desfazer(self.conexao, resumo["lote"])
        self.assertEqual(retorno["removidas"], 2)
        self.assertEqual(self.contar("transacoes"), 4)
        self.assertEqual(self.contar("contas"), 1)

    def saldos_guardados(self, conta_id):
        return [tuple(r) for r in self.conexao.execute(
            "SELECT data, saldo FROM historico_saldos WHERE ref_id = ? ORDER BY data", (conta_id,))]

    def test_desfazer_volta_o_saldo_anterior(self):
        conta = self.nova_conta_ofx()["conta"]
        antes = self.saldos_guardados(conta)
        resumo = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "contaId": conta})
        self.assertEqual(self.saldo(conta), 3774.60)
        importar.desfazer(self.conexao, resumo["lote"])
        self.assertEqual(self.saldo(conta), 3560.10)
        self.assertEqual(self.saldos_guardados(conta), antes)

    def test_desfazer_o_mais_recente_usa_o_saldo_de_arquivo_mais_antigo(self):
        # outubro primeiro, setembro depois (o saldo de setembro não vale enquanto o de outubro existir)
        conta = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})
        self.confirmar("extrato_conta.csv", {"tipo": "conta", "contaId": conta["conta"]})
        self.assertEqual(self.saldo(conta["conta"]), 3774.60)
        importar.desfazer(self.conexao, conta["lote"])
        # sobram os lançamentos de setembro e o saldo de 20/09
        self.assertEqual(self.saldo(conta["conta"]), 3560.10)

    def test_desfazer_sem_outro_saldo_deixa_a_conta_sem_saldo(self):
        conta = self.confirmar("extrato_conta.csv", {"tipo": "conta", "novaConta": {"instituicao": "Banco Exemplo"}})["conta"]
        sem_saldo = "Data;Descrição;Valor\n02/10/2026;PIX RECEBIDO CICLANO DE TESTE;250,00\n".encode("utf-8")
        self.confirmar("x.csv", {"tipo": "conta", "contaId": conta}, sem_saldo)
        primeira = self.conexao.execute("SELECT min(id) FROM importacoes").fetchone()[0]
        importar.desfazer(self.conexao, primeira)
        b = importar.ler_conta(self.conexao, conta)["bruto"]
        self.assertIsNone(b["_saldoData"])
        self.assertEqual(self.saldos_guardados(conta), [])

    def test_saldo_digitado_nao_some_ao_desfazer(self):
        conta = self.nova_conta_ofx()["conta"]
        resumo = self.confirmar("extrato_conta_outubro.csv", {"tipo": "conta", "contaId": conta})
        importar.editar_conta(self.conexao, {"contaId": conta, "saldo": "5.000,00"})
        importar.desfazer(self.conexao, resumo["lote"])
        self.assertEqual(self.saldo(conta), 5000.0)

    def test_conta_de_tipo_errado_e_recusada(self):
        cartao = self.confirmar("fatura_cartao.csv", {"tipo": "cartao", "novaConta": {"instituicao": "Nubank"}})["conta"]
        with self.assertRaises(ValueError):
            self.confirmar("extrato_conta.csv", {"tipo": "conta", "contaId": cartao})

    def test_arquivo_que_precisa_de_mapeamento(self):
        with self.assertRaises(ValueError):
            self.confirmar("x.csv", {"tipo": "conta"}, b"a;b;c\nxx;yy;zz\nww;kk;ll\n")

    def test_mapeamento_e_lembrado_para_o_proximo_arquivo(self):
        conteudo = "a;b;c\n01/09/2026;LOJA A;-10,00\n02/09/2026;LOJA B;-20,00\n".encode("utf-8")
        # cabecalho = linhaCabecalho da prévia (-1 aqui), como a tela manda
        mapeamento = {"cabecalho": -1, "papeis": {"data": [0], "descricao": [1], "valor": [2]}}
        self.confirmar("x.csv", {"tipo": "conta", "mapeamento": mapeamento, "novaConta": {"instituicao": "Banco Exemplo"}}, conteudo)
        (previa,) = importar.analisar(self.conexao, "y.csv", conteudo.replace(b"LOJA", b"BAR"), hoje=HOJE)
        self.assertFalse(previa.get("precisaMapeamento"))
        self.assertEqual(previa["quantidade"], 2)


class TestCartao(TesteImportacao):
    def importar_fatura(self, **opcoes):
        return self.confirmar("fatura_cartao.csv", {"tipo": "cartao", "novaConta": {"instituicao": "Nubank"},
                                                    "vencimento": "2026-10-05", **opcoes})

    def test_compras_viram_debito_e_pagamento_credito(self):
        resumo = self.importar_fatura()
        self.assertEqual(resumo["novas"], 5)
        txs = self.transacoes(resumo["conta"])
        pagamento = next(t for t in txs if t["description"] == "Pagamento recebido")
        self.assertEqual((pagamento["type"], pagamento["amount"]), ("CREDIT", -980.0))
        self.assertEqual(pagamento["categoryId"], importar.CAT_PAGAMENTO_CARTAO)
        compras = [t for t in txs if t["type"] == "DEBIT"]
        self.assertTrue(all(t["amount"] > 0 for t in compras))
        self.assertEqual({t["creditCardMetadata"]["billForecastDate"] for t in txs}, {"2026-10"})

    def test_parcela_sai_da_descricao_e_projeta_as_futuras(self):
        resumo = self.importar_fatura()
        parcelada = next(t for t in self.transacoes(resumo["conta"]) if t["creditCardMetadata"].get("totalInstallments"))
        self.assertEqual(parcelada["description"], "Loja de Eletronicos Exemplo")
        self.assertEqual(parcelada["creditCardMetadata"]["installmentNumber"], 2)
        futuras = self.transacoes(resumo["conta"], projetadas=True)
        self.assertEqual(resumo["projetadas"], 2)
        self.assertEqual([t["creditCardMetadata"]["installmentNumber"] for t in futuras], [3, 4])
        self.assertEqual([t["creditCardMetadata"]["billForecastDate"] for t in futuras], ["2026-11", "2026-12"])

    def test_fatura_fechada_sem_o_pagamento_anterior(self):
        resumo = self.importar_fatura()
        self.assertEqual(resumo["faturas"], 1)
        (fatura,) = self.conexao.execute("SELECT vencimento, total FROM faturas").fetchall()
        # 72,40 + 250,00 + 2 × 23,90; o pagamento de 980,00 é da fatura anterior
        self.assertEqual((fatura["vencimento"], fatura["total"]), ("2026-10-05", 370.20))

    def test_reimportar_a_fatura_nao_duplica(self):
        conta = self.importar_fatura()["conta"]
        resumo = self.confirmar("fatura_cartao.csv", {"tipo": "cartao", "contaId": conta, "vencimento": "2026-10-05"})
        self.assertEqual((resumo["novas"], resumo["atualizadas"]), (0, 5))
        self.assertEqual(len(self.transacoes(conta)), 5)
        self.assertEqual(len(self.transacoes(conta, projetadas=True)), 2)
        self.assertEqual(self.contar("faturas"), 1)

    def test_fatura_seguinte_substitui_a_parcela_projetada(self):
        conta = self.importar_fatura()["conta"]
        seguinte = "date,title,amount\n2026-10-15,Loja de Eletronicos Exemplo - Parcela 3/4,250.00\n2026-10-18,Padaria Exemplo,12.00\n"
        self.confirmar("fatura_nov.csv", {"tipo": "cartao", "contaId": conta, "vencimento": "2026-11-05"}, seguinte.encode("utf-8"))
        futuras = self.transacoes(conta, projetadas=True)
        self.assertEqual([t["creditCardMetadata"]["installmentNumber"] for t in futuras], [4])
        parcelas = [t for t in self.transacoes(conta) if t["creditCardMetadata"].get("totalInstallments")]
        self.assertEqual([t["creditCardMetadata"]["installmentNumber"] for t in parcelas], [2, 3])

    def test_cartao_do_ofx(self):
        resumo = self.confirmar("conta_e_cartao.ofx", {"parte": 1, "tipo": "cartao", "novaConta": {"instituicao": "Banco Exemplo"}})
        self.assertEqual(resumo["novas"], 2)
        txs = self.transacoes(resumo["conta"])
        self.assertTrue(all(t["type"] == "DEBIT" and t["amount"] > 0 for t in txs))
        self.assertEqual(resumo["projetadas"], 3)  # parcela 2/5 → 3, 4 e 5


class TestPosicoes(TesteImportacao):
    def planilha(self):
        return gerar_xlsx({"Posição": [
            ["Produto", "Código de Negociação", "Quantidade", "Valor Atualizado", "Instituição"],
            ["ACAO EXEMPLO ON", "ABCD3", 100, 1234.5, "CORRETORA EXEMPLO S.A."],
            ["CDB BANCO EXEMPLO", "", "", 5000, ""],
        ]})

    def test_sem_instituicao_pede_uma_padrao(self):
        with self.assertRaises(ValueError):
            self.confirmar("posicao.xlsx", {"tipo": "investimentos"}, self.planilha())

    def test_grava_e_substitui_a_posicao_anterior(self):
        opcoes = {"tipo": "investimentos", "instituicao": "Banco Exemplo", "dataPosicao": "2026-10-01"}
        resumo = self.confirmar("posicao.xlsx", opcoes, self.planilha())
        self.assertEqual(resumo["posicoes"], 2)
        self.assertEqual(resumo["instituicoes"], ["Banco Exemplo", "Corretora Exemplo"])
        self.assertEqual(resumo["total"], 6234.5)
        acao = json.loads(self.conexao.execute("SELECT bruto FROM investimentos WHERE saldo = 1234.5").fetchone()[0])
        self.assertEqual((acao["code"], acao["quantity"], acao["value"]), ("ABCD3", 100.0, 12.345))
        self.confirmar("posicao.xlsx", {**opcoes, "dataPosicao": "2026-10-10"}, self.planilha())
        self.assertEqual(self.contar("investimentos"), 2)

    def test_desfazer_posicao(self):
        opcoes = {"tipo": "investimentos", "instituicao": "Banco Exemplo"}
        resumo = self.confirmar("posicao.xlsx", opcoes, self.planilha())
        importar.desfazer(self.conexao, resumo["lote"])
        self.assertEqual(self.contar("investimentos"), 0)
        self.assertEqual(self.contar("itens"), 0)


class TestDatasDaFatura(unittest.TestCase):
    def test_mes_da_fatura(self):
        # fecha dia 3, vence dia 10
        self.assertEqual(importar.mes_da_fatura("2026-09-03", 3, 10), "2026-09")
        self.assertEqual(importar.mes_da_fatura("2026-09-04", 3, 10), "2026-10")
        # fecha dia 25, vence dia 5 do mês seguinte
        self.assertEqual(importar.mes_da_fatura("2026-09-20", 25, 5), "2026-10")
        self.assertEqual(importar.mes_da_fatura("2026-09-26", 25, 5), "2026-11")

    def test_meses_e_dias(self):
        self.assertEqual(importar.mes_mais("2026-11", 3), "2027-02")
        self.assertEqual(importar.somar_meses_data("2026-01-31", 1), "2026-02-28")
        self.assertEqual(importar.fechamento_da_fatura("2026-10", 25, 5), "2026-09-25")


if __name__ == "__main__":
    unittest.main()
