// Sub-abas Rentabilidade e Risco da área Investimentos (no estilo do Investidor10).
// O histórico diário vem pronto de openbalance/historico.py (/api/historico): valor e cota da carteira, índice de
// rentabilidade de cada ativo e os índices de comparação, todos na mesma régua de dias úteis. Aqui ficam os
// recortes por período e as contas: rentabilidade por cotas, ano a ano, contribuição por ativo e por classe,
// volatilidade, queda máxima, Sharpe e correlação.
import { desenharDispersao, desenharLinhas, linhaDica } from "./graficos.js";
import { CLASSES_INVESTIMENTO } from "./investimentos.js";
import { brl, brlSinal, dataBR, esc, nomeMesCurto, somarMeses } from "./util.js";

const COR_CARTEIRA = "var(--s1)";
// Cor fixa por índice (ordem validada da paleta), nunca pela posição na lista.
const REFERENCIAS = [
  { id: "cdi", nome: "CDI", curto: "CDI", cor: "var(--s2)" },
  { id: "ibov", nome: "Ibovespa", curto: "Ibov", cor: "var(--s3)" },
  { id: "ipca", nome: "IPCA", curto: "IPCA", cor: "var(--s4)" },
  { id: "ifix", nome: "IFIX", curto: "IFIX", cor: "var(--s5)", nota: "pelo ETF XFIX11, que replica o índice" },
  { id: "dolar", nome: "Dólar", curto: "Dólar", cor: "var(--s6)" },
  { id: "sp500", nome: "S&P 500 em R$", curto: "S&P 500", cor: "var(--s7)" },
];
const REF = Object.fromEntries(REFERENCIAS.map((r) => [r.id, r]));
// Só oscilam de preço: entram no gráfico de quedas e na correlação.
const REFERENCIAS_DE_MERCADO = ["ibov", "ifix", "dolar", "sp500"];
const PERIODOS = [["6m", "6 meses"], ["12m", "12 meses"], ["ano", "No ano"], ["tudo", "Desde o início"]];
// Índice certo para cada classe: renda fixa e fundos contra o CDI, Tesouro (quase todo IPCA+) contra o IPCA, ações contra o
// Ibovespa, FIIs contra o IFIX; ações internacionais e REITs contra o S&P 500 em reais, renda fixa internacional contra o dólar.
const REFERENCIA_CLASSE = { tesouro: "ipca", renda_fixa: "cdi", fundos: "cdi", acoes: "ibov", etf: "ibov", fiis: "ifix", acoes_exterior: "sp500",
  reits: "sp500", renda_fixa_exterior: "dolar", cripto: "cdi", outros: "cdi" };
const DIAS_ANO = 252;
const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

// Filtros da área (valem para Rentabilidade e Risco) e o histórico já carregado.
const filtros = { periodo: "12m", refs: new Set(["cdi", "ibov"]) };
const cache = { dados: null, em: 0, promessa: null, timer: null };

const formato2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const formato1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const valido = (v) => v !== null && v !== undefined && isFinite(v);
export const pct2 = (v) => (valido(v) ?`${v > 0 ? "+" : v < 0 ? "−" : ""}${formato2.format(Math.abs(v))}%` : "—");
const pctSemSinal = (v) => (valido(v) ? `${v < 0 ? "−" : ""}${formato2.format(Math.abs(v))}%` : "—");
const pp = (v) => (valido(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${formato2.format(Math.abs(v))} p.p.` : "—");
const sinal = (v) => (!valido(v) ? "" : v > 0 ? "positivo" : v < 0 ? "negativo" : "");
const dataCurtaAno = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`;
const nomeClasse = (id) => CLASSES_INVESTIMENTO.find((c) => c.id === id) || { nome: id, cor: "var(--s-outros)", icone: "" };

// ============================================================ carga (com atualização em segundo plano)
function carregar(api) {
  if (!cache.promessa) {
    cache.promessa = api("/api/historico")
      .then((dados) => { cache.dados = dados; cache.em = Date.now(); return dados; })
      .finally(() => { cache.promessa = null; });
  }
  return cache.promessa;
}

/** Chamado pelas outras sub-abas: o servidor começa a baixar as cotações antes de o usuário abrir Rentabilidade. */
export function preCarregarHistorico(api) {
  if (!cache.dados && !cache.promessa) carregar(api).catch(() => {});
}

const recente = () => cache.dados && Date.now() - cache.em < 5 * 60e3 && !cache.dados.progresso?.rodando;

/** Para o Resumo: pinta já com o histórico em memória e de novo quando ele chega (ou muda, enquanto baixa cotações).
 *  pintar(h, erro): h é null quando o histórico não pôde ser montado. */
export function usarHistorico(api, pintar) {
  if (cache.dados) pintar(cache.dados);
  if (recente()) return;
  const repintar = () => pintar(cache.dados);
  carregar(api).then(() => { repintar(); acompanhar(api, repintar); }).catch((e) => { if (!cache.dados) pintar(null, e); });
}

export function telaRentabilidade(conteudo, estado, ui) { abrir(conteudo, ui, "rentabilidade", desenharRentabilidade); }
export function telaRisco(conteudo, estado, ui) { abrir(conteudo, ui, "risco", desenharRisco); }

function abrir(conteudo, ui, sub, desenhar) {
  const pintar = () => {
    if (location.hash.split("?")[0] !== `#/investimentos/${sub}` || !cache.dados) return;
    desenhar(conteudo, cache.dados, ui, () => pintar());
  };
  if (cache.dados) pintar();
  else conteudo.innerHTML = `<div class="vazio"><h2>Montando o histórico da carteira…</h2><p>Na primeira vez o Open Balance baixa as cotações dos seus ativos e índices; leva cerca de um minuto.</p></div>`;
  if (recente()) return;
  carregar(ui.api).then(() => { pintar(); acompanhar(ui.api, pintar); }).catch((e) => {
    if (cache.dados) ui.avisar(`Não consegui atualizar o histórico: ${e.message}`, true);
    else conteudo.innerHTML = `<div class="vazio"><h2>Não consegui montar o histórico</h2><p>${esc(e.message)}</p></div>`;
  });
}

// Enquanto o servidor baixa cotações, busca de novo a cada 2,5 s e redesenha (mantendo a tela anterior até lá).
function acompanhar(api, pintar) {
  clearTimeout(cache.timer);
  if (!cache.dados?.progresso?.rodando) return;
  cache.timer = setTimeout(() => carregar(api).then(() => { pintar(); acompanhar(api, pintar); }).catch(() => {}), 2500);
}

// ============================================================ contas
function preencher(serie) {
  let ultimo = null;
  return serie.map((v) => (valido(v) && v ? (ultimo = v) : ultimo));
}

function preparar(h) {
  if (!h._prep) {
    h.ativos.forEach((a) => { a.indice = preencher(a.indice); });
    h._prep = { cota: h.carteira.cota, refs: Object.fromEntries(Object.entries(h.indices).map(([k, v]) => [k, preencher(v)])) };
  }
  return h._prep;
}

const temDados = (h, id) => (h.indices[id] || []).some((v) => v);

/** Índices [s, e] do período escolhido. A base é o fechamento do dia anterior ao período. */
function janela(h) {
  const n = h.datas.length;
  const ultima = h.datas[n - 1];
  let alvo = null;
  if (filtros.periodo === "6m" || filtros.periodo === "12m") {
    alvo = `${somarMeses(ultima.slice(0, 7), filtros.periodo === "6m" ? -6 : -12)}${ultima.slice(7)}`;
  } else if (filtros.periodo === "ano") {
    alvo = `${Number(ultima.slice(0, 4)) - 1}-12-31`;
  }
  let s = 0;
  if (alvo) h.datas.forEach((d, k) => { if (d <= alvo) s = k; });
  return { s, e: n - 1 };
}

function retorno(serie, s, e) {
  let k = s;
  while (k < e && !serie[k]) k++;
  return serie[k] && serie[e] ? (serie[e] / serie[k] - 1) * 100 : null;
}

/** Retorno, anualizado, volatilidade anual, maior queda (com datas) e retornos diários de uma série no período. */
function estatisticas(serie, s, e) {
  let k0 = s;
  while (k0 < e && !serie[k0]) k0++;
  const diarios = [];
  let pico = serie[k0];
  let picoK = k0;
  let queda = 0;
  let quedaDe = k0;
  let quedaAte = k0;
  for (let k = k0 + 1; k <= e; k++) {
    const a = serie[k - 1];
    const b = serie[k];
    diarios[k] = a && b ? b / a - 1 : null;
    if (!b) continue;
    if (b > pico) { pico = b; picoK = k; }
    if (b / pico - 1 < queda) { queda = b / pico - 1; quedaDe = picoK; quedaAte = k; }
  }
  const lista = diarios.filter(valido);
  const media = lista.reduce((x, r) => x + r, 0) / (lista.length || 1);
  const variancia = lista.reduce((x, r) => x + (r - media) ** 2, 0) / Math.max(1, lista.length - 1);
  const ret = retorno(serie, k0, e);
  const anual = valido(ret) && e > k0 ? ((1 + ret / 100) ** (DIAS_ANO / (e - k0)) - 1) * 100 : null;
  return { retorno: ret, anual, vol: Math.sqrt(variancia * DIAS_ANO) * 100, queda: queda * 100, quedaDe, quedaAte, diarios };
}

/** Contribuição de cada ativo e de cada classe para a rentabilidade do período (somam exatamente o total). */
function contribuicoes(h, p, s, e) {
  const ativos = h.ativos.map((a) => ({ ...a, contrib: 0 }));
  const classes = {};
  for (let k = s + 1; k <= e; k++) {
    let base = 0;
    const linhas = [];
    for (const a of ativos) {
      const v = a.valor[k - 1];
      const i0 = a.indice[k - 1];
      const i1 = a.indice[k];
      if (v && i0 && i1) { base += v; linhas.push([a, v, i1 / i0 - 1]); }
    }
    if (!base) continue;
    const escala = p.cota[k - 1] / p.cota[s];
    const doDia = {};
    for (const [a, v, r] of linhas) {
      a.contrib += (v / base) * r * escala * 100;
      const c = (doDia[a.classe] ||= { base: 0, ganho: 0 });
      c.base += v;
      c.ganho += v * r;
    }
    for (const [id, c] of Object.entries(doDia)) {
      const ref = p.refs[REFERENCIA_CLASSE[id] || "cdi"];
      const cl = (classes[id] ||= { fator: 1, fatorRef: 1, contrib: 0, dias: 0 });
      cl.fator *= 1 + c.ganho / c.base;
      if (ref[k - 1] && ref[k]) cl.fatorRef *= ref[k] / ref[k - 1];
      cl.contrib += (c.ganho / base) * escala * 100;
      cl.dias++;
    }
  }
  return { ativos, classes };
}

function correlacao(a, b) {
  const pares = [];
  a.forEach((x, k) => { if (valido(x) && valido(b[k])) pares.push([x, b[k]]); });
  if (pares.length < 20) return null;
  const mx = pares.reduce((s, [x]) => s + x, 0) / pares.length;
  const my = pares.reduce((s, [, y]) => s + y, 0) / pares.length;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (const [x, y] of pares) { sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
}

// ============================================================ peças comuns
function barraFiltros(h) {
  return `<div class="filtros">
    <div class="segmentos" style="margin:0">${PERIODOS.map(([id, nome]) => `<button data-periodo="${id}" class="${filtros.periodo === id ? "ativo" : ""}">${nome}</button>`).join("")}</div>
    <span class="espaco"></span>
    <span class="mudo" style="font-size:12px">Comparar com</span>
    ${REFERENCIAS.filter((r) => temDados(h, r.id)).map((r) => `<label class="chip-ref${filtros.refs.has(r.id) ? " ativo" : ""}"${r.nota ? ` title="${esc(r.nota)}"` : ""}>
      <input type="checkbox" data-ref="${r.id}" ${filtros.refs.has(r.id) ? "checked" : ""}><span class="ponto" style="background:${r.cor}"></span>${esc(r.nome)}</label>`).join("")}
  </div>`;
}

function ligarFiltros(conteudo, redesenhar) {
  conteudo.querySelectorAll("[data-periodo]").forEach((b) => b.addEventListener("click", () => { filtros.periodo = b.dataset.periodo; redesenhar(); }));
  conteudo.querySelectorAll("[data-ref]").forEach((c) => c.addEventListener("change", () => {
    if (c.checked) filtros.refs.add(c.dataset.ref); else filtros.refs.delete(c.dataset.ref);
    redesenhar();
  }));
}

function faixaStatus(h) {
  const pr = h.progresso || {};
  const partes = [];
  if (pr.rodando) partes.push(`Baixando cotações (${pr.feitas} de ${pr.total || "?"}): ${esc(pr.etapa)}. A tela se completa sozinha.`);
  else {
    if (h.semPreco?.length) partes.push(`Sem cotação para ${esc(h.semPreco.join(", "))}: ${h.semPreco.length === 1 ? "fica" : "ficam"} fora do histórico nos dias sem preço.`);
    if (pr.erros?.length) partes.push(`Algumas fontes não responderam agora (o histórico usa o que já estava guardado): ${esc(pr.erros.slice(0, 3).join(" · "))}.`);
  }
  return partes.length ? `<div class="alerta-faixa">${partes.join("<br>")}</div>` : "";
}

function marcasX(n) {
  return [...new Set(Array.from({ length: 6 }, (_, j) => Math.round((j * (n - 1)) / 5)))];
}

const refsEscolhidas = (h) => REFERENCIAS.filter((r) => filtros.refs.has(r.id) && temDados(h, r.id));

function rotuloCurto(a) {
  if (a.classe === "tesouro") return a.nome.replace(/^Tesouro /, "").replace("Aposentadoria Extra ", "");
  if (a.classe === "renda_fixa") return a.nome.split(" - ")[0];
  if (a.classe === "fundos") return a.nome.split(" ").slice(0, 3).join(" ");
  return a.nome;
}

function semHistorico(h) {
  if (h.vazio) return `<div class="vazio"><h2>Sem posições para montar o histórico</h2><p>Quando houver investimentos (pela Pluggy ou importados), a rentabilidade aparece aqui.</p></div>`;
  if (!h.datas?.length || !h.ativos?.length) return `${faixaStatus(h)}<div class="vazio"><h2>Histórico ainda vazio</h2><p>As cotações ainda não foram baixadas.</p></div>`;
  return null;
}

// Dias estimados dentro do período (poucos dias na borda não valem a faixa nem a nota).
function diasEstimados(h, s) {
  if (!h.confiavelDesde || h.confiavelDesde <= h.datas[s]) return 0;
  const k = h.datas.findIndex((d) => d >= h.confiavelDesde);
  return (k < 0 ? h.datas.length : k) - s;
}

function notaEstimado(h, s) {
  if (!h.confiavelDesde) {
    return `<p class="mudo" style="font-size:12px;margin:8px 0 0">Sem as compras e vendas (posições importadas por arquivo não trazem esse histórico), o gráfico simula as quantidades de hoje ao longo de todo o período: mostra como a carteira atual teria se saído, não o que você de fato ganhou.</p>`;
  }
  if (diasEstimados(h, s) < 5) return "";
  return `<p class="mudo" style="font-size:12px;margin:8px 0 0">Trecho sombreado (até ${dataBR(h.confiavelDesde)}): o banco só informa compras e vendas a partir dessa data, então antes dela o Open Balance supõe que você tinha as mesmas quantidades desde a data da primeira compra de cada título. Posições resgatadas antes disso não entram.</p>`;
}

// ============================================================ RENTABILIDADE
function desenharRentabilidade(conteudo, h, ui, redesenhar) {
  const { cartao, topoCartao, tile } = ui;
  const vazio = semHistorico(h);
  if (vazio) { conteudo.innerHTML = vazio; return; }
  const p = preparar(h);
  const { s, e } = janela(h);
  const R = retorno(p.cota, s, e);
  const ref = (id) => (temDados(h, id) ? retorno(p.refs[id], s, e) : null);
  const cdi = ref("cdi");
  const ibov = ref("ibov");
  const ipca = ref("ipca");
  const real = valido(R) && valido(ipca) ? ((1 + R / 100) / (1 + ipca / 100) - 1) * 100 : null;
  const fluxo = h.carteira.fluxo.slice(s + 1, e + 1).reduce((x, f) => x + f, 0);
  const ganho = h.carteira.valor[e] - h.carteira.valor[s] - fluxo;
  const refs = refsEscolhidas(h);

  conteudo.innerHTML = `${barraFiltros(h)}${faixaStatus(h)}
    <section class="grade">
      ${cartao("c12", `<div class="tiles">
        ${tile("Rentabilidade", pct2(R), `${dataBR(h.datas[s])} a ${dataBR(h.datas[e])}`, sinal(R))}
        ${tile("Comparado ao CDI", valido(R) && cdi ? `${formato1.format((R / cdi) * 100)}% do CDI` : "—", `CDI no período ${pct2(cdi)}`, valido(R) && valido(cdi) ? sinal(R - cdi) : "")}
        ${tile("Comparado ao Ibovespa", pp(valido(R) && valido(ibov) ? R - ibov : null), `Ibovespa no período ${pct2(ibov)}`, valido(R) && valido(ibov) ? sinal(R - ibov) : "")}
        ${tile("Acima da inflação", pct2(real), `IPCA ${pct2(ipca)}${h.indicesInfo?.ipcaAte ? ` (publicado até ${esc(nomeMesCurto(h.indicesInfo.ipcaAte))})` : ""}`, sinal(real))}
        ${tile("Ganho no período", brlSinal(ganho), `aportes − resgates no período ${brlSinal(fluxo)}`, sinal(ganho))}
      </div>`)}
      ${cartao("c12", `${topoCartao("Desempenho da carteira", `<span class="mudo" style="font-size:12px">rentabilidade acumulada, sem contar aportes e resgates (método de cotas)</span>`)}
        <div id="g-desempenho" style="margin-top:12px"></div>
        <div class="legenda"><span><i style="background:${COR_CARTEIRA};height:3px"></i>Carteira</span>${refs.map((r) => `<span><i style="background:${r.cor};height:3px"></i>${esc(r.nome)}</span>`).join("")}</div>
        ${notaEstimado(h, s)}`)}
      ${secaoAnoAno(h, p, refs, cartao, topoCartao)}
      ${secaoClasses(h, p, s, e, R, cartao, topoCartao)}
    </section>
    ${notas(h)}`;

  ligarFiltros(conteudo, redesenhar);
  graficoDesempenho(h, p, s, e, refs);
}

function graficoDesempenho(h, p, s, e, refs) {
  const el = document.getElementById("g-desempenho");
  if (!el) return;
  const n = e - s + 1;
  const acumulado = (serie) => {
    let k0 = s;
    while (k0 < e && !serie[k0]) k0++;
    return Array.from({ length: n }, (_, i) => (serie[s + i] && serie[k0] && s + i >= k0 ? (serie[s + i] / serie[k0] - 1) * 100 : 0));
  };
  const series = [{ nome: "Carteira", curto: "Carteira", valores: acumulado(p.cota), cor: COR_CARTEIRA },
    ...refs.map((r) => ({ nome: r.nome, curto: r.curto, valores: acumulado(p.refs[r.id]), cor: r.cor, fraca: true }))];
  const estimados = diasEstimados(h, s);
  desenharLinhas(el, {
    series, n, altura: 300,
    marcasX: marcasX(n), rotuloX: (i) => dataCurtaAno(h.datas[s + i]),
    formatoY: (v) => `${formato1.format(v)}%`,
    faixas: estimados >= 5 ? [{ de: 0, ate: estimados, rotulo: "estimado" }] : [],
    rotuloFim: (serie) => `${serie.curto} ${pct2(serie.valores[serie.valores.length - 1])}`,
    dica: (i) => `<div class="t">${dataBR(h.datas[s + i])}</div>${series.map((x) => linhaDica(x.cor, x.nome, pct2(x.valores[i]))).join("")}${linhaDica(null, "Patrimônio", brl(h.carteira.valor[s + i]))}`,
  });
}

function secaoAnoAno(h, p, refs, cartao, topoCartao) {
  const fimMes = new Map();
  h.datas.forEach((d, k) => fimMes.set(d.slice(0, 7), k));
  const meses = [...fimMes.keys()];
  const anteriorDe = (mes) => { const j = meses.indexOf(mes); return j > 0 ? fimMes.get(meses[j - 1]) : 0; };
  const razao = (serie, k0, k) => (serie[k0] && serie[k] ? (serie[k] / serie[k0] - 1) * 100 : null);
  const mensal = (serie, mes) => (fimMes.has(mes) ? razao(serie, anteriorDe(mes), fimMes.get(mes)) : null);
  const anos = [...new Set(meses.map((m) => m.slice(0, 4)))].sort().reverse();
  const doAno = (ano) => meses.filter((m) => m.startsWith(ano));
  const anual = (serie, ano) => { const ms = doAno(ano); return razao(serie, anteriorDe(ms[0]), fimMes.get(ms[ms.length - 1])); };
  const acumulado = (serie, ano) => { const ms = doAno(ano); return razao(serie, 0, fimMes.get(ms[ms.length - 1])); };
  // Meses até o da primeira movimentação conhecida são estimados (ver nota do gráfico).
  const mesConfiavel = h.confiavelDesde && h.confiavelDesde > h.datas[0] ? h.confiavelDesde.slice(0, 7) : null;
  const estimado = (mes) => mesConfiavel && mes <= mesConfiavel;

  const linhas = [{ nome: "Carteira", serie: p.cota, cor: COR_CARTEIRA, principal: true },
    ...refs.map((r) => ({ nome: r.nome, serie: p.refs[r.id], cor: r.cor }))];
  const celula = (v, linha, mes) => {
    if (!valido(v)) return `<td class="direita num mudo">—</td>`;
    const classes = [linha.principal ? sinal(v) : "mudo", mes && estimado(mes) ? "estimado" : ""].join(" ");
    return `<td class="direita num ${classes}"${mes && estimado(mes) ? ` title="estimado"` : ""}>${pctSemSinal(v)}</td>`;
  };
  const corpo = anos.map((ano) => linhas.map((l, j) => `<tr class="${j === linhas.length - 1 ? "fim-ano" : ""}">
    ${j === 0 ? `<td rowspan="${linhas.length}" class="num" style="vertical-align:top"><b>${ano}</b></td>` : ""}
    <td><span class="barra-serie" style="background:${l.cor}"></span>${esc(l.nome)}</td>
    ${MESES.map((_, m) => celula(mensal(l.serie, `${ano}-${String(m + 1).padStart(2, "0")}`), l, `${ano}-${String(m + 1).padStart(2, "0")}`)).join("")}
    ${celula(anual(l.serie, ano), l)}${celula(acumulado(l.serie, ano), l)}</tr>`).join("")).join("");

  // Resumo só com meses que não são estimados.
  const confiaveis = meses.filter((m) => !estimado(m)).map((m) => ({ mes: m, r: mensal(p.cota, m), cdi: mensal(p.refs.cdi, m) })).filter((x) => valido(x.r));
  const melhor = confiaveis.reduce((a, x) => (!a || x.r > a.r ? x : a), null);
  const pior = confiaveis.reduce((a, x) => (!a || x.r < a.r ? x : a), null);
  const resumo = melhor ? `<div class="resumo-meses">
      <span>Melhor mês <b class="positivo">${pct2(melhor.r)}</b> (${esc(nomeMesCurto(melhor.mes))})</span>
      <span>Pior mês <b class="${sinal(pior.r)}">${pct2(pior.r)}</b> (${esc(nomeMesCurto(pior.mes))})</span>
      <span>Meses positivos <b>${confiaveis.filter((x) => x.r > 0).length} de ${confiaveis.length}</b></span>
      ${temDados(h, "cdi") ? `<span>Acima do CDI <b>${confiaveis.filter((x) => valido(x.cdi) && x.r > x.cdi).length} de ${confiaveis.length}</b></span>` : ""}
    </div>` : "";
  return cartao("c12", `${topoCartao("Comparação ano a ano", `<span class="mudo" style="font-size:12px">todo o histórico · rentabilidade de cada mês</span>`)}
    ${resumo}
    <div class="tabela-envolve" style="margin-top:10px"><table class="tabela compacta ano-a-ano"><thead><tr><th>Ano</th><th></th>${MESES.map((m) => `<th class="direita">${m}</th>`).join("")}<th class="direita">Ano</th><th class="direita">Acumulado</th></tr></thead>
    <tbody>${corpo}</tbody></table></div>
    ${mesConfiavel ? `<p class="mudo" style="font-size:12px;margin:8px 0 0">Meses em itálico são estimados (antes de o banco informar as compras e vendas). Melhor e pior mês consideram só os meses a partir de ${esc(nomeMesCurto(meses.find((m) => !estimado(m)) || mesConfiavel))}. O primeiro e o último mês são parciais.</p>` : ""}`);
}

function secaoClasses(h, p, s, e, R, cartao, topoCartao) {
  const { ativos, classes } = contribuicoes(h, p, s, e);
  const linhasClasse = CLASSES_INVESTIMENTO.filter((cl) => classes[cl.id]?.dias).map((cl) => {
    const c = classes[cl.id];
    const rent = (c.fator - 1) * 100;
    const refId = REFERENCIA_CLASSE[cl.id];
    const rentRef = (c.fatorRef - 1) * 100;
    const doCdi = refId === "cdi" && rentRef > 0 ? `<div class="mudo" style="font-size:11px">${formato1.format((rent / rentRef) * 100)}% do CDI</div>` : "";
    return `<tr><td><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${cl.cor}"></span>${esc(cl.nome)}</span></td>
      <td class="direita num ${sinal(rent)}">${pct2(rent)}</td>
      <td class="direita num mudo">${esc(REF[refId].nome)}<div style="font-size:11px">${pct2(rentRef)}</div></td>
      <td class="direita num"><span class="${sinal(rent - rentRef)}">${pp(rent - rentRef)}</span>${doCdi}</td>
      <td class="direita num ${sinal(c.contrib)}">${pp(c.contrib)}</td></tr>`;
  }).join("");

  const lista = ativos.filter((a) => Math.abs(a.contrib) >= 0.005).sort((a, z) => z.contrib - a.contrib);
  const maior = Math.max(0.01, ...lista.map((a) => Math.abs(a.contrib)));
  const mostrar = lista.length > 10 ? [...lista.slice(0, 7), ...lista.slice(-3)] : lista;
  const itens = mostrar.map((a) => `<li><div class="meio"><div class="titulo">${esc(a.nome)}${a.ativo ? "" : ` <span class="etiqueta">vendido</span>`}</div>
      <div class="linha2">${esc(a.detalhe || nomeClasse(a.classe).nome)}</div>
      <div class="trilho" style="margin-top:6px"><span style="width:${(Math.abs(a.contrib) / maior) * 100}%;background:${a.contrib >= 0 ? "var(--positivo)" : "var(--negativo)"}"></span></div></div>
      <div class="direita num ${sinal(a.contrib)}"><b>${pp(a.contrib)}</b></div></li>`).join("");

  return `${cartao("c6", `${topoCartao("Cada classe contra o seu índice", `<span class="mudo" style="font-size:12px">no período</span>`)}
      <div class="tabela-envolve" style="margin-top:8px"><table class="tabela compacta"><thead><tr><th>Classe</th><th class="direita">Rentab.</th><th class="direita">Índice</th><th class="direita">Diferença</th><th class="direita">Contrib.</th></tr></thead>
      <tbody>${linhasClasse || `<tr><td colspan="5" class="mudo">Sem dados no período.</td></tr>`}</tbody></table></div>
      <p class="mudo" style="font-size:12px;margin:10px 0 0">Cada classe é medida só nos dias em que você a teve, e o índice nos mesmos dias. Contribuição = quantos pontos percentuais a classe somou à rentabilidade da carteira (${pct2(R)}); a soma das classes dá o total.</p>`)}
    ${cartao("c6", `${topoCartao("O que mais puxou a carteira", `<span class="mudo" style="font-size:12px">contribuição no período</span>`)}
      <ul class="lista">${itens || `<li class="mudo">Sem dados no período.</li>`}</ul>
      ${lista.length > mostrar.length ? `<p class="mudo" style="font-size:12px;margin:8px 0 0">Mostrando os 7 que mais somaram e os 3 que mais tiraram, de ${lista.length} ativos.</p>` : ""}`)}`;
}

function notas(h) {
  const avisos = (h.avisos || []).map((a) => `<li>${esc(a)}</li>`).join("");
  return `<div class="mudo" style="font-size:12px;margin-top:4px">
    <p style="margin:0 0 6px">Como é calculado: o valor de cada dia vem do preço de mercado de cada ativo (Tesouro pelo preço oficial de venda, ações e ETFs pelo fechamento da B3, fundos pela cota da CVM e CDBs pela taxa contratada sobre o CDI/IPCA do dia). A rentabilidade é pelo método de cotas: aportes e resgates não contam como ganho. Valores brutos, antes do IR. Ações e ETFs incluem dividendos e JCP.</p>
    ${avisos ? `<ul style="margin:0;padding-left:18px">${avisos}</ul>` : ""}
  </div>`;
}

// ============================================================ RISCO
function desenharRisco(conteudo, h, ui, redesenhar) {
  const { cartao, topoCartao, tile } = ui;
  const vazio = semHistorico(h);
  if (vazio) { conteudo.innerHTML = vazio; return; }
  const p = preparar(h);
  const { s, e } = janela(h);
  const carteira = estatisticas(p.cota, s, e);
  const cdi = temDados(h, "cdi") ? estatisticas(p.refs.cdi, s, e) : null;
  const ibov = temDados(h, "ibov") ? estatisticas(p.refs.ibov, s, e) : null;
  const sharpe = (st) => (st.vol >= 0.5 && valido(st.anual) && cdi && valido(cdi.anual) ? (st.anual - cdi.anual) / st.vol : null);
  const total = h.carteira.valor[e] || 1;

  // Ativos de hoje no período inteiro (pelo preço de mercado, mesmo antes de você comprar).
  // Títulos idênticos (ex.: vários CDBs 100% do CDI) viram um ponto só.
  const grupos = new Map();
  for (const a of h.ativos.filter((x) => x.ativo && x.valor[e] > 0)) {
    const st = estatisticas(a.indice, s, e);
    if (!valido(st.retorno)) continue;
    const chave = `${a.classe}|${rotuloCurto(a)}|${st.retorno.toFixed(1)}|${st.vol.toFixed(1)}`;
    const g = grupos.get(chave) || { ...st, classe: a.classe, rotulo: rotuloCurto(a), nomes: [], valor: 0, indice: a.indice };
    g.nomes.push(a.detalhe ? `${a.nome} · ${a.detalhe}` : a.nome);
    g.valor += a.valor[e];
    grupos.set(chave, g);
  }
  const lista = [...grupos.values()].map((g) => ({ ...g, rotulo: g.nomes.length > 1 ? `${g.rotulo} (${g.nomes.length})` : g.rotulo, sharpe: sharpe(g) }))
    .sort((a, z) => z.retorno - a.retorno);
  const refsMercado = refsEscolhidas(h).filter((r) => REFERENCIAS_DE_MERCADO.includes(r.id));

  conteudo.innerHTML = `${barraFiltros(h)}${faixaStatus(h)}
    <section class="grade">
      ${cartao("c12", `<div class="tiles">
        ${tile("Volatilidade da carteira", pctSemSinal(carteira.vol), ibov ? `por ano · Ibovespa ${pctSemSinal(ibov.vol)}` : "por ano")}
        ${tile("Maior queda", pct2(carteira.queda), carteira.queda < 0 ? `de ${dataBR(h.datas[carteira.quedaDe])} a ${dataBR(h.datas[carteira.quedaAte])}` : "sem quedas no período", carteira.queda < 0 ? "negativo" : "")}
        ${tile("Índice de Sharpe", valido(sharpe(carteira)) ? formato2.format(sharpe(carteira)) : "—", "retorno acima do CDI por unidade de risco")}
        ${tile("Retorno ao ano", pct2(carteira.anual), cdi ? `CDI ${pct2(cdi.anual)} ao ano` : "", sinal(carteira.anual))}
      </div>`)}
      ${cartao("c7", `${topoCartao("Risco × retorno", `<span class="mudo" style="font-size:12px">cada ativo no período</span>`)}
        <div id="g-dispersao" style="margin-top:10px"></div>
        <div class="legenda">${CLASSES_INVESTIMENTO.filter((cl) => lista.some((g) => g.classe === cl.id)).map((cl) => `<span><span class="ponto" style="background:${cl.cor}"></span>${esc(cl.nome)}</span>`).join("")}
          <span><span class="ponto" style="background:transparent;border:2px solid var(--texto)"></span>Carteira e índices</span></div>`)}
      ${cartao("c5", `${topoCartao("Ativos", `<span class="mudo" style="font-size:12px">do maior para o menor retorno</span>`)}
        <div class="tabela-envolve" style="margin-top:8px"><table class="tabela compacta"><thead><tr><th>Ativo</th><th class="direita">Retorno</th><th class="direita">Risco</th><th class="direita">Sharpe</th><th class="direita">% cart.</th></tr></thead>
        <tbody>${lista.map((g) => `<tr title="${esc(g.nomes.join("\n"))}"><td><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${nomeClasse(g.classe).cor}"></span>${esc(g.rotulo)}</span></td>
          <td class="direita num ${sinal(g.retorno)}">${pct2(g.retorno)}</td><td class="direita num">${pctSemSinal(g.vol)}</td>
          <td class="direita num">${valido(g.sharpe) ? formato2.format(g.sharpe) : `<span class="mudo">—</span>`}</td>
          <td class="direita num mudo">${formato1.format((g.valor / total) * 100)}%</td></tr>`).join("")}</tbody></table></div>`)}
      ${cartao("c12", `${topoCartao("Quedas desde o pico", `<span class="mudo" style="font-size:12px">quanto cada um estava abaixo do seu maior valor no período</span>`)}
        <div id="g-quedas" style="margin-top:12px"></div>
        <div class="legenda"><span><i style="background:${COR_CARTEIRA};height:3px"></i>Carteira</span>${refsMercado.map((r) => `<span><i style="background:${r.cor};height:3px"></i>${esc(r.nome)}</span>`).join("")}</div>`)}
      ${secaoCorrelacao(h, p, lista, refsMercado, s, e, cartao, topoCartao)}
    </section>
    <div class="mudo" style="font-size:12px;margin-top:4px"><p style="margin:0">Risco = volatilidade: o quanto o valor oscila de um dia para o outro, em % ao ano (desvio padrão dos retornos diários × √252). Retorno e risco de cada ativo usam o preço de mercado do período inteiro, mesmo antes de você comprar. CDBs seguem a taxa contratada e quase não oscilam. Sharpe = (retorno ao ano − CDI ao ano) ÷ volatilidade; acima de 1 é considerado bom. Nada disso é recomendação de investimento.</p></div>`;

  ligarFiltros(conteudo, redesenhar);
  graficoDispersao(lista, carteira, h, p, s, e);
  graficoQuedas(h, p, s, e, refsMercado);
}

function graficoDispersao(lista, carteira, h, p, s, e) {
  const el = document.getElementById("g-dispersao");
  if (!el) return;
  const dicaAtivo = (g) => `<div class="t">${esc(g.rotulo)}</div>${g.nomes.length > 1 ? g.nomes.slice(0, 6).map((n) => `<div class="l">${esc(n)}</div>`).join("") : ""}${linhaDica(nomeClasse(g.classe).cor, "Retorno", pct2(g.retorno))}${linhaDica(null, "Risco (volatilidade)", pctSemSinal(g.vol))}${linhaDica(null, "Maior queda", pct2(g.queda))}${linhaDica(null, "Valor hoje", brl(g.valor))}`;
  const pontos = lista.map((g) => ({ x: g.vol, y: g.retorno, cor: nomeClasse(g.classe).cor, rotulo: g.rotulo, dica: dicaAtivo(g) }));
  const referencia = (nome, st) => ({ x: st.vol, y: st.retorno, cor: "var(--texto-2)", oco: true, rotulo: nome,
    dica: `<div class="t">${esc(nome)}</div>${linhaDica(null, "Retorno", pct2(st.retorno))}${linhaDica(null, "Risco (volatilidade)", pctSemSinal(st.vol))}${linhaDica(null, "Maior queda", pct2(st.queda))}` });
  pontos.push({ ...referencia("Carteira", carteira), cor: "var(--texto)" });
  for (const r of REFERENCIAS.filter((x) => (x.id === "cdi" || filtros.refs.has(x.id)) && temDados(h, x.id) && x.id !== "ipca")) {
    const st = estatisticas(p.refs[r.id], s, e);
    if (valido(st.retorno)) pontos.push(referencia(r.nome, st));
  }
  desenharDispersao(el, {
    pontos, altura: 340,
    formatoX: (v) => `${formato1.format(v)}%`, formatoY: (v) => `${formato1.format(v)}%`,
    tituloX: "Risco (volatilidade ao ano) →", tituloY: "Retorno no período",
  });
}

function graficoQuedas(h, p, s, e, refsMercado) {
  const el = document.getElementById("g-quedas");
  if (!el) return;
  const n = e - s + 1;
  const quedas = (serie) => {
    let pico = 0;
    return Array.from({ length: n }, (_, i) => {
      const v = serie[s + i];
      if (!v) return 0;
      pico = Math.max(pico, v);
      return (v / pico - 1) * 100;
    });
  };
  const series = [{ nome: "Carteira", curto: "Carteira", valores: quedas(p.cota), cor: COR_CARTEIRA },
    ...refsMercado.map((r) => ({ nome: r.nome, curto: r.curto, valores: quedas(p.refs[r.id]), cor: r.cor, fraca: true }))];
  desenharLinhas(el, {
    series, n, altura: 220,
    marcasX: marcasX(n), rotuloX: (i) => dataCurtaAno(h.datas[s + i]),
    formatoY: (v) => `${formato1.format(v)}%`,
    rotuloFim: (serie) => `${serie.curto} ${pct2(serie.valores[serie.valores.length - 1])}`,
    dica: (i) => `<div class="t">${dataBR(h.datas[s + i])}</div>${series.map((x) => linhaDica(x.cor, x.nome, pct2(x.valores[i]))).join("")}`,
  });
}

function secaoCorrelacao(h, p, lista, refsMercado, s, e, cartao, topoCartao) {
  // Só o que oscila: CDBs e o CDI quase não variam e não dizem nada aqui.
  const itens = [
    ...lista.filter((g) => g.vol >= 2).map((g) => ({ nome: g.rotulo, diarios: estatisticas(g.indice, s, e).diarios })),
    ...refsMercado.map((r) => ({ nome: r.nome, diarios: estatisticas(p.refs[r.id], s, e).diarios })),
  ];
  if (itens.length < 2) {
    return cartao("c12", `${topoCartao("Correlação")}<p class="mudo">Precisa de pelo menos dois ativos que oscilam de preço no período (ações, fundos, Tesouro) para comparar.</p>`);
  }
  const cor = (c) => {
    const alfa = (0.1 + 0.6 * Math.abs(c)).toFixed(2);
    return c >= 0 ? `rgba(217, 89, 38, ${alfa})` : `rgba(57, 135, 229, ${alfa})`;
  };
  const linhas = itens.map((a, i) => `<tr><th scope="row">${esc(a.nome)}</th>${itens.map((b, j) => {
    if (i === j) return `<td class="num mudo">1</td>`;
    const c = correlacao(a.diarios, b.diarios);
    return valido(c) ? `<td class="num" style="background:${cor(c)}" title="${esc(a.nome)} × ${esc(b.nome)}">${formato2.format(c)}</td>` : `<td class="num mudo">—</td>`;
  }).join("")}</tr>`).join("");
  return cartao("c12", `${topoCartao("Correlação", `<span class="mudo" style="font-size:12px">como os ativos se movem juntos, dia a dia, no período</span>`)}
    <div class="tabela-envolve" style="margin-top:10px"><table class="tabela compacta correlacao"><thead><tr><th></th>${itens.map((a) => `<th>${esc(a.nome)}</th>`).join("")}</tr></thead>
    <tbody>${linhas}</tbody></table></div>
    <div class="escala-correlacao"><span>−1 · andam em sentidos opostos</span><i style="background:linear-gradient(90deg, rgba(57,135,229,.7), rgba(57,135,229,.1), rgba(217,89,38,.1), rgba(217,89,38,.7))"></i><span>+1 · andam juntos</span></div>
    <p class="mudo" style="font-size:12px;margin:8px 0 0">Perto de +1: sobem e caem juntos (diversificam pouco entre si). Perto de 0: sem relação. Negativo: um tende a subir quando o outro cai.</p>`);
}
