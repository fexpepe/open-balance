"""Open Balance — abre o painel no navegador.

    python app.py                  abre em http://127.0.0.1:8765
    python app.py --porta 9000
    python app.py --sem-navegador  só sobe o servidor
    python app.py --sincronizar    rotina diária sem abrir o painel: cópia de segurança, Pluggy, valor da carteira, cotações
    python app.py --agendar        roda a rotina diária sozinho, todo dia às 08:00 (--agendar 21:30 muda o horário)
    python app.py --desagendar     desliga a rotina agendada
    python app.py --banco X.db     usa outro arquivo de banco (ex.: para testar sem mexer nos seus dados)

Sem Pluggy, os dados entram pela aba Importar (arquivos OFX/CSV/XLSX exportados do banco).
A cada dia em que abre, o Open Balance guarda uma cópia do banco em dados/backup (detalhes em openbalance/backup.py).

Feche esta janela (ou Ctrl+C) para desligar.
"""

import argparse
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from openbalance import agendamento, backup, banco
from openbalance.config import ARQUIVO_BANCO
from openbalance.servidor import criar_servidor


def main():
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Painel de finanças local.")
    parser.add_argument("--porta", type=int, default=8765)
    parser.add_argument("--sem-navegador", action="store_true")
    parser.add_argument("--sincronizar", action="store_true", help="roda a rotina diária e sai, sem abrir o painel")
    parser.add_argument("--agendar", nargs="?", const="08:00", metavar="HH:MM",
                        help="agenda a rotina diária no Windows (padrão: 08:00)")
    parser.add_argument("--desagendar", action="store_true", help="remove a rotina diária agendada")
    parser.add_argument("--banco", type=Path, default=ARQUIVO_BANCO, help="arquivo do banco de dados (SQLite)")
    args = parser.parse_args()

    if args.agendar or args.desagendar:
        try:
            print(agendamento.desagendar(args.banco) if args.desagendar else agendamento.agendar(args.agendar, args.banco))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
            print(f"Não consegui: {e}")
            sys.exit(1)
        return

    conexao = banco.conectar(args.banco)
    if args.sincronizar:
        sys.exit(agendamento.rotina_diaria(conexao))

    try:
        servidor = criar_servidor(conexao, args.porta)
    except OSError:
        url = f"http://127.0.0.1:{args.porta}"
        print(f"A porta {args.porta} já está em uso — o Open Balance provavelmente já está aberto ({url}).")
        if not args.sem_navegador:
            webbrowser.open(url)
        sys.exit(1)

    try:
        copia = backup.backup_do_dia(conexao)
        if copia:
            print(f"Cópia de segurança do dia: {copia}")
    except Exception as e:  # noqa: BLE001 — sem a cópia do dia, o painel abre do mesmo jeito
        print(f"Aviso: não consegui fazer a cópia de segurança do dia ({type(e).__name__}: {e}).")

    url = f"http://127.0.0.1:{args.porta}"
    print(f"Open Balance rodando em {url}  (feche esta janela ou Ctrl+C para sair)")
    if not args.sem_navegador:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDesligando…")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
