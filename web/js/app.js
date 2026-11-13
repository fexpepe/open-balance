import { Base, impacto, INTERNAS } from "./dados.js";
import { desenharCalendario, desenharColunas, desenharLinhas, desenharRosca, esconderDica, linhaDica } from "./graficos.js";
import { iniciarPrivacidade } from "./privacidade.js";
import { telaImportar } from "./importar.js";
import { renderInvestimentos } from "./investimentos.js";
import { destaquePrevisao, telaPrevisao } from "./previsao.js";
import { resumoGenerico, telaRevisar } from "./revisar.js";
import { cartaoFechamentoTopo, cartaoOrcamentoVisao, destaquesOrcamento, ligarCartaoFechamento, telaFechamento, telaOrcamento } from "./orcamento.js";
import { atualizarSaude } from "./saude.js";
import {
  avatarInstituicao, avatarMarca, brl, brlSinal, compacto, corGrupo, dataBR, dataCurta, dataLonga, diaSemana, diasEntre,
  diasNoMes, esc, grupoTemCor, horaRelativa, iconeGrupo, mesDe, NATUREZAS, NATUREZAS_CURTAS, nomeMes, nomeMesCurto,
  nomeMesSo, pct, somarMeses,
} from "./util.js";

const estado = {
  dados: null,
  base: null,
  mes: null,
  filtros: { periodo: "mes", conta: "", tipo: "", categoria: "", ordem: "data-desc", busca: "", futuras: false, ocultas: false },
  limiteLinhas: 150,
  parcStatus: "ativo",
  parcOrdem: "restante",
  cartaoSel: null,
};
const conteudo = document.getElementById("conteudo");
const ABAS_COM_MES = new Set(["visao", "transacoes", "categorias", "revisar", "orcamento", "fechamento"]);

// ============================================================ API e carga
async function api(caminho, corpo) {
  const opcoes = corpo === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Open-Balance": "1" },
    body: JSON.stringify(corpo),
  };
  const resposta = await fetch(caminho, opcoes);
  const json = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error(json.erro || `HTTP ${resposta.status}`);
  return json;
}

async function carregar() {
  estado.dados = await api("/api/dados");
  estado.base = new Base(estado.dados);
  if (!estado.mes || estado.mes > estado.base.mesAtual) estado.mes = estado.base.mesAtual;
  atualizarTopo();
  render();
}

function avisar(texto, erro = false, duracao = erro ? 9000 : 4500) {
  const el = document.getElementById("aviso");
  el.textContent = texto;
  el.className = `aviso${erro ? " erro" : ""}`;
  el.hidden = false;
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => { el.hidden = true; }, duracao);
}

// Depois de atualizar: quanto de provento já anunciado vai cair (ações e FIIs, pela B3) e a estimativa dos FIIs.
function textoAReceber(a) {
  if (!a || (!a.total && !a.estimado)) return "";
  const proximo = a.proximo ? ` Próximo: ${a.proximo.codigo} ${brl(a.proximo.valor)} em ${dataBR(a.proximo.pagamento)}.` : "";
  const estimado = a.estimado ? ` FIIs que ainda não anunciaram: ~${brl(a.estimado)}.` : "";
  return ` Proventos a receber: ${brl(a.total)}${a.fiis ? ` (FIIs ${brl(a.fiis)})` : ""}.${proximo}${estimado}`;
}

async function sincronizar() {
  const botao = document.getElementById("botao-sinc");
  botao.disabled = true;
  botao.classList.add("carregando");
  botao.querySelector(".sinc-texto").textContent = "Atualizando…";
  try {
    const r = await api("/api/sincronizar", {});
    const total = r.itens.reduce((s, i) => s + i.transacoes, 0);
    await carregar();
    const consolidados = r.consolidados?.length ? ` Conexão antiga substituída pela nova: ${r.consolidados.join(", ")}.` : "";
    const proventos = textoAReceber(estado.dados.carteira?.proventos?.aReceber);
    if (r.erros.length) avisar(`Atualizado com avisos: ${r.erros.join(" · ")}${consolidados}${proventos}`, true);
    else avisar(`Atualizado: ${r.itens.length} instituição(ões), ${total} transações lidas.${consolidados}${proventos}`, false, proventos ? 9000 : undefined);
  } catch (e) {
    avisar(`Não consegui atualizar: ${e.message}`, true);
  } finally {
    botao.disabled = false;
    botao.classList.remove("carregando");
    botao.querySelector(".sinc-texto").textContent = "Atualizar";
  }
}

// ============================================================ topo e navegação
// Duas áreas: "Dia a dia" (#/visao, #/transacoes…) e "Investimentos" (#/investimentos/<sub-aba>).
// Importar é um atalho no topo, fora das duas.
function rota() {
  const [aba, sub] = location.hash.replace(/^#\/?/, "").split("?")[0].split("/");
  return { aba: aba || "visao", sub: sub || "" };
}
function abaAtual() { return rota().aba; }
const areaDe = (aba) => (aba === "investimentos" ? "investimentos" : "dia");
// Ao trocar de área, volta para a última aba visitada nela.
const ultimaRota = { dia: "#/visao", investimentos: "#/investimentos" };

function atualizarTopo() {
  const b = estado.base;
  const sinc = estado.dados.ultimaSincronizacao;
  const status = document.getElementById("sinc-status");
  // Sem Pluggy configurada, não há o que sincronizar: o topo mostra a última importação de arquivo.
  document.getElementById("botao-sinc").style.display = estado.dados.pluggy ? "" : "none";
  if (estado.dados.pluggy) {
    const dataSinc = sinc?.fim ? sinc.fim.slice(0, 10) : null;
    status.textContent = sinc ? `Atualizado ${horaRelativa(sinc.fim)}` : "Ainda não sincronizado";
    status.classList.toggle("velho", !dataSinc || dataSinc < b.hoje);
  } else {
    const ultima = estado.dados.importacoes[0];
    status.textContent = ultima ? `Último arquivo importado ${horaRelativa(ultima.criada_em)}` : "Nenhum arquivo importado";
    status.classList.toggle("velho", !ultima || diasEntre(ultima.criada_em.slice(0, 10), b.hoje) > 35);
  }
  atualizarSaude(estado.dados);
  document.getElementById("rotulo-mes").textContent = nomeMes(estado.mes);
  const [anterior, proximo] = document.querySelectorAll("#seletor-mes button");
  anterior.disabled = estado.mes <= b.primeiroMes;
  proximo.disabled = estado.mes >= b.mesAtual;
  const { aba, sub } = rota();
  const area = areaDe(aba);
  const subAtiva = aba === "investimentos" ? sub || "resumo" : "";
  if (aba !== "importar") ultimaRota[area] = location.hash || "#/visao";
  document.getElementById("seletor-mes").classList.toggle("oculto", !ABAS_COM_MES.has(aba));
  document.querySelectorAll("#areas a").forEach((a) => {
    a.classList.toggle("ativa", aba !== "importar" && a.dataset.area === area);
    a.href = ultimaRota[a.dataset.area];
  });
  document.querySelectorAll("#abas a").forEach((a) => {
    a.hidden = a.dataset.area !== area;
    a.classList.toggle("ativa", a.dataset.aba === aba && (a.dataset.sub || "") === subAtiva);
  });
  document.getElementById("link-importar").classList.toggle("ativo", aba === "importar");
}

function render() {
  if (!estado.base) return;
  atualizarTopo();
  const aba = abaAtual();
  if (aba !== "importar" && !estado.dados.transacoes.length && !estado.dados.contas.length) return telaVazia();
  (TELAS[aba] || TELAS.visao)();
}

function telaVazia() {
  conteudo.innerHTML = `<div class="vazio"><h2>Bem-vindo ao Open Balance</h2>
    <p>Para começar, exporte o extrato da conta e a fatura do cartão no app ou site do seu banco (OFX, CSV ou Excel)<br>
      e envie na aba <b>Importar</b>. Dá para repetir todo mês: o que já foi importado não duplica.</p>
    <p style="margin-top:18px"><a class="botao botao-acento" href="#/importar" style="text-decoration:none">Importar arquivos</a></p>
    ${estado.dados.pluggy ? `<p class="mudo">Ou clique em <b>Atualizar</b> para puxar suas contas pela Pluggy.</p>`
      : `<p class="mudo">Prefere automático? Na mesma aba dá para <a class="link" href="#/importar">conectar seus bancos pelo Open Finance (Pluggy)</a> — tem um passo a passo lá.</p>`}</div>`;
}

// ============================================================ peças reutilizáveis
const cartao = (classe, html) => `<div class="cartao ${classe}">${html}</div>`;
const topoCartao = (rotulo, direita = "") => `<div class="cartao-topo"><span class="rotulo">${esc(rotulo)}</span>${direita}</div>`;
const tile = (rotulo, valor, detalhe = "", classeValor = "") =>
  `<div class="tile"><div class="rotulo">${esc(rotulo)}</div><div class="valor ${classeValor}">${valor}</div>${detalhe ? `<div class="detalhe">${detalhe}</div>` : ""}</div>`;

function pilulaVariacao(variacao, maiorEhRuim = true) {
  if (variacao === null || !isFinite(variacao)) return `<span class="pilula neutra">sem base</span>`;
  const ruim = maiorEhRuim ? variacao > 0 : variacao < 0;
  const seta = variacao > 0 ? "↑" : variacao < 0 ? "↓" : "→";
  return `<span class="pilula ${Math.abs(variacao) < 0.5 ? "neutra" : ruim ? "ruim" : "bom"}">${seta} ${pct(Math.abs(variacao)).replace("+", "")}</span>`;
}

function etiquetaCategoria(catId) {
  const b = estado.base;
  const g = b.grupoDe(catId);
  return `<span class="etiqueta"><span class="ponto" style="background:${corGrupo(g)}"></span>${esc(b.categoria(catId).nome)}</span>`;
}

function valorTransacao(t) {
  const classe = t.entrada ? "positivo" : "";
  return `<span class="num ${classe}">${t.entrada ? "+" : "−"}${brl(t.valor)}</span>`;
}

function iconeTransacao(t) {
  if (t.marca) return avatarMarca(t.marca).replace('class="avatar"', 'class="avatar pequeno"');
  return `<span class="icone-cat">${iconeGrupo(estado.base.grupoDe(t.categoriaId))}</span>`;
}

function irPara(aba, filtros = {}) {
  Object.assign(estado.filtros, filtros);
  location.hash = `#/${aba}`;
}

// ============================================================ VISÃO GERAL
function telaVisao() {
  const b = estado.base;
  const d = estado.dados;
  const mes = estado.mes;
  const atual = mes === b.mesAtual;
  const tot = b.totais(b.doMes(mes));
  const comp = b.mesmoPeriodoAnterior(mes);
  const variacao = comp.despesas ? (tot.despesas / comp.despesas - 1) * 100 : null;
  const { cats } = b.porCategoria(mes);
  const catsAnt = b.porCategoria(somarMeses(mes, -1)).cats;
  const ranking = [...cats].filter(([, v]) => v > 0).sort((a, z) => z[1] - a[1]);
  const maior = ranking[0];
  const contasBanco = d.contas.filter((c) => c.tipo === "BANK");
  const cartoes = d.cartoes;
  const ativos = d.parcelamentos.filter((p) => p.status === "ativo");
  const assinaturas = d.recorrentes.filter((r) => r.tipo === "assinatura");
  const mesNome = nomeMesSo(mes);
  const mesAntNome = nomeMesSo(comp.mes);

  // --- destaques escritos
  const destaques = [];
  if (variacao !== null) {
    const sentido = variacao > 0 ? "a mais" : "a menos";
    destaques.push(`Você gastou <b>${brl(tot.despesas)}</b> em ${mesNome}${atual ? " até hoje" : ""}, <b>${pct(Math.abs(variacao)).replace("+", "")} ${sentido}</b> que ${comp.completo ? `em ${mesAntNome}` : `no mesmo período de ${mesAntNome}`}.`);
  } else {
    destaques.push(`Você gastou <b>${brl(tot.despesas)}</b> em ${mesNome}${atual ? " até hoje" : ""}.`);
  }
  if (maior) destaques.push(`<b>${esc(b.categoria(maior[0]).nome)}</b> é a maior despesa do mês: ${brl(maior[1])} (${Math.round((maior[1] / tot.despesas) * 100)}% do total).`);
  destaques.push(...destaquesOrcamento(estado, mes));
  const cartaoAberto = cartoes.filter((c) => c.faturaAberta.valor > 0).sort((a, z) => z.faturaAberta.valor - a.faturaAberta.valor)[0];
  if (cartaoAberto) destaques.push(`Fatura do <b>${esc(cartaoAberto.nome)}</b> vence em ${dataCurta(cartaoAberto.faturaAberta.vencimento)}: <b>${brl(cartaoAberto.faturaAberta.valor)}</b> estimados até agora.`);
  if (ativos.length) destaques.push(`<b>${ativos.length} compras parceladas</b> em andamento; ainda faltam ${brl(ativos.reduce((s, p) => s + p.restante, 0))}.`);
  if (atual && d.previsao) destaques.push(destaquePrevisao(d.previsao));

  // --- recentes
  const recentes = b.doMes(mes).slice().sort((a, z) => (z.data + z.id).localeCompare(a.data + a.id)).slice(0, 7);
  let diaAnterior = "";
  const linhasRecentes = recentes.map((t) => {
    const cab = t.data !== diaAnterior ? `<li class="mudo" style="border:0;padding:12px 0 2px;font-size:11px;letter-spacing:.06em;text-transform:uppercase">${t.data === b.hoje ? "Hoje" : diasEntre(t.data, b.hoje) === 1 ? "Ontem" : esc(dataLonga(t.data))}</li>` : "";
    diaAnterior = t.data;
    return `${cab}<li>${iconeTransacao(t)}<div class="meio"><div class="titulo">${esc(t.descricao)}</div></div>
      ${INTERNAS.has(t.natureza) ? `<span class="etiqueta">${NATUREZAS_CURTAS[t.natureza]}</span>` : etiquetaCategoria(t.categoriaId)}
      <div class="direita" style="min-width:110px">${valorTransacao(t)}</div></li>`;
  }).join("");

  // --- categorias (tabela)
  const linhasCat = ranking.slice(0, 6).map(([cat, v]) => {
    const ant = catsAnt.get(cat) || 0;
    const varCat = ant ? (v / ant - 1) * 100 : null;
    const g = b.grupoDe(cat);
    return `<tr data-cat="${esc(cat)}" style="cursor:pointer">
      <td><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${corGrupo(g)}"></span>${iconeGrupo(g)} ${esc(b.categoria(cat).nome)}</span></td>
      <td class="direita num"><b>${brl(v)}</b></td>
      <td style="width:28%"><div class="trilho"><span style="width:${(v / ranking[0][1]) * 100}%;background:${corGrupo(g)}"></span></div></td>
      <td class="direita">${pilulaVariacao(varCat)}</td>
      <td class="direita num mudo">${ant ? brl(ant) : "—"}</td></tr>`;
  }).join("");

  const totalContas = contasBanco.reduce((s, c) => s + c.saldo, 0);
  const totalDisponivel = cartoes.reduce((s, c) => s + (c.disponivel || 0), 0);
  const totalLimite = cartoes.reduce((s, c) => s + (c.limite || 0), 0);
  const dias = b.porDia(mes);
  const diasComGasto = atual ? Number(b.hoje.slice(8, 10)) : dias.length;
  const maiorDia = dias.reduce((m, x) => (x.total > (m?.total || 0) ? x : m), null);
  const totalAssin = assinaturas.reduce((s, r) => s + r.valor, 0);

  const fechamentoTopo = cartaoFechamentoTopo(estado, { cartao });
  conteudo.innerHTML = `
    ${fechamentoTopo ? `<section class="grade">${fechamentoTopo}</section>` : ""}
    <section class="grade">
      ${cartao("c7 saudacao", `
        <h1>Olá${d.titular ? `, ${esc(d.titular)}` : ""}!</h1>
        <div class="sub">Seu resumo de ${esc(nomeMes(mes))}</div>
        <ul class="destaques">${destaques.map((x) => `<li><span>${x}</span></li>`).join("")}</ul>
        <div class="tiles">
          ${tile(`Gasto em ${mesNome}`, brl(tot.despesas), atual ? `até ${dataCurta(b.hoje)}` : "mês fechado")}
          ${tile(`vs ${mesAntNome}`, variacao === null ? "—" : `${variacao > 0 ? "↑" : "↓"} ${pct(Math.abs(variacao)).replace("+", "")}`, comp.completo ? "mês inteiro" : `mesmo período (até dia ${comp.dia})`, variacao > 0 ? "negativo" : "positivo")}
          ${tile("Maior categoria", maior ? `${iconeGrupo(b.grupoDe(maior[0]))} ${esc(b.categoria(maior[0]).nome)}` : "—", maior ? brl(maior[1]) : "")}
        </div>`)}
      ${cartao("c5", `
        ${topoCartao("Ritmo de gastos", `<a class="link" href="#/transacoes">ver todas ↗</a>`)}
        <div class="heroi">${brl(tot.despesas)}</div>
        <div class="sub">${pilulaVariacao(variacao)} vs ${brl(comp.despesas)} ${comp.completo ? `em ${mesAntNome}` : `no mesmo período de ${mesAntNome}`}</div>
        <div id="g-ritmo" style="margin-top:12px"></div>
        <div class="legenda"><span><i style="background:var(--acento)"></i>${esc(mesNome)}</span><span><i style="background:var(--texto-3)"></i>${esc(mesAntNome)}</span></div>`)}
    </section>

    <section class="grade">
      ${cartao("c12", `<div class="tiles">
        ${tile("Entradas", brl(tot.receitas + tot.rendimentos), tot.rendimentos > 0.01 ? `inclui ${brl(tot.rendimentos)} de rendimentos` : "salário, Pix recebidos…", "positivo")}
        ${tile("Saídas (despesas)", brl(tot.despesas), "sem contar faturas pagas e aplicações")}
        ${tile("Resultado do mês", brlSinal(tot.resultado), "entradas − despesas", tot.resultado >= 0 ? "positivo" : "negativo")}
        ${tile("Investido no mês (líquido)", brlSinal(tot.investidoLiquido), `aplicado ${compacto(tot.aplicado)} · resgatado ${compacto(tot.resgatado)}`)}
        ${d.emprestimos.length ? tile("Emprestado a terceiros", brl(d.emprestimos.reduce((s, p) => s + p.saldo, 0)), `a receber · <a class="link" href="#/investimentos/movimentacoes">detalhes</a>`) : ""}
      </div>`)}
    </section>

    <section class="grade">${cartaoOrcamentoVisao(estado, { cartao, topoCartao })}</section>

    <section class="grade">
      ${cartao("c6", `
        ${topoCartao("Contas correntes")}
        <div class="heroi">${brl(totalContas)} <small>saldo total</small></div>
        <ul class="lista">${contasBanco.map((c) => `<li>${avatarInstituicao(c.instituicao)}<div class="meio"><div class="titulo">${esc(c.nome)}</div><div class="linha2">${esc(c.subtipo)}${c.final ? ` · final ${esc(c.final)}` : ""}</div></div><div class="direita num">${c.semSaldo ? `<span class="mudo" title="Saldo não informado: defina em Importar → Editar">—</span>` : `<b>${brl(c.saldo)}</b>`}</div></li>`).join("")}</ul>
        <div class="rodape-cartao"><span>${contasBanco.length} conta(s)</span></div>`)}
      ${cartao("c6", `
        ${topoCartao("Limite total disponível", `<a class="link" href="#/cartoes">cartões ↗</a>`)}
        <div class="heroi">${totalLimite ? brl(totalDisponivel) : "—"}</div>
        <div class="sub">${totalLimite ? `de ${brl(totalLimite)} de limite total` : `limite não informado · <a class="link" href="#/importar">informar em Importar</a>`}</div>
        <ul class="lista">${cartoes.map((c) => `<li>${avatarInstituicao(c.instituicao)}<div class="meio"><div class="titulo">${esc(c.nome)}</div><div class="linha2">•••• ${esc(c.final)}${c.faturaAberta.vencimento ? ` · vence ${dataCurta(c.faturaAberta.vencimento)}` : ""}</div></div><div class="direita"><div class="num"><b>${c.disponivel === null ? "—" : brl(c.disponivel)}</b></div><div class="linha2 mudo">${c.disponivel === null ? "limite não informado" : c.disponivelEstimado ? "disponível (estimado)" : "disponível"}</div></div></li>`).join("")}</ul>`)}
    </section>

    <section class="grade">
      ${cartao("c5", `
        ${topoCartao("Mapa de calor", `<a class="link" href="#/transacoes">ver mais ↗</a>`)}
        <div class="heroi">${brl(tot.despesas)}</div>
        <div class="sub">Média diária: <b>${brl(tot.despesas / Math.max(1, diasComGasto))}</b></div>
        <div id="g-calor"></div>
        ${maiorDia ? `<div class="rodape-cartao"><span>Maior gasto</span><span><b class="negativo">${brl(maiorDia.total)}</b> dia ${maiorDia.dia}</span></div>` : ""}`)}
      ${cartao("c7", `
        ${topoCartao("Principais categorias", `<a class="link" href="#/categorias">ver mais ↗</a>`)}
        <div class="tabela-envolve"><table class="tabela" id="t-cats"><thead><tr><th>Categoria</th><th class="direita">Atual</th><th>Proporção</th><th class="direita">Variação</th><th class="direita">${esc(nomeMesCurto(somarMeses(mes, -1)))}</th></tr></thead>
        <tbody>${linhasCat || `<tr><td colspan="5" class="mudo">Sem despesas neste mês.</td></tr>`}</tbody></table></div>`)}
    </section>

    <section class="grade">
      ${cartao("c7", `${topoCartao("Transações recentes", `<a class="link" href="#/transacoes">ver todas ↗</a>`)}<ul class="lista">${linhasRecentes || `<li class="mudo">Nenhuma transação neste mês.</li>`}</ul>`)}
      ${cartao("c5", `
        ${topoCartao("Assinaturas", `<a class="link" href="#/assinaturas">ver todas ↗</a>`)}
        <div class="heroi">${brl(totalAssin)} <small>/mês · ${assinaturas.length} ativas</small></div>
        <ul class="lista">${assinaturas.slice(0, 4).map((r) => `<li>${avatarMarca(r.nome)}<div class="meio"><div class="titulo">${esc(r.nome)}</div><div class="linha2">Próxima: ${dataCurta(r.proxima)}</div></div><div class="direita num"><b>${brl(r.valor)}</b></div></li>`).join("")}</ul>
        ${assinaturas.length > 4 ? `<div class="rodape-cartao"><span>+${assinaturas.length - 4} assinaturas</span><a class="link" href="#/assinaturas">ver todas ↗</a></div>` : ""}`)}
    </section>`;

  // gráficos
  const anterior = somarMeses(mes, -1);
  const serieAtual = b.acumulado(mes);
  const serieAnterior = b.acumulado(anterior);
  const n = Math.max(diasNoMes(mes), diasNoMes(anterior));
  desenharLinhas(document.getElementById("g-ritmo"), {
    n,
    series: [
      { nome: mesNome, valores: serieAtual, cor: "var(--acento)" },
      { nome: mesAntNome, valores: serieAnterior, cor: "var(--texto-3)", fraca: true },
    ],
    dica: (i) => `<div class="t">Dia ${i + 1}</div>${serieAtual[i] !== undefined ? linhaDica("var(--acento)", mesNome, brl(serieAtual[i])) : ""}${serieAnterior[i] !== undefined ? linhaDica("var(--texto-3)", mesAntNome, brl(serieAnterior[i])) : ""}`,
  });
  desenharCalendario(document.getElementById("g-calor"), {
    dias: dias.map((x) => ({
      ...x,
      dica: `<div class="t">${esc(dataLonga(`${mes}-${String(x.dia).padStart(2, "0")}`))}</div>${linhaDica(null, "Gasto no dia", brl(x.total))}${x.txs.sort((a, z) => impacto(z) - impacto(a)).slice(0, 3).map((t) => linhaDica(null, t.descricao.slice(0, 26), brl(impacto(t)))).join("")}`,
    })),
    primeiroDiaSemana: diaSemana(`${mes}-01`),
    hojeDia: atual ? Number(b.hoje.slice(8, 10)) : null,
  });
  ligarCartaoFechamento(conteudo, render);
  conteudo.querySelectorAll(".orc-item[data-cat]").forEach((li) =>
    li.addEventListener("click", () => irPara("transacoes", { categoria: li.dataset.cat, periodo: "mes", tipo: "" })));
  document.querySelectorAll("#t-cats tr[data-cat]").forEach((tr) =>
    tr.addEventListener("click", () => irPara("transacoes", { categoria: tr.dataset.cat, periodo: "mes", tipo: "" })));
}

// ============================================================ TRANSAÇÕES
function filtrarTransacoes() {
  const b = estado.base;
  const f = estado.filtros;
  const mes = estado.mes;
  const inicio = { mes, "3m": somarMeses(mes, -2), "12m": somarMeses(mes, -11), tudo: "0000-00" }[f.periodo] || mes;
  const fim = f.periodo === "tudo" ? "9999-99" : mes;
  const busca = f.busca.trim().toLowerCase();
  let lista = estado.dados.transacoes.filter((t) => {
    const m = mesDe(t.data);
    if (m < inicio || m > fim) return false;
    if (!f.futuras && t.data > b.hoje) return false;
    if (!f.ocultas && t.oculto) return false;
    if (f.conta && t.contaId !== f.conta) return false;
    if (f.categoria && t.categoriaId !== f.categoria && b.grupoDe(t.categoriaId) !== f.categoria) return false;
    if (f.tipo === "despesa" && t.natureza !== "despesa") return false;
    if (f.tipo === "entrada" && t.natureza !== "receita" && t.natureza !== "rendimento") return false;
    if (f.tipo === "investimento" && t.natureza !== "investimento") return false;
    if (f.tipo === "internas" && !INTERNAS.has(t.natureza)) return false;
    if (f.tipo === "emprestimo" && t.natureza !== "emprestimo") return false;
    if (f.tipo === "parcelas" && !t.parcela) return false;
    if (f.tipo === "editadas" && !t.ajustada && !t.regraId) return false;
    if (busca && !t.descricao.toLowerCase().includes(busca)) return false;
    return true;
  });
  const ordem = {
    "data-desc": (a, z) => (z.data + z.id).localeCompare(a.data + a.id),
    "data-asc": (a, z) => (a.data + a.id).localeCompare(z.data + z.id),
    "valor-desc": (a, z) => z.valor - a.valor,
    "valor-asc": (a, z) => a.valor - z.valor,
  }[f.ordem];
  return lista.sort(ordem);
}

function opcoesCategorias(selecionada, { incluirGrupos = false, vazio = null } = {}) {
  const cats = estado.base.categorias;
  const grupos = Object.entries(cats).filter(([id, c]) => c.grupo === id).sort((a, z) => a[1].nome.localeCompare(z[1].nome));
  let html = vazio !== null ? `<option value="">${esc(vazio)}</option>` : "";
  for (const [gid, g] of grupos) {
    const filhos = Object.entries(cats).filter(([id, c]) => c.grupo === gid && id !== gid).sort((a, z) => a[1].nome.localeCompare(z[1].nome));
    html += `<optgroup label="${esc(g.nome)}">`;
    html += `<option value="${gid}" ${selecionada === gid ? "selected" : ""}>${incluirGrupos ? `${esc(g.nome)} (todas)` : esc(g.nome)}</option>`;
    html += filhos.map(([id, c]) => `<option value="${id}" ${selecionada === id ? "selected" : ""}>${esc(c.nome)}</option>`).join("");
    html += `</optgroup>`;
  }
  return html;
}

function telaTransacoes() {
  const b = estado.base;
  const f = estado.filtros;
  const lista = filtrarTransacoes();
  const tot = b.totais(lista.filter((t) => !t.oculto));
  const sel = (nome, opcoes) => `<select data-filtro="${nome}">${opcoes.map(([v, r]) => `<option value="${esc(v)}" ${f[nome] === v ? "selected" : ""}>${esc(r)}</option>`).join("")}</select>`;
  const linhas = lista.slice(0, estado.limiteLinhas).map((t) => {
    const conta = b.conta(t.contaId);
    const marcas = [
      t.parcela ? `<span class="marcador">${t.parcela[0]}/${t.parcela[1]}</span>` : "",
      t.data > b.hoje ? `<span class="marcador">prevista</span>` : t.pendente ? `<span class="marcador">pendente</span>` : "",
      t.oculto ? `<span class="marcador">oculta</span>` : "",
      t.ajustada ? `<span class="marcador" title="Você ajustou esta transação">editada</span>` : t.regraId ? `<span class="marcador" title="Classificada por uma regra sua">regra</span>` : "",
    ].join("");
    const natureza = INTERNAS.has(t.natureza) || t.natureza === "rendimento" ? `<span class="etiqueta">${NATUREZAS_CURTAS[t.natureza]}</span> ` : "";
    return `<tr class="${t.oculto || INTERNAS.has(t.natureza) ? "esmaecida" : ""}">
      <td><div class="desc">${iconeTransacao(t)}<span class="texto" title="${esc(t.descricao)}">${esc(t.descricao)}</span>${marcas}</div></td>
      <td>${natureza}${etiquetaCategoria(t.categoriaId)}</td>
      <td><span style="display:inline-flex;align-items:center;gap:8px">${avatarInstituicao(conta.instituicao, true)}<span class="mudo">${esc(conta.tipo === "CREDIT" ? "Cartão" : "Conta")}</span></span></td>
      <td class="num">${dataBR(t.data)}</td>
      <td class="direita">${valorTransacao(t)}</td>
      <td><button class="botao-linha" data-editar="${esc(t.id)}" aria-label="Editar">⋮</button></td></tr>`;
  }).join("");

  conteudo.innerHTML = `
    <div class="filtros">
      ${sel("periodo", [["mes", nomeMes(estado.mes)], ["3m", "Últimos 3 meses"], ["12m", "Últimos 12 meses"], ["tudo", "Todo o histórico"]])}
      ${sel("conta", [["", "Todas as contas"], ...estado.dados.contas.map((c) => [c.id, `${c.instituicao} · ${c.tipo === "CREDIT" ? `Cartão ${c.final}` : c.subtipo}`])])}
      ${sel("tipo", [["", "Todos os tipos"], ["despesa", "Despesas"], ["entrada", "Receitas e rendimentos"], ["investimento", "Investimentos"], ["emprestimo", "Empréstimos a terceiros"], ["internas", "Movimentações internas"], ["parcelas", "Só parceladas"], ["editadas", "Editadas por mim"]])}
      <select data-filtro="categoria">${opcoesCategorias(f.categoria, { incluirGrupos: true, vazio: "Todas as categorias" })}</select>
      ${sel("ordem", [["data-desc", "Mais recentes"], ["data-asc", "Mais antigas"], ["valor-desc", "Maior valor"], ["valor-asc", "Menor valor"]])}
      <input type="search" data-filtro="busca" placeholder="Buscar transações…" value="${esc(f.busca)}">
      <label class="alternar"><input type="checkbox" data-filtro="futuras" ${f.futuras ? "checked" : ""}> Previstas</label>
      <label class="alternar"><input type="checkbox" data-filtro="ocultas" ${f.ocultas ? "checked" : ""}> Ocultas</label>
    </div>
    <section class="grade">
      <div class="c3">${tile("Transações", String(lista.length), INTERNAS.size ? `${lista.filter((t) => INTERNAS.has(t.natureza)).length} internas` : "")}</div>
      <div class="c3">${tile("Despesas", brl(tot.despesas), "", "negativo")}</div>
      <div class="c3">${tile("Receitas e rendimentos", brl(tot.receitas + tot.rendimentos), "", "positivo")}</div>
      <div class="c3">${tile("Saldo", brlSinal(tot.resultado), "receitas − despesas", tot.resultado >= 0 ? "positivo" : "negativo")}</div>
    </section>
    ${cartao("c12", `<div class="tabela-envolve"><table class="tabela">
      <thead><tr><th>Descrição</th><th>Categoria</th><th>Conta</th><th>Data</th><th class="direita">Valor</th><th></th></tr></thead>
      <tbody>${linhas || `<tr><td colspan="6" class="mudo" style="padding:28px;text-align:center">Nenhuma transação com esses filtros.</td></tr>`}</tbody>
    </table></div>
    ${lista.length > estado.limiteLinhas ? `<div class="mais"><button class="botao" id="botao-mais">Mostrar mais (${lista.length - estado.limiteLinhas} restantes)</button></div>` : ""}`)}`;

  conteudo.querySelectorAll("[data-filtro]").forEach((el) => {
    const evento = el.type === "search" ? "input" : "change";
    el.addEventListener(evento, () => {
      estado.filtros[el.dataset.filtro] = el.type === "checkbox" ? el.checked : el.value;
      estado.limiteLinhas = 150;
      const foco = el.type === "search" ? el.selectionStart : null;
      telaTransacoes();
      if (foco !== null) { const novo = conteudo.querySelector('[data-filtro="busca"]'); novo.focus(); novo.setSelectionRange(foco, foco); }
    });
  });
  conteudo.querySelector("#botao-mais")?.addEventListener("click", () => { estado.limiteLinhas += 300; telaTransacoes(); });
  conteudo.querySelectorAll("[data-editar]").forEach((botao) => botao.addEventListener("click", () => abrirEdicao(botao.dataset.editar)));
}

// ---- edição de transação
function abrirEdicao(id) {
  const t = estado.dados.transacoes.find((x) => x.id === id);
  if (!t) return;
  const modal = document.getElementById("modal-transacao");
  document.getElementById("modal-sub").textContent = `${dataBR(t.data)} · ${t.entrada ? "+" : "−"}${brl(t.valor)} · ${t.descricao}`;
  document.getElementById("campo-categoria").innerHTML = opcoesCategorias(t.categoriaId);
  document.getElementById("campo-natureza").innerHTML = Object.entries(NATUREZAS)
    .map(([v, r]) => `<option value="${v}" ${t.natureza === v ? "selected" : ""}>${esc(r)}</option>`).join("");
  document.getElementById("campo-oculto").checked = t.oculto;
  const regra = document.getElementById("campo-regra");
  const padrao = document.getElementById("campo-padrao");
  regra.checked = false;
  padrao.disabled = true;
  padrao.value = t.descricao.replace(/[\d/.*#-]+\s*$/, "").trim();
  regra.onchange = () => { padrao.disabled = !regra.checked; if (regra.checked) padrao.focus(); };
  document.getElementById("botao-cancelar").onclick = () => modal.close();
  document.getElementById("botao-restaurar").onclick = async () => {
    modal.close();
    await salvarEdicao(() => api("/api/ajustes", { transacaoId: t.id, categoriaId: null, natureza: null, oculto: false }), "Transação voltou à classificação automática.");
  };
  document.getElementById("form-transacao").onsubmit = async (e) => {
    e.preventDefault();
    const categoriaId = document.getElementById("campo-categoria").value;
    const natureza = document.getElementById("campo-natureza").value;
    const oculto = document.getElementById("campo-oculto").checked;
    modal.close();
    await salvarEdicao(async () => {
      const ajuste = { transacaoId: t.id, oculto };
      if (categoriaId !== t.categoriaId) ajuste.categoriaId = categoriaId;
      if (natureza !== t.natureza) ajuste.natureza = natureza;
      if (regra.checked && padrao.value.trim()) {
        await api("/api/regras", {
          padrao: padrao.value.trim(),
          categoriaId: categoriaId !== t.categoriaAuto ? categoriaId : null,
          natureza: natureza !== t.naturezaAuto ? natureza : null,
        });
      } else {
        await api("/api/ajustes", ajuste);
        return;
      }
      if (oculto !== t.oculto) await api("/api/ajustes", { transacaoId: t.id, oculto });
    }, regra.checked ? "Regra criada e aplicada." : "Transação atualizada.");
  };
  modal.showModal();
}

async function salvarEdicao(acao, mensagem) {
  try {
    await acao();
    await carregar();
    avisar(mensagem);
  } catch (e) {
    avisar(`Não consegui salvar: ${e.message}`, true);
  }
}

// ============================================================ PARCELAMENTOS
function telaParcelamentos() {
  const b = estado.base;
  const todos = estado.dados.parcelamentos;
  const ativos = todos.filter((p) => p.status === "ativo");
  const finalizados = todos.filter((p) => p.status === "finalizado");
  const total = ativos.reduce((s, p) => s + p.total, 0);
  const pago = ativos.reduce((s, p) => s + p.pago, 0);
  const restante = ativos.reduce((s, p) => s + p.restante, 0);
  const ultima = ativos.map((p) => p.ultimaParcela).sort().pop();
  const ordem = {
    restante: (a, z) => z.restante - a.restante,
    parcela: (a, z) => z.valorParcela - a.valorParcela,
    termino: (a, z) => a.ultimaParcela.localeCompare(z.ultimaParcela),
    recente: (a, z) => z.compra.localeCompare(a.compra),
  }[estado.parcOrdem];
  const lista = (estado.parcStatus === "ativo" ? ativos : finalizados).slice().sort(ordem);

  // Compromisso por fatura: parcelas ainda não pagas, somadas pelo mês de cobrança.
  const fechada = Object.fromEntries(estado.dados.cartoes.filter((c) => c.ultimaFechada).map((c) => [c.contaId, c.ultimaFechada.vencimento.slice(0, 7)]));
  const porFatura = new Map();
  for (const t of b.visiveis) {
    if (!t.parcela || t.natureza !== "despesa" || t.entrada) continue;
    const mesFatura = t.faturaMes || mesDe(t.data);
    if (fechada[t.contaId] ? mesFatura <= fechada[t.contaId] : t.data <= b.hoje) continue;
    porFatura.set(mesFatura, (porFatura.get(mesFatura) || 0) + t.valor);
  }
  const meses = [...porFatura.keys()].sort();

  conteudo.innerHTML = `<section class="grade">
    ${cartao("c12", `
      <div class="tiles">
        ${tile("Em andamento", String(ativos.length), "compras parceladas")}
        ${tile("Valor total", brl(total))}
        ${tile("Já pago", brl(pago), "em faturas fechadas", "positivo")}
        ${tile("Restante", brl(restante), "inclui a fatura aberta", "negativo")}
      </div>
      <div style="margin-top:16px;display:flex;justify-content:space-between" class="sub"><span>Progresso geral</span><span class="positivo">${total ? Math.round((pago / total) * 100) : 0}% pago</span></div>
      <div class="trilho grosso" style="margin-top:6px"><span style="width:${total ? (pago / total) * 100 : 0}%"></span></div>
      ${ultima ? `<div class="sub" style="margin-top:12px">📅 Última parcela: <b>${esc(nomeMes(ultima.slice(0, 7)))}</b></div>` : ""}`)}
    ${meses.length ? cartao("c12", `${topoCartao("Parcelas por fatura")}<div class="sub">Quanto de cada fatura futura já está comprometido com parcelas</div><div id="g-parcelas" style="margin-top:10px"></div>`) : ""}
    </section>
    <div class="segmentos">
      <button data-status="ativo" class="${estado.parcStatus === "ativo" ? "ativo" : ""}">Em andamento (${ativos.length})</button>
      <button data-status="finalizado" class="${estado.parcStatus === "finalizado" ? "ativo" : ""}">Finalizadas (${finalizados.length})</button>
      <span class="espaco"></span>
      <select id="parc-ordem" class="botao">
        ${[["restante", "Maior restante"], ["parcela", "Maior parcela"], ["termino", "Termina antes"], ["recente", "Compra mais recente"]].map(([v, r]) => `<option value="${v}" ${estado.parcOrdem === v ? "selected" : ""}>${r}</option>`).join("")}
      </select>
    </div>
    ${lista.length ? `<div class="itens-grade">${lista.map((p) => {
      const conta = b.conta(p.contaId);
      const avatar = p.marca ? avatarMarca(p.marca) : `<span class="avatar">${iconeGrupo(b.grupoDe(p.categoriaId))}</span>`;
      return `<div class="item-card">${avatar}
        <div style="min-width:0"><div class="titulo">${esc(p.nome)} <span class="pilula ${p.status === "ativo" ? "bom" : "neutra"}">${p.status === "ativo" ? "Ativo" : "Finalizado"}</span></div>
        <div class="linha2">${p.pagas}/${p.parcelas}x · ${brl(p.valorParcela)}/mês · ${esc(conta.instituicao)} · compra ${esc(p.compra.length > 7 ? dataBR(p.compra) : nomeMesCurto(p.compra))}${p.proxima ? ` · próxima na fatura de ${esc(nomeMesCurto(p.proxima))}` : ""}</div>
        <div class="trilho"><span style="width:${(p.pagas / p.parcelas) * 100}%"></span></div></div>
        <div><div class="valor">${brl(p.status === "ativo" ? p.restante : p.total)}</div><div class="linha2 mudo" style="text-align:right">${p.status === "ativo" ? "restante" : "total"}</div></div>
      </div>`;
    }).join("")}</div>` : `<div class="vazio">Nada aqui.</div>`}`;

  conteudo.querySelectorAll("[data-status]").forEach((botao) => botao.addEventListener("click", () => { estado.parcStatus = botao.dataset.status; telaParcelamentos(); }));
  conteudo.querySelector("#parc-ordem").addEventListener("change", (e) => { estado.parcOrdem = e.target.value; telaParcelamentos(); });
  if (meses.length) {
    desenharColunas(document.getElementById("g-parcelas"), {
      altura: 190,
      itens: meses.map((m, i) => ({
        rotulo: nomeMesCurto(m), valor: porFatura.get(m), estilo: i === 0 ? "destaque" : "previsto",
        dica: `<div class="t">Fatura de ${esc(nomeMes(m))}</div>${linhaDica(null, "Parcelas", brl(porFatura.get(m)))}`,
      })),
    });
  }
}

// ============================================================ ASSINATURAS
function telaAssinaturas() {
  const b = estado.base;
  const rec = estado.dados.recorrentes;
  const assinaturas = rec.filter((r) => r.tipo === "assinatura");
  const fixas = rec.filter((r) => r.tipo === "conta_fixa");
  const soma = (l) => l.reduce((s, r) => s + r.valor, 0);
  const item = (r) => {
    const conta = b.conta(r.contaId);
    const atrasada = r.proxima < b.hoje;
    const subiu = r.valor > r.media * 1.1 && r.pagamentos > 2;
    return `<div class="item-card">${avatarMarca(r.nome)}
      <div style="min-width:0"><div class="titulo">${esc(r.nome)} ${subiu ? `<span class="pilula ruim" title="Média dos últimos meses: ${brl(r.media)}">↑ subiu</span>` : ""}</div>
      <div class="linha2" style="margin-bottom:0">${r.descricao !== r.nome ? `${esc(r.descricao)} · ` : ""}${atrasada ? `previsto para ${dataCurta(r.proxima)}, ainda não cobrado` : `próximo: ${dataCurta(r.proxima)}`} · ${r.pagamentos} pagamentos · ${esc(conta.instituicao)} · ${etiquetaCategoria(r.categoriaId)}</div></div>
      <div><div class="valor">${brl(r.valor)}</div><div class="linha2 mudo" style="text-align:right;margin:0">/mês</div></div></div>`;
  };
  conteudo.innerHTML = `
    ${cartao("", `<div class="tiles">
      ${tile("Assinaturas", String(assinaturas.length), "ativas")}
      ${tile("Gasto mensal", brl(soma(assinaturas)))}
      ${tile("Projeção anual", brl(soma(assinaturas) * 12), "", "negativo")}
      ${tile("Média por serviço", brl(assinaturas.length ? soma(assinaturas) / assinaturas.length : 0), "", "positivo")}
    </div>`)}
    <div class="secao-titulo"><h2>Assinaturas</h2><span class="mudo">${brl(soma(assinaturas))}/mês</span></div>
    ${assinaturas.length ? `<div class="itens-grade">${assinaturas.map(item).join("")}</div>` : `<div class="vazio">Nenhuma assinatura detectada.</div>`}
    <div class="secao-titulo"><h2>Contas fixas e recorrentes</h2><span class="mudo">${brl(soma(fixas))}/mês</span></div>
    ${fixas.length ? `<div class="itens-grade">${fixas.map(item).join("")}</div>` : `<div class="vazio">Nenhuma conta fixa detectada.</div>`}
    <p class="mudo" style="margin-top:20px;font-size:12px">Detectadas automaticamente: cobranças do mesmo estabelecimento em pelo menos 3 meses, com intervalo de ~1 mês, a última nos últimos 45 dias. O IOF de compras internacionais é somado ao serviço.</p>`;
}

// ============================================================ CATEGORIAS
function telaCategorias() {
  const b = estado.base;
  const mes = estado.mes;
  const { cats, grupos } = b.porCategoria(mes);
  const { media: mediaMensal, meses: nMedia } = b.mediaCategorias(mes, 6);
  // No mês corrente, compara com a média proporcional aos dias já passados (senão tudo parece "abaixo").
  const fator = mes === b.mesAtual ? Number(b.hoje.slice(8, 10)) / diasNoMes(mes) : 1;
  const media = new Map([...mediaMensal].map(([c, v]) => [c, v * fator]));
  const total = [...grupos.values()].reduce((s, v) => s + Math.max(0, v), 0);
  const gruposOrdenados = [...grupos].filter(([, v]) => v > 0).sort((a, z) => z[1] - a[1]);
  const mediaGrupo = (g) => [...media].filter(([c]) => b.grupoDe(c) === g).reduce((s, [, v]) => s + v, 0);
  const contagem = new Map();
  for (const t of b.doMes(mes)) if (t.natureza === "despesa") contagem.set(t.categoriaId, (contagem.get(t.categoriaId) || 0) + 1);

  // Rosca: grupos com cor própria; o resto vira "Demais".
  const comCor = gruposOrdenados.filter(([g]) => grupoTemCor(g));
  const demais = gruposOrdenados.filter(([g]) => !grupoTemCor(g)).reduce((s, [, v]) => s + v, 0);
  const fatias = comCor.map(([g, v]) => ({ nome: b.nomeGrupo(g), valor: v, cor: corGrupo(g) }));
  if (demais > 0) fatias.push({ nome: "Demais grupos", valor: demais, cor: "var(--s-outros)" });
  fatias.forEach((f) => { f.dica = `<div class="t">${esc(f.nome)}</div>${linhaDica(f.cor, "No mês", brl(f.valor))}${linhaDica(null, "Do total", `${Math.round((f.valor / total) * 100)}%`)}`; });

  const comparar = (atual, base) => (nMedia && base > 0 ? pilulaVariacao((atual / base - 1) * 100) : `<span class="pilula neutra">novo</span>`);
  const regrasUsuario = estado.dados.regras;

  conteudo.innerHTML = `<section class="grade">
    ${cartao("c12", `<div class="donut-envolve">
      <div><div class="rotulo">Gasto em ${esc(nomeMes(mes))}</div><div class="heroi">${brl(total)}</div>
      <div class="sub">${nMedia ? `média mensal dos ${nMedia} meses anteriores: ${brl([...mediaMensal.values()].reduce((s, v) => s + v, 0))}` : ""}</div>
      ${resumoGenerico(b, mes) ? `<div class="sub">${resumoGenerico(b, mes)}</div>` : ""}
      <div class="legenda" style="max-width:360px;margin-top:14px">${fatias.map((f) => `<span><span class="ponto" style="background:${f.cor}"></span>${esc(f.nome)}</span>`).join("")}</div></div>
      <span class="espaco"></span><div id="g-rosca"></div></div>`)}
    ${cartao("c8", `${topoCartao("Categorias", `<span class="mudo" style="font-size:12px">vs média de ${nMedia || 0} meses${fator < 1 ? `, proporcional até dia ${b.hoje.slice(8, 10)}` : ""}</span>`)}
      ${gruposOrdenados.map(([g, v]) => {
        const filhos = [...cats].filter(([c, x]) => b.grupoDe(c) === g && x !== 0).sort((a, z) => z[1] - a[1]);
        return `<details class="grupo-cat">
          <summary><span class="seta">›</span><span class="icone-cat">${iconeGrupo(g)}</span>
            <span><b>${esc(b.nomeGrupo(g))}</b> <span class="mudo">· ${filhos.length}</span></span>
            <span class="num" style="display:flex;gap:10px;align-items:center">${comparar(v, mediaGrupo(g))}<b>${brl(v)}</b></span>
            <div class="trilho"><span style="width:${(v / gruposOrdenados[0][1]) * 100}%;background:${corGrupo(g)}"></span></div></summary>
          <ul class="subcats">${filhos.map(([c, x]) => `<li data-cat="${esc(c)}"><span>${esc(b.categoria(c).nome)} <span class="mudo">· ${contagem.get(c) || 0}</span></span>
            ${comparar(x, media.get(c) || 0)}<span class="num">${brl(x)}</span>
            <div class="trilho"><span style="width:${Math.max(0, (x / v) * 100)}%;background:${corGrupo(g)}"></span></div></li>`).join("")}</ul>
        </details>`;
      }).join("") || `<div class="vazio">Sem despesas neste mês.</div>`}`)}
    <div class="c4 coluna">
    ${cartao("", `${topoCartao("Suas categorias")}
      <div class="sub">Categorias criadas por você aparecem no ⋮ das transações e nas regras.</div>
      <form class="filtros" id="form-categoria" style="margin:12px 0 0">
        <input type="text" id="nova-categoria" placeholder="Nome (ex.: Auxílio familiar)" maxlength="40" required style="flex:1;min-width:200px;background:var(--superficie);border:1px solid var(--borda-forte);border-radius:10px;padding:8px 10px">
        <select id="nova-categoria-pai"><option value="">Categoria principal (novo grupo)</option>${Object.entries(b.categorias)
          .filter(([id, c]) => c.grupo === id).sort((a, z) => a[1].nome.localeCompare(z[1].nome))
          .map(([id, c]) => `<option value="${esc(id)}">Dentro de: ${esc(c.nome)}</option>`).join("")}</select>
        <button class="botao botao-acento" type="submit">Criar</button>
      </form>
      <ul class="lista">${Object.entries(b.categorias).filter(([, c]) => c.propria).map(([id, c]) => `<li><span class="icone-cat">${iconeGrupo(c.grupo)}</span><div class="meio"><div class="titulo">${esc(c.nome)}</div>
        <div class="linha2">${c.grupo === id ? "categoria principal" : `dentro de ${esc(b.nomeGrupo(c.grupo))}`}</div></div></li>`).join("")}</ul>`)}
    ${cartao("", `${topoCartao("Suas regras")}
      <div class="sub">Crie regras pelo ⋮ de uma transação (aba Transações). Elas valem para o histórico todo e para as próximas sincronizações.</div>
      <ul class="lista regras-lista">${regrasUsuario.map((r) => `<li><div class="meio"><div class="titulo">contém “${esc(r.padrao)}”</div>
        <div class="linha2">${r.categoria_id ? `→ ${esc(b.categoria(r.categoria_id).nome)}` : ""}${r.categoria_id && r.natureza ? " · " : ""}${r.natureza ? `→ ${esc(NATUREZAS[r.natureza])}` : ""}</div></div>
        <button class="botao botao-fantasma" data-remover="${r.id}">Remover</button></li>`).join("") || `<li class="mudo">Nenhuma regra ainda.</li>`}</ul>`)}
    </div>
  </section>`;

  desenharRosca(document.getElementById("g-rosca"), { fatias, tamanho: 190, centro: compacto(total), centroSub: nomeMesCurto(mes) });
  conteudo.querySelectorAll(".subcats li[data-cat]").forEach((li) =>
    li.addEventListener("click", () => irPara("transacoes", { categoria: li.dataset.cat, periodo: "mes", tipo: "" })));
  conteudo.querySelectorAll("[data-remover]").forEach((botao) => botao.addEventListener("click", () =>
    salvarEdicao(() => api("/api/regras/remover", { id: Number(botao.dataset.remover) }), "Regra removida.")));
  conteudo.querySelector("#form-categoria").addEventListener("submit", (e) => {
    e.preventDefault();
    const nome = conteudo.querySelector("#nova-categoria").value.trim();
    const paiId = conteudo.querySelector("#nova-categoria-pai").value || null;
    salvarEdicao(() => api("/api/categorias", { nome, paiId }), `Categoria “${nome}” criada.`);
  });
}

// ============================================================ CARTÕES
function telaCartoes() {
  const cartoes = estado.dados.cartoes;
  if (!cartoes.length) { conteudo.innerHTML = `<div class="vazio">Nenhum cartão de crédito conectado.</div>`; return; }
  const comHistorico = cartoes.filter((c) => c.historico.length || c.faturaAberta.valor);
  if (!estado.cartaoSel || !cartoes.some((c) => c.contaId === estado.cartaoSel)) estado.cartaoSel = (comHistorico[0] || cartoes[0]).contaId;
  const sel = cartoes.find((c) => c.contaId === estado.cartaoSel);
  const totalAberta = cartoes.reduce((s, c) => s + c.faturaAberta.valor, 0);

  conteudo.innerHTML = `<div>
    ${cartao("", `<div style="text-align:center"><div class="rotulo">Faturas abertas</div><div class="heroi" style="font-size:44px">${brl(totalAberta)}</div>
      <div class="sub">estimativa somando todos os cartões</div></div>`)}
    <div class="secao-titulo"><h2>Seus cartões</h2><span class="mudo">${cartoes.length}</span></div>
    <section class="grade">${cartoes.map((c) => {
      const usado = Math.max(0, c.usado || 0);
      const limite = c.limite || usado + (c.disponivel || 0) || 1;
      return cartao("c6 cartao-credito", `
        <div class="cab">${avatarInstituicao(c.instituicao)}<div><div class="titulo"><b>${esc(c.nome)}</b></div><div class="mudo num">•••• ${esc(c.final)}${c.bandeira ? ` · ${esc(c.bandeira)}` : ""}</div></div></div>
        <div class="rotulo" style="font-size:11px">Fatura aberta (estimada)</div>
        <div class="heroi">${brl(c.faturaAberta.valor)}</div>
        <div class="sub">${c.faturaAberta.vencimento ? `vence ${dataCurta(c.faturaAberta.vencimento)}` : "sem fatura em aberto"}${c.ultimaFechada ? ` · última fechada: ${brl(c.ultimaFechada.valor)} (${c.ultimaFechada.aPagar ? "a pagar até" : "venceu"} ${dataCurta(c.ultimaFechada.vencimento)})` : ""}</div>
        <div class="rodape-cartao" style="display:block">
          <div style="display:flex;justify-content:space-between"><span>Limite total</span><b class="num" style="color:var(--texto)">${c.limite === null ? `<a class="link" href="#/importar">informar</a>` : brl(c.limite)}</b></div>
          <div class="barra-limite"><span style="width:${(usado / limite) * 100}%;background:var(--s1)"></span><span style="flex:1;background:var(--acento)"></span></div>
          <div class="legenda" style="margin:0;justify-content:space-between"><span><span class="ponto" style="background:var(--s1)"></span>Usado ${brl(usado)}</span><span><span class="ponto" style="background:var(--acento)"></span>${c.disponivelEstimado ? "Disponível (estimado)" : "Disponível"} ${c.disponivel === null ? "—" : brl(c.disponivel)}</span></div>
          ${c.limiteConfigurado && c.limiteConfigurado !== c.limite ? `<div class="mudo" style="margin-top:6px;font-size:12px">Limite ajustado por você no app: ${brl(c.limiteConfigurado)}</div>` : ""}
        </div>`);
    }).join("")}</section>
    ${cartao("", `${topoCartao("Faturas", comHistorico.length > 1 ? `<span class="segmentos" style="margin:0">${comHistorico.map((c) => `<button data-cartao="${esc(c.contaId)}" class="${c.contaId === sel.contaId ? "ativo" : ""}">${esc(c.instituicao)} ${esc(c.final)}</button>`).join("")}</span>` : `<span class="mudo">${esc(sel.nome)}</span>`)}
      <div id="g-faturas" style="margin-top:10px"></div>
      <div class="legenda"><span><i style="background:#4a4a47;height:8px"></i>Fechadas</span><span><i style="background:var(--acento);height:8px"></i>Aberta (estimada)</span><span><i style="background:var(--acento);opacity:.35;height:8px"></i>Já comprometido (parcelas)</span></div>`)}
    <div class="alerta-faixa" style="margin-top:4px">A fatura aberta é estimada pelas compras com cobrança prevista para ela, incluindo parcelas já agendadas. Compras dos últimos 1–3 dias podem ainda não ter chegado pelo Open Finance.</div>
  </div>`;

  conteudo.querySelectorAll("[data-cartao]").forEach((botao) => botao.addEventListener("click", () => { estado.cartaoSel = botao.dataset.cartao; telaCartoes(); }));
  const itens = [
    ...sel.historico.map((f) => ({ rotulo: nomeMesCurto(f.mes), valor: f.valor, estilo: "normal", dica: `<div class="t">Fatura de ${esc(nomeMes(f.mes))}</div>${linhaDica(null, "Total", brl(f.valor))}${linhaDica(null, "Vencimento", dataBR(f.vencimento))}` })),
    ...(sel.faturaAberta.mes ? [{ rotulo: nomeMesCurto(sel.faturaAberta.mes), valor: sel.faturaAberta.valor, estilo: "destaque", dica: `<div class="t">Fatura aberta · ${esc(nomeMes(sel.faturaAberta.mes))}</div>${linhaDica(null, "Estimada", brl(sel.faturaAberta.valor))}${linhaDica(null, "Vencimento", dataBR(sel.faturaAberta.vencimento))}` }] : []),
    ...sel.proximas.slice(0, 6).map((f) => ({ rotulo: nomeMesCurto(f.mes), valor: f.valor, estilo: "previsto", dica: `<div class="t">${esc(nomeMes(f.mes))}</div>${linhaDica(null, "Já comprometido", brl(f.valor))}` })),
  ];
  desenharColunas(document.getElementById("g-faturas"), { itens, altura: 240 });
}

// ============================================================ INVESTIMENTOS
// As sub-abas ficam em investimentos.js (resumo, proventos, composição, ativos, movimentações)
// e rentabilidade.js (rentabilidade e risco, a partir do histórico diário da carteira).
function telaInvestimentos() {
  renderInvestimentos(conteudo, estado, { cartao, topoCartao, tile, api, salvarEdicao, irPara, avisar }, rota().sub || "resumo");
}

const TELAS = {
  visao: telaVisao, transacoes: telaTransacoes, parcelamentos: telaParcelamentos, assinaturas: telaAssinaturas,
  categorias: telaCategorias, cartoes: telaCartoes, investimentos: telaInvestimentos,
};
TELAS.importar = () => telaImportar({ dados: estado.dados, api, recarregar: carregar, avisar, conteudo });
TELAS.revisar = () => telaRevisar(conteudo, estado, { cartao, topoCartao, api, avisar, salvarEdicao, irPara, opcoesCategorias });
TELAS.orcamento = () => telaOrcamento(conteudo, estado, { cartao, topoCartao, api, avisar, recarregar: carregar });
TELAS.fechamento = () => telaFechamento(conteudo, estado, { cartao, topoCartao, tile, pilulaVariacao, api, irPara });
TELAS.previsao = () => telaPrevisao(conteudo, estado, { cartao, topoCartao, tile, api, recarregar: carregar, avisar });

// ============================================================ início
iniciarPrivacidade(document.getElementById("botao-privado"));
document.getElementById("botao-sinc").addEventListener("click", sincronizar);
document.querySelectorAll("#seletor-mes button").forEach((botao) => botao.addEventListener("click", () => {
  estado.mes = somarMeses(estado.mes, Number(botao.dataset.mes));
  render();
}));
// A dica do gráfico anterior não recebe mouseleave quando a tela é trocada: esconde aqui.
window.addEventListener("hashchange", () => { esconderDica(); window.scrollTo(0, 0); render(); });
let redimensionar;
window.addEventListener("resize", () => { clearTimeout(redimensionar); redimensionar = setTimeout(render, 150); });

carregar().catch((e) => {
  conteudo.innerHTML = `<div class="vazio"><h2>Não consegui carregar os dados</h2><p>${esc(e.message)}</p></div>`;
});
