"""Cliente mínimo da API da Pluggy (somente leitura, só biblioteca padrão)."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.pluggy.ai"
USER_AGENT = "open-balance/1.0"


class ErroApi(Exception):
    def __init__(self, status, mensagem):
        super().__init__(f"HTTP {status}: {mensagem}" if status else mensagem)
        self.status = status


class Pluggy:
    def __init__(self, client_id, client_secret):
        resposta = self._requisitar("POST", "/auth", corpo={"clientId": client_id, "clientSecret": client_secret})
        self.api_key = resposta["apiKey"]

    def _requisitar(self, metodo, caminho, params=None, corpo=None, api_key=None):
        url = BASE_URL + caminho
        if params:
            url += "?" + urllib.parse.urlencode(params)
        cabecalhos = {"Accept": "application/json", "User-Agent": USER_AGENT}
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cabecalhos["Content-Type"] = "application/json"
        if api_key:
            cabecalhos["X-API-KEY"] = api_key
        req = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", errors="replace")
            try:
                texto = json.loads(texto).get("message", texto)
            except (ValueError, AttributeError):
                pass
            raise ErroApi(e.code, str(texto)[:300]) from None
        except urllib.error.URLError as e:
            raise ErroApi(0, f"falha de rede: {e.reason}") from None

    def get(self, caminho, params=None):
        return self._requisitar("GET", caminho, params=params, api_key=self.api_key)

    def get_paginado(self, caminho, params):
        """Endpoints paginados por page/pageSize (investments, bills)."""
        resultados, pagina = [], 1
        while True:
            dados = self.get(caminho, {**params, "page": pagina, "pageSize": 500})
            resultados += dados.get("results", [])
            if pagina >= (dados.get("totalPages") or 1):
                return resultados
            pagina += 1

    def transacoes(self, account_id, data_inicio):
        """GET /v2/transactions, paginado por cursor."""
        filtros = {"accountId": account_id, "dateFrom": data_inicio}
        resultados, params, vistos = [], dict(filtros), set()
        while True:
            dados = self.get("/v2/transactions", params)
            resultados += dados.get("results", [])
            proximo = dados.get("next")
            if not proximo or proximo in vistos:
                return resultados
            vistos.add(proximo)
            # 'next' é uma query string pronta ("?accountId=...&after=...");
            # reaplica os filtros de data caso ela não os traga.
            consulta = urllib.parse.urlsplit(proximo).query or proximo.lstrip("?")
            params = {**filtros, **dict(urllib.parse.parse_qsl(consulta))}


RE_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def testar_conexao(client_id, client_secret, item_ids, cliente=Pluggy):
    """Confere credenciais e Item IDs antes de gravá-los. Levanta ValueError com uma mensagem para a tela."""
    invalidos = [i for i in [client_id, *item_ids] if not RE_ID.match(i)]
    if invalidos:
        raise ValueError(f"Formato inválido (esperado algo como 1a2b3c4d-…): {invalidos[0][:40]}")
    try:
        api = cliente(client_id, client_secret)
    except ErroApi as e:
        if e.status in (400, 401, 403):
            raise ValueError("A Pluggy recusou o Client ID / Client Secret. Confira se copiou os dois da mesma aplicação.") from None
        raise ValueError(f"Não consegui falar com a Pluggy: {e}") from None
    itens = []
    for item_id in item_ids:
        try:
            item = api.get(f"/items/{item_id}")
        except ErroApi as e:
            if e.status in (403, 404):
                raise ValueError(f"Item ID não encontrado nesta aplicação: {item_id[:8]}… (copie de novo na Demo).") from None
            raise ValueError(f"Não consegui conferir o item {item_id[:8]}…: {e}") from None
        itens.append({"id": item_id, "conector": (item.get("connector") or {}).get("name"), "status": item.get("status")})
    return itens
