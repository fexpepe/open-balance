"""Rotina diária (python app.py --sincronizar) e a tarefa do Windows que a roda sozinha (--agendar).

A rotina faz a cópia de segurança, puxa os dados da Pluggy, guarda o valor do dia da carteira e baixa as
cotações, para a evolução do patrimônio e a aba Rentabilidade já abrirem prontas.
Como a tarefa roda sem janela, tudo vai também para sincronizacao.log, ao lado do banco, e o resultado de cada
etapa fica na tabela rotinas, que o painel lê para avisar quando algo deu errado (saude.py).
"""

import re
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import analise, backup, banco, historico, sincronizar
from .banco import arquivo, para_json
from .config import ARQUIVO_BANCO, RAIZ, pluggy_configurado

NOME_TAREFA = "Open Balance - sincronizar"
LIMITE_LOG = 200_000  # bytes; acima disso o log fica só com as linhas mais recentes
DESAGENDADA = "desligada"  # preferência rotina_agendada depois do --desagendar (senão, o horário do --agendar)


# ============================================================================ rotina diária
def rotina_diaria(conexao):
    """Devolve o código de saída: 0 se tudo deu certo, 1 se alguma etapa falhou (as outras rodam mesmo assim)."""
    log = _abrir_log(arquivo(conexao).with_name("sincronizacao.log"))
    log("Início da rotina diária")
    registro = _Registro(conexao)
    ok = _etapa("Cópia de segurança", lambda: _copia(conexao), log, registro)
    if pluggy_configurado():
        ok &= _etapa("Sincronização", lambda: _sincronizacao(conexao, log), log, registro)
    else:
        log("Sincronização: Pluggy não configurada (os dados entram pela aba Importar)")
    ok &= _etapa("Carteira", lambda: _valor_do_dia(conexao), log, registro)
    ok &= _etapa("Cotações", lambda: _cotacoes(conexao), log, registro)
    registro.fim(ok)
    log("Fim: tudo certo" if ok else "Fim: com falhas (veja acima)")
    return 0 if ok else 1


def _etapa(nome, funcao, log, registro):
    try:
        texto, ok = funcao(), True
        log(f"{nome}: {texto}")
    except Exception as e:  # noqa: BLE001 — uma etapa que falha não impede as outras
        texto, ok = f"{type(e).__name__}: {e}", False
        log(f"{nome}: falhou — {texto}")
    registro.etapa(nome, ok, texto)
    return ok


class _Registro:
    """A rotina na tabela rotinas, gravada etapa a etapa: se ela for interrompida, fica sem fim e o painel avisa."""

    def __init__(self, conexao):
        self.conexao, self.etapas = conexao, []
        with conexao:
            self.id = conexao.execute("INSERT INTO rotinas (inicio, etapas) VALUES (?, '[]')",
                                      (sincronizar.agora(),)).lastrowid

    def etapa(self, nome, ok, texto):
        self.etapas.append({"nome": nome, "ok": ok, "texto": str(texto)})
        with self.conexao:
            self.conexao.execute("UPDATE rotinas SET etapas = ? WHERE id = ?", (para_json(self.etapas), self.id))

    def fim(self, ok):
        with self.conexao:
            self.conexao.execute("UPDATE rotinas SET fim = ?, ok = ? WHERE id = ?", (sincronizar.agora(), int(ok), self.id))


def _copia(conexao):
    copia = backup.backup_do_dia(conexao)
    return copia.name if copia else "a de hoje já existia"


def _sincronizacao(conexao, log):
    resumo = sincronizar.sincronizar(conexao, log=log)
    lidas = sum(i["transacoes"] for i in resumo["itens"])
    texto = f"{len(resumo['itens'])} instituição(ões), {lidas} transações lidas"
    if resumo["erros"]:
        raise RuntimeError(f"{texto}, com avisos: {' · '.join(resumo['erros'])}")
    return texto


def _valor_do_dia(conexao):
    dados = analise.montar(conexao)  # a carteira grava o valor do dia ao ser montada
    a_receber = dados["carteira"]["proventos"]["aReceber"]
    if not a_receber["total"]:
        return "valor do dia guardado"
    reais = f"R$ {a_receber['total']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"valor do dia guardado; proventos anunciados a receber: {reais}"


def _cotacoes(conexao):
    erros = []
    historico.atualizar_fontes(conexao, lambda erro=None, **_: erro and erros.append(erro))
    if erros:
        raise RuntimeError("; ".join(erros))
    return "em dia"


def _abrir_log(caminho):
    if caminho.exists() and caminho.stat().st_size > LIMITE_LOG:
        linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
        caminho.write_text("\n".join(linhas[len(linhas) // 2:]) + "\n", encoding="utf-8")

    def log(texto):
        print(texto)
        with caminho.open("a", encoding="utf-8") as saida:
            saida.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {texto}\n")
    return log


# ============================================================================ tarefa agendada (Windows)
def agendar(horario, arquivo_banco=ARQUIVO_BANCO):
    """Cria (ou refaz) a tarefa que roda a rotina todo dia no horário. Devolve a mensagem para a tela."""
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", horario or ""):
        raise ValueError(f"horário inválido: {horario} (use HH:MM, ex.: 08:00)")
    executavel = Path(sys.executable)
    if executavel.with_name("pythonw.exe").exists():
        executavel = executavel.with_name("pythonw.exe")  # roda sem abrir janela
    argumentos = f'"{RAIZ / "app.py"}" --sincronizar'
    if Path(arquivo_banco).resolve() != ARQUIVO_BANCO.resolve():
        argumentos += f' --banco "{Path(arquivo_banco).resolve()}"'
    _powershell(
        f"$acao = New-ScheduledTaskAction -Execute {_texto_ps(executavel)} -Argument {_texto_ps(argumentos)} "
        f"-WorkingDirectory {_texto_ps(RAIZ)}",
        f"$quando = New-ScheduledTaskTrigger -Daily -At {_texto_ps(horario)}",
        # StartWhenAvailable: se o computador estiver desligado no horário, roda assim que for ligado.
        "$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {_texto_ps(NOME_TAREFA)} -Action $acao -Trigger $quando -Settings $config "
        f"-Description {_texto_ps('Open Balance: cópia de segurança, sincronização com a Pluggy e cotações do dia.')} "
        "-Force | Out-Null")
    _anotar_agendamento(arquivo_banco, horario)
    log = Path(arquivo_banco).resolve().with_name("sincronizacao.log")
    return (f"Agendado: todo dia às {horario} (ou assim que o computador ligar, se estiver desligado nessa hora).\n"
            f"Tarefa \"{NOME_TAREFA}\" no Agendador de Tarefas do Windows. Se uma execução falhar, o painel avisa no topo; "
            f"o passo a passo de cada uma vai para {log}.")


def desagendar(arquivo_banco=ARQUIVO_BANCO):
    _powershell(f"Get-ScheduledTask -TaskName {_texto_ps(NOME_TAREFA)} -ErrorAction SilentlyContinue | "
                "Unregister-ScheduledTask -Confirm:$false")
    _anotar_agendamento(arquivo_banco, DESAGENDADA)
    return f"Tarefa \"{NOME_TAREFA}\" removida (se existia)."


def _anotar_agendamento(arquivo_banco, valor):
    """Para o painel saber se deve cobrar a rotina que parou de rodar."""
    with closing(banco.conectar(arquivo_banco)) as conexao:
        banco.gravar_preferencia(conexao, "rotina_agendada", valor)


def _texto_ps(valor):
    """Texto literal do PowerShell (aspas simples; a única coisa a escapar é a própria aspa)."""
    return "'" + str(valor).replace("'", "''") + "'"


def _powershell(*comandos):
    if sys.platform != "win32":
        raise RuntimeError("o agendamento automático é só para Windows; em outros sistemas, agende "
                           "'python app.py --sincronizar' no cron")
    script = "; ".join(["$ErrorActionPreference = 'Stop'", "[Console]::OutputEncoding = [Text.Encoding]::UTF8", *comandos])
    resultado = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if resultado.returncode:
        raise RuntimeError((resultado.stderr or resultado.stdout).strip()[:500] or "o PowerShell recusou o comando")
