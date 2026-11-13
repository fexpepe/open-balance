"""Gera uma cópia do Open Balance para passar a outra pessoa — só o código, nenhum dado seu.

    python compartilhar.py               cria dist/Open-Balance-AAAAMMDD.zip
    python compartilhar.py --saida X.zip

Entra só o que está na lista abaixo (app, interface, LEIA-ME e o .env.example em branco).
Nunca entram: .env (credenciais da Pluggy), dados/ (seu banco de dados e backups), dados_brutos/.
Quem receber abre com "Abrir Open Balance.bat" e importa os próprios extratos na aba Importar.
"""

import argparse
import zipfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQUIVOS = ["app.py", "Abrir Open Balance.bat", "LEIA-ME.txt", "LICENSE", ".env.example", ".gitignore"]
PASTAS = {"openbalance": (".py", ".json"), "web": (".html", ".css", ".js", ".csv", ".svg", ".png", ".ico")}
PROIBIDOS = {".env", "dados", "dados_brutos", "__pycache__", "dist"}


def arquivos_do_pacote():
    for nome in ARQUIVOS:
        if (RAIZ / nome).is_file():
            yield RAIZ / nome
    for pasta, extensoes in PASTAS.items():
        for caminho in sorted((RAIZ / pasta).rglob("*")):
            if caminho.is_file() and caminho.suffix.lower() in extensoes:
                yield caminho


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=RAIZ / "dist" / f"Open-Balance-{date.today():%Y%m%d}.zip")
    args = parser.parse_args()
    args.saida.parent.mkdir(parents=True, exist_ok=True)

    incluidos = []
    with zipfile.ZipFile(args.saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        for caminho in arquivos_do_pacote():
            relativo = caminho.relative_to(RAIZ)
            if PROIBIDOS & set(relativo.parts):  # trava extra: nada de dados pessoais, mesmo se a lista mudar
                raise SystemExit(f"Recusado: {relativo} não pode ir no pacote.")
            pacote.write(caminho, Path("Open Balance") / relativo)
            incluidos.append(str(relativo))
    print(f"Pacote criado: {args.saida}")
    print(f"{len(incluidos)} arquivos (só código e interface; sem .env, sem banco de dados).")


if __name__ == "__main__":
    main()
