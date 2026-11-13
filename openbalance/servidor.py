"""Servidor HTTP local (só 127.0.0.1): entrega a interface e a API JSON."""

import base64
import binascii
import json
import mimetypes
import os
import re
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import analise, banco, carteira, historico, importar, imposto, orcamento, previsao, regras, revisao, saude, sincronizar
from .config import CHAVES_PLUGGY, PASTA_WEB, resumo_pluggy, salvar_env
from .pluggy import ErroApi, testar_conexao

CABECALHO_ACAO = "X-Open-Balance"
# Fixos: no Windows o registro às vezes mapeia .js para text/plain e quebra os módulos.
TIPOS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json", ".csv": "text/csv"}
LIMITE_CORPO = 1_000_000
LIMITE_ARQUIVO = 30_000_000  # arquivos de extrato vêm em base64 dentro do JSON
# Só carrega e só fala com o próprio painel: um HTML injetado não consegue buscar script de fora nem mandar dados
# para outro servidor. O estilo inline fica liberado porque a interface usa style="..." em toda parte.
POLITICA_CONTEUDO = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                     "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def criar_servidor(conexao, porta):
    trava_banco = threading.Lock()
    arquivo_banco = banco.arquivo(conexao)
    hosts_validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}

    class Manipulador(BaseHTTPRequestHandler):
        server_version = "OpenBalance/1.0"

        def log_message(self, formato, *args):
            if "/api/" in (args[0] if args else ""):
                print(f"[{datetime.now():%H:%M:%S}] {args[0]}")

        # --- respostas -------------------------------------------------------
        def _responder(self, status, corpo, tipo="application/json; charset=utf-8"):
            dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", POLITICA_CONTEUDO)
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(dados)

        def _erro(self, status, mensagem):
            self._responder(status, {"erro": mensagem})

        def _host_ok(self):
            # Bloqueia DNS rebinding: só aceita requisições endereçadas ao próprio PC.
            return self.headers.get("Host") in hosts_validos

        def _corpo_json(self, limite=LIMITE_CORPO):
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho < 0:  # read(-1) esperaria o cliente fechar a conexão, prendendo a thread
                raise ValueError("tamanho do corpo inválido")
            if tamanho > limite:
                raise ValueError("arquivo grande demais" if limite > LIMITE_CORPO else "corpo grande demais")
            return json.loads(self.rfile.read(tamanho) or b"{}")

        # --- GET -------------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                return self._erro(403, "host inválido")
            caminho = urlsplit(self.path).path
            if caminho == "/api/dados":
                with trava_banco:
                    dados = analise.montar(conexao)
                    dados["saude"] = saude.montar(conexao)  # rotina diária e conexões (avisos do topo)
                    return self._responder(200, dados)
            if caminho == "/api/historico":
                # Responde com o que já está guardado e, se preciso, baixa cotações novas em segundo plano.
                try:
                    with trava_banco:
                        resposta = historico.montar(conexao)
                        historico.iniciar_atualizacao(conexao)
                except Exception as e:  # noqa: BLE001 — mostra o erro na tela em vez de derrubar a requisição
                    traceback.print_exc()
                    return self._erro(500, f"{type(e).__name__}: {e}")
                resposta["progresso"] = historico.progresso()
                return self._responder(200, resposta)
            if caminho == "/api/revisao":  # despesas em categorias genéricas, agrupadas por recebedor
                with trava_banco:
                    return self._responder(200, revisao.montar(conexao))
            if caminho.startswith("/api/"):
                return self._erro(404, "rota inexistente")
            return self._arquivo_estatico(caminho)

        def _arquivo_estatico(self, caminho):
            nome = "index.html" if caminho in ("", "/") else caminho.lstrip("/")
            arquivo = (PASTA_WEB / nome).resolve()
            if PASTA_WEB.resolve() not in arquivo.parents or not arquivo.is_file():
                return self._erro(404, "não encontrado")
            tipo = TIPOS.get(arquivo.suffix.lower()) or mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
            if tipo.startswith("text/"):
                tipo += "; charset=utf-8"
            self._responder(200, arquivo.read_bytes(), tipo)

        # --- POST ------------------------------------------------------------
        def do_POST(self):
            if not self._host_ok():
                return self._erro(403, "host inválido")
            # Cabeçalho próprio força preflight CORS: outro site não consegue disparar ações aqui.
            if self.headers.get(CABECALHO_ACAO) != "1":
                return self._erro(403, "cabeçalho ausente")
            caminho = urlsplit(self.path).path
            try:
                corpo = self._corpo_json(LIMITE_ARQUIVO if caminho.startswith("/api/importar/") else LIMITE_CORPO)
                if caminho == "/api/sincronizar":
                    # Conexão própria: a sincronização demora e grava em etapas. Na conexão das telas, as gravações
                    # dela se misturariam com as de quem edita uma transação ou abre outra aba nesse meio-tempo.
                    conexao_sinc = banco.conectar(arquivo_banco)
                    try:
                        return self._responder(200, sincronizar.sincronizar(conexao_sinc))
                    finally:
                        conexao_sinc.close()
                if caminho == "/api/pluggy/conectar":  # fala com a Pluggy; não precisa travar o banco
                    return self._responder(200, conectar_pluggy(corpo))
                if caminho == "/api/pluggy/desconectar":
                    salvar_env({chave: None for chave in CHAVES_PLUGGY})
                    return self._responder(200, {"ok": True})
                with trava_banco:
                    if caminho == "/api/importar/analisar":
                        partes = importar.analisar(conexao, nome_arquivo(corpo), conteudo_arquivo(corpo), corpo.get("opcoes"))
                        return self._responder(200, {"partes": partes})
                    if caminho == "/api/importar/confirmar":
                        resumo = importar.confirmar(conexao, nome_arquivo(corpo), conteudo_arquivo(corpo), corpo.get("opcoes") or {})
                        return self._responder(200, resumo)
                    if caminho == "/api/importar/desfazer":
                        return self._responder(200, importar.desfazer(conexao, corpo["id"]))
                    if caminho == "/api/contas/editar":
                        return self._responder(200, importar.editar_conta(conexao, corpo))
                    if caminho == "/api/contas/excluir":
                        return self._responder(200, importar.excluir_conta(conexao, str(corpo["contaId"])))
                    if caminho == "/api/preferencias":
                        banco.gravar_preferencia(conexao, "titular", (corpo.get("titular") or "").strip()[:80])
                        return self._responder(200, {"ok": True})
                    if caminho == "/api/ajustes":
                        return self._responder(200, salvar_ajuste(conexao, corpo))
                    if caminho == "/api/regras":
                        return self._responder(200, salvar_regra(conexao, corpo))
                    if caminho == "/api/categorias":
                        return self._responder(200, salvar_categoria(conexao, corpo))
                    if caminho == "/api/revisao/ignorar":
                        return self._responder(200, revisao.ignorar(conexao, corpo))
                    if caminho == "/api/regras/remover":
                        with conexao:
                            conexao.execute("DELETE FROM regras WHERE id = ?", (int(corpo["id"]),))
                        return self._responder(200, {"ok": True})
                    if caminho == "/api/metas-alocacao":
                        return self._responder(200, carteira.salvar_metas(conexao, corpo))
                    if caminho == "/api/imposto/custo":
                        return self._responder(200, imposto.salvar_custo(conexao, corpo))
                    if caminho == "/api/imposto/prejuizo":
                        return self._responder(200, imposto.salvar_prejuizo(conexao, corpo))
                    if caminho == "/api/orcamento":
                        return self._responder(200, orcamento.salvar(conexao, corpo))
                    if caminho == "/api/previsao":
                        return self._responder(200, previsao.salvar_ajustes(conexao, corpo))
                return self._erro(404, "rota inexistente")
            except (ValueError, KeyError, TypeError) as e:
                return self._erro(400, str(e))
            except (ErroApi, RuntimeError) as e:
                return self._erro(502, str(e))
            except Exception as e:  # noqa: BLE001 — mostra o erro na tela em vez de derrubar o servidor
                traceback.print_exc()
                return self._erro(500, f"{type(e).__name__}: {e}")

    return ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)


def conectar_pluggy(corpo):
    """Confere as credenciais na Pluggy e só então grava no .env. Secret em branco = manter o já salvo."""
    atual = resumo_pluggy()
    client_id = str(corpo.get("clientId") or "").strip()
    client_secret = str(corpo.get("clientSecret") or "").strip()
    if not client_secret and atual["temSecret"] and client_id == atual["clientId"]:
        client_secret = os.environ.get("PLUGGY_CLIENT_SECRET", "").strip()
    item_ids = list(dict.fromkeys(re.findall(r"[0-9a-fA-F-]{36}", str(corpo.get("itemIds") or ""))))
    if not client_id or not client_secret:
        raise ValueError("preencha o Client ID e o Client Secret")
    if not item_ids:
        raise ValueError("cole ao menos um Item ID (um por banco conectado no MeuPluggy)")
    itens = testar_conexao(client_id, client_secret, item_ids)
    salvar_env({"PLUGGY_CLIENT_ID": client_id, "PLUGGY_CLIENT_SECRET": client_secret, "PLUGGY_ITEM_IDS": ",".join(item_ids)})
    return {"ok": True, "itens": itens}


def nome_arquivo(corpo):
    return str(corpo.get("nome") or "arquivo").replace("\\", "/").split("/")[-1][:200]


def conteudo_arquivo(corpo):
    try:
        return base64.b64decode(corpo["conteudo"], validate=True)
    except (binascii.Error, TypeError):
        raise ValueError("conteúdo do arquivo inválido") from None


def validar_natureza(natureza):
    if natureza not in (None, "", *regras.NATUREZAS):
        raise ValueError(f"natureza inválida: {natureza}")
    return natureza or None


def salvar_ajuste(conexao, corpo):
    """Ajuste manual de uma transação. Campos ausentes ficam como estão; null limpa."""
    tx_id = str(corpo["transacaoId"])
    atual = conexao.execute("SELECT * FROM ajustes WHERE transacao_id = ?", (tx_id,)).fetchone()
    novo = dict(atual) if atual else {"categoria_id": None, "natureza": None, "oculto": 0}
    if "categoriaId" in corpo:
        novo["categoria_id"] = corpo["categoriaId"] or None
    if "natureza" in corpo:
        novo["natureza"] = validar_natureza(corpo["natureza"])
    if "oculto" in corpo:
        novo["oculto"] = int(bool(corpo["oculto"]))
    with conexao:
        if not novo["categoria_id"] and not novo["natureza"] and not novo["oculto"]:
            conexao.execute("DELETE FROM ajustes WHERE transacao_id = ?", (tx_id,))
        else:
            conexao.execute("INSERT OR REPLACE INTO ajustes (transacao_id, categoria_id, natureza, oculto) "
                            "VALUES (?, ?, ?, ?)", (tx_id, novo["categoria_id"], novo["natureza"], novo["oculto"]))
    return {"ok": True}


def salvar_categoria(conexao, corpo):
    """Categoria criada por você. Sem 'paiId' vira um grupo próprio; com ele, uma subcategoria."""
    nome = (corpo.get("nome") or "").strip()
    if not 2 <= len(nome) <= 40:
        raise ValueError("o nome da categoria precisa ter entre 2 e 40 caracteres")
    pai = corpo.get("paiId") or None
    if pai and not conexao.execute("SELECT 1 FROM categorias WHERE id = ?", (pai,)).fetchone():
        raise ValueError("categoria principal inexistente")
    if conexao.execute("SELECT 1 FROM categorias WHERE lower(coalesce(descricao_pt, descricao)) = lower(?)",
                       (nome,)).fetchone():
        raise ValueError(f"já existe uma categoria chamada “{nome}”")
    proximo = conexao.execute("SELECT count(*) FROM categorias WHERE propria = 1").fetchone()[0] + 1
    novo_id = f"P{proximo:07d}"
    with conexao:
        conexao.execute("INSERT INTO categorias (id, descricao, descricao_pt, pai_id, propria) VALUES (?, ?, ?, ?, 1)",
                        (novo_id, nome, nome, pai))
    return {"ok": True, "id": novo_id}


def salvar_regra(conexao, corpo):
    padrao = (corpo.get("padrao") or "").strip()
    if len(padrao) < 3:
        raise ValueError("o trecho da descrição precisa ter ao menos 3 caracteres")
    categoria = corpo.get("categoriaId") or None
    natureza = validar_natureza(corpo.get("natureza"))
    if not categoria and not natureza:
        raise ValueError("informe uma categoria ou uma natureza")
    with conexao:
        cursor = conexao.execute("INSERT INTO regras (padrao, categoria_id, natureza, criada_em) VALUES (?, ?, ?, ?)",
                                 (padrao, categoria, natureza, datetime.now().isoformat(timespec="seconds")))
    return {"ok": True, "id": cursor.lastrowid}
