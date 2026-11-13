// Situação da rotina diária e das conexões: um indicador discreto no topo, ao lado do "Atualizado…".
// Tudo certo: só um ponto verde. Com aviso: o motivo (ou quantos são), em âmbar ou vermelho.
// Clicar abre o painel com os avisos, as etapas da última rotina e, com Pluggy, cada instituição
// (quando a Pluggy atualizou e até quando vale o consentimento). Os avisos vêm prontos do servidor (saude.py).
import { esc, horaRelativa } from "./util.js";

const ESTADOS = { ok: "tudo certo", falha: "com falhas", rodando: "rodando agora", interrompida: "não terminou" };
let desenhado = null;

export function atualizarSaude(dados) {
  const raiz = document.getElementById("saude");
  const s = dados.saude;
  if (!raiz || s === desenhado) return; // o topo é refeito a cada troca de aba; só redesenha com dados novos
  desenhado = s;
  raiz.hidden = !s || !(s.rotina.ultima || s.rotina.agendada || s.instituicoes.length);
  if (raiz.hidden) return;
  iniciar(raiz);

  const nivel = s.avisos.some((a) => a.nivel === "erro") ? "erro" : s.avisos.length ? "alerta" : "ok";
  const rotulo = s.avisos.length === 1 ? s.avisos[0].curto : s.avisos.length ? `${s.avisos.length} avisos` : "";
  const aberto = raiz.querySelector(".saude-painel")?.hidden === false;
  const titulo = nivel === "ok" ? "Rotina diária e conexões em dia" : "Ver o que precisa de atenção";
  raiz.innerHTML = `<button type="button" class="saude-botao ${nivel}" aria-expanded="${aberto}" aria-controls="saude-painel"
      title="${titulo}" aria-label="${esc(rotulo || titulo)}">
      <span class="saude-ponto" aria-hidden="true"></span>${rotulo ? `<span class="saude-rotulo">${esc(rotulo)}</span>` : ""}</button>
    <div class="saude-painel" id="saude-painel" ${aberto ? "" : "hidden"}>${painel(s)}</div>`;
}

function painel(s) {
  return `${s.avisos.map((a) => `<div class="saude-aviso ${a.nivel}">${esc(a.texto)}</div>`).join("")}
    <section><div class="rotulo">Rotina diária</div>${rotina(s.rotina)}</section>
    ${s.instituicoes.length ? `<section><div class="rotulo">Open Finance (Pluggy)</div>
      <ul class="saude-lista">${s.instituicoes.map(instituicao).join("")}</ul></section>` : ""}
    <p class="mudo saude-rodape">O passo a passo de cada execução fica em dados/sincronizacao.log.</p>`;
}

function rotina(r) {
  const agenda = r.agendada === "desligada" ? "desligada (--desagendar)" : r.agendada ? `agendada todo dia às ${r.agendada}` : "";
  if (!r.ultima) {
    return `<p class="mudo">${agenda ? `${esc(agenda[0].toUpperCase() + agenda.slice(1))}; ainda não rodou.`
      : "Ainda não rodou neste banco. Para ela rodar sozinha todo dia (cópia de segurança, Pluggy e cotações): <code>python app.py --agendar</code>"}</p>`;
  }
  const u = r.ultima;
  const etapas = u.etapas.map((e) => `<li class="${e.ok ? "ok" : "falha"}">
      <span class="saude-marca" aria-label="${e.ok ? "ok" : "falhou"}">${e.ok ? "✓" : "✕"}</span>
      <span><b>${esc(e.nome)}</b> <span class="saude-texto">${esc(e.texto)}</span></span></li>`).join("");
  return `<p>Última: ${esc(horaRelativa(u.inicio))} · <span class="saude-estado ${u.estado}">${ESTADOS[u.estado]}</span>${agenda ? `<span class="mudo"> · ${esc(agenda)}</span>` : ""}</p>
    ${etapas ? `<ul class="saude-lista saude-etapas">${etapas}</ul>` : ""}`;
}

function instituicao(i) {
  const vence = i.consentimentoExpira ? new Date(i.consentimentoExpira).toLocaleDateString("pt-BR") : null;
  const perto = i.diasConsentimento !== null && i.diasConsentimento <= 30;
  return `<li><span><b>${esc(i.nome)}</b> <span class="saude-texto">dados da Pluggy de ${esc(horaRelativa(i.atualizadoEm))}${vence
    ? ` · <span class="${perto ? "saude-perto" : ""}">consentimento até ${vence}</span>` : ""}</span></span></li>`;
}

// Abre e fecha pelo botão; fecha com Esc ou clicando fora. Os ouvintes ficam na raiz, que não é recriada.
function iniciar(raiz) {
  if (raiz.dataset.iniciado) return;
  raiz.dataset.iniciado = "1";
  const abrir = (sim) => {
    const botao = raiz.querySelector(".saude-botao");
    const painelEl = raiz.querySelector(".saude-painel");
    if (!botao || !painelEl) return;
    painelEl.hidden = !sim;
    botao.setAttribute("aria-expanded", String(sim));
  };
  raiz.addEventListener("click", (e) => {
    if (e.target.closest(".saude-botao")) abrir(raiz.querySelector(".saude-painel").hidden);
  });
  document.addEventListener("click", (e) => { if (!raiz.contains(e.target)) abrir(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") abrir(false); });
}
