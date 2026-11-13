"""Caminhos do projeto e leitura do .env."""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"
ARQUIVO_BANCO = PASTA_DADOS / "open-balance.db"
PASTA_WEB = RAIZ / "web"


def carregar_env(caminho=RAIZ / ".env"):
    """Lê um .env simples (CHAVE=valor). Variáveis já definidas no ambiente têm prioridade."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


CHAVES_PLUGGY = ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS")


def salvar_env(valores, caminho=RAIZ / ".env"):
    """Grava chaves no .env mantendo o resto do arquivo (None apaga a chave) e já aplica no processo atual."""
    linhas = caminho.read_text(encoding="utf-8-sig").splitlines() if caminho.exists() else [
        "# Credenciais da Pluggy, gravadas pelo Open Balance (aba Importar → Conectar).",
        "# Fica só neste computador: não compartilhe este arquivo nem coloque a pasta em nuvem."]
    pendentes = dict(valores)
    resultado = []
    for linha in linhas:
        chave = linha.split("=", 1)[0].strip() if "=" in linha and not linha.strip().startswith("#") else None
        if chave in pendentes:
            valor = pendentes.pop(chave)
            if valor is not None:
                resultado.append(f"{chave}={valor}")
            continue
        resultado.append(linha)
    resultado += [f"{chave}={valor}" for chave, valor in pendentes.items() if valor is not None]
    caminho.write_text("\n".join(resultado) + "\n", encoding="utf-8")
    for chave, valor in valores.items():
        if valor is None:
            os.environ.pop(chave, None)
        else:
            os.environ[chave] = valor


def resumo_pluggy():
    """O que a tela pode mostrar da conexão. O Client Secret nunca sai daqui."""
    carregar_env()
    return {"configurado": pluggy_configurado(), "clientId": os.environ.get("PLUGGY_CLIENT_ID", "").strip(),
            "temSecret": bool(os.environ.get("PLUGGY_CLIENT_SECRET", "").strip()), "itemIds": itens_configurados()}


def itens_configurados():
    """Item IDs do .env (lista vazia se não houver), sem exigir as credenciais."""
    carregar_env()
    return [i.strip() for i in os.environ.get("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]


def pluggy_configurado():
    """True se o .env tem tudo para sincronizar. Sem isso o app funciona só com arquivos importados."""
    try:
        credenciais()
        return True
    except ValueError:
        return False


def credenciais():
    """Devolve (client_id, client_secret, [item_ids]) ou levanta ValueError dizendo o que falta."""
    carregar_env()
    client_id = os.environ.get("PLUGGY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("PLUGGY_CLIENT_SECRET", "").strip()
    item_ids = [i.strip() for i in os.environ.get("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]
    faltando = [nome for nome, valor in (("PLUGGY_CLIENT_ID", client_id),
                                         ("PLUGGY_CLIENT_SECRET", client_secret),
                                         ("PLUGGY_ITEM_IDS", item_ids)) if not valor]
    if faltando:
        raise ValueError(f"Faltam variáveis no {RAIZ / '.env'}: {', '.join(faltando)}")
    return client_id, client_secret, item_ids
