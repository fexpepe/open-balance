"""Situação da rotina diária e das conexões, para o painel avisar quando algo deu errado.

- Rotina diária (agendamento.py): a última terminou com falhas, foi interrompida no meio ou não roda há mais
  de um dia. Só entra depois que ela rodou alguma vez neste banco; depois do --desagendar, deixa de cobrar.
- Conexões da Pluggy: quando a Pluggy atualizou cada instituição pela última vez, conexão com problema e o
  vencimento do consentimento do Open Finance (aviso a partir de 30 dias antes).

Sem Pluggy configurada (só arquivos importados), fica só a parte da rotina.
"""

import json
from datetime import datetime, timedelta

from .agendamento import DESAGENDADA, NOME_TAREFA
from .analise import itens_visiveis
from .banco import preferencia
from .config import pluggy_configurado

ATRASO_ROTINA = timedelta(hours=26)  # roda todo dia; a folga cobre o computador ligado depois do horário
DURACAO_MAXIMA = timedelta(minutes=40)  # a tarefa agendada é encerrada aos 30 minutos
AVISO_CONSENTIMENTO = 30  # dias antes do vencimento
DIAS_SEM_DADOS = 3  # a Pluggy atualiza as conexões do MeuPluggy uma vez por dia
STATUS_COM_PROBLEMA = {
    "LOGIN_ERROR": "a conexão perdeu o acesso ao banco; reconecte a instituição no MeuPluggy (meu.pluggy.ai)",
    "OUTDATED": "a última atualização feita pela Pluggy falhou; os dados podem estar defasados",
    "WAITING_USER_INPUT": "a Pluggy está esperando uma ação sua no MeuPluggy (meu.pluggy.ai)",
    "WAITING_USER_ACTION": "a Pluggy está esperando uma ação sua no MeuPluggy (meu.pluggy.ai)",
}


def montar(conexao, agora=None):
    """{"rotina", "instituicoes", "avisos"}. Cada aviso tem nível (erro ou alerta), um texto curto para o topo e o completo."""
    agora = agora or datetime.now().astimezone()
    avisos = []
    rotina = _rotina(conexao, agora, avisos)
    instituicoes = _instituicoes(conexao, agora, avisos) if pluggy_configurado() else []
    return {"rotina": rotina, "instituicoes": instituicoes, "avisos": avisos}


def _aviso(nivel, curto, texto):
    return {"nivel": nivel, "curto": curto, "texto": texto}


def _rotina(conexao, agora, avisos):
    agendada = preferencia(conexao, "rotina_agendada")  # horário do --agendar, DESAGENDADA ou nada (antes desta versão)
    linha = conexao.execute("SELECT inicio, fim, ok, etapas FROM rotinas ORDER BY id DESC LIMIT 1").fetchone()
    if not linha:
        return {"agendada": agendada, "ultima": None}
    inicio = _data(linha["inicio"])
    etapas = json.loads(linha["etapas"] or "[]")
    if linha["fim"]:
        estado = "ok" if linha["ok"] else "falha"
    else:
        estado = "rodando" if agora - inicio < DURACAO_MAXIMA else "interrompida"

    quando = _quando(inicio, agora)
    if estado == "falha":
        falhas = ", ".join(e["nome"] for e in etapas if not e["ok"])
        avisos.append(_aviso("erro", "Rotina com falha",
                             f"A rotina diária de {quando} terminou com falha{f' em: {falhas}' if falhas else ''}."))
    elif estado == "interrompida":
        avisos.append(_aviso("erro", "Rotina interrompida",
                             f"A rotina diária de {quando} não terminou (o computador desligou no meio ou ela passou de 30 minutos)."))
    if agendada != DESAGENDADA and agora - inicio > ATRASO_ROTINA:
        avisos.append(_aviso("alerta", "Rotina parada",
                             f"A rotina diária não roda desde {quando}. Confira a tarefa “{NOME_TAREFA}” no Agendador de Tarefas "
                             "do Windows ou agende de novo com python app.py --agendar (para desligar de vez: --desagendar)."))
    return {"agendada": agendada, "ultima": {"inicio": linha["inicio"], "fim": linha["fim"], "estado": estado, "etapas": etapas}}


def _instituicoes(conexao, agora, avisos):
    sinc = conexao.execute("SELECT fim FROM sincronizacoes ORDER BY id DESC LIMIT 1").fetchone()
    ultima_sinc = _data(sinc["fim"]) if sinc else None
    itens = sorted((i for i in itens_visiveis(conexao).values() if i["origem"] == "pluggy"),
                   key=lambda i: i["instituicao"] or "")
    lista = []
    for item in itens:
        nome = item["instituicao"] or "Instituição"
        atualizado, expira = _data(item["atualizado_em"]), _data(item["consentimento_expira"])
        dias = (expira.date() - agora.date()).days if expira else None

        problema = STATUS_COM_PROBLEMA.get(item["status"])
        if problema:
            avisos.append(_aviso("alerta", f"{nome}: conexão com problema", f"{nome}: {problema}."))
        # Compara com a última sincronização (e não com agora): sem sincronizar, a data guardada não anda mesmo.
        elif atualizado and ultima_sinc and ultima_sinc - atualizado > timedelta(days=DIAS_SEM_DADOS):
            avisos.append(_aviso("alerta", f"{nome} sem dados novos",
                                 f"{nome}: a Pluggy não traz dados novos desde {_quando(atualizado, agora)}. "
                                 "Confira a conexão no MeuPluggy (meu.pluggy.ai)."))

        if dias is not None and dias <= AVISO_CONSENTIMENTO:
            renovar = ("Renove a autorização no MeuPluggy (meu.pluggy.ai); se a instituição ganhar um Item ID novo, "
                       "troque em Importar → Conectar pelo Open Finance.")
            if dias < 0:
                avisos.append(_aviso("erro", "Consentimento vencido",
                                     f"{nome}: o consentimento do Open Finance venceu em {expira:%d/%m/%Y} "
                                     f"e os dados pararam de chegar. {renovar}"))
            else:
                prazo = "hoje" if dias == 0 else "amanhã" if dias == 1 else f"em {dias} dias"
                avisos.append(_aviso("alerta", f"Consentimento vence {prazo}",
                                     f"{nome}: o consentimento do Open Finance vence {prazo} ({expira:%d/%m/%Y}). {renovar}"))
        lista.append({"nome": nome, "status": item["status"], "atualizadoEm": item["atualizado_em"],
                      "consentimentoExpira": item["consentimento_expira"], "diasConsentimento": dias})
    return lista


def _data(texto):
    """ISO com ou sem fuso (a Pluggy manda em UTC, com Z) → horário local."""
    try:
        return datetime.fromisoformat(texto).astimezone() if texto else None
    except ValueError:
        return None


def _quando(momento, agora):
    dias = (agora.date() - momento.date()).days
    dia = "hoje" if dias == 0 else "ontem" if dias == 1 else f"{momento:%d/%m}" if momento.year == agora.year else f"{momento:%d/%m/%Y}"
    return f"{dia} às {momento:%H:%M}"
