"""Servidor HTTP local (openbalance/servidor.py): cabeçalhos de segurança e corpo de requisição inválido."""

import http.client
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from openbalance import banco, servidor


class TestServidor(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.conexao = banco.conectar(Path(pasta.name) / "teste.db")
        self.addCleanup(self.conexao.close)
        with socket.socket() as livre:
            livre.bind(("127.0.0.1", 0))
            self.porta = livre.getsockname()[1]
        self.servidor = servidor.criar_servidor(self.conexao, self.porta)
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def pedir(self, metodo, caminho, cabecalhos=None):
        cliente = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        self.addCleanup(cliente.close)
        cliente.putrequest(metodo, caminho)
        for nome, valor in (cabecalhos or {}).items():
            cliente.putheader(nome, valor)
        cliente.endheaders()
        return cliente.getresponse()

    def test_paginas_saem_com_politica_de_conteudo(self):
        resposta = self.pedir("GET", "/")
        self.assertEqual(resposta.status, 200)
        politica = resposta.getheader("Content-Security-Policy")
        self.assertIn("default-src 'self'", politica)
        self.assertIn("connect-src 'self'", politica)
        self.assertIn("frame-ancestors 'none'", politica)
        self.assertNotIn("unsafe-eval", politica)
        self.assertEqual(resposta.getheader("X-Frame-Options"), "DENY")

    def test_erros_tambem_saem_com_politica_de_conteudo(self):
        resposta = self.pedir("GET", "/api/rota-que-nao-existe")
        self.assertIn("default-src 'self'", resposta.getheader("Content-Security-Policy"))

    def test_tamanho_negativo_e_recusado_sem_esperar_o_corpo(self):
        # Antes da correção, read(-1) ficava esperando o cliente fechar a conexão e este pedido estourava o tempo.
        resposta = self.pedir("POST", "/api/orcamento", {servidor.CABECALHO_ACAO: "1", "Content-Length": "-1"})
        self.assertEqual(resposta.status, 400)
        self.assertIn("tamanho", resposta.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
