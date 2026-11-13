// Resumo da área Investimentos: evolução do patrimônio (linha, com o período ajustável) e rendimento por mês
// (como no app do Itaú: só o que a carteira ganhou ou perdeu em cada mês, sem contar aportes e resgates).
// Os dois vêm do histórico diário de openbalance/historico.py, o mesmo da sub-aba Rentabilidade.
// O Tesouro Direto tem duas visões: a mercado (o que você receberia vendendo, oscila com os juros) e na curva
// (pela taxa contratada, como no app do banco). A escolha vale para todo o Resumo; a linha mostra as duas.
import { desenharColunas, desenharLinhas, linhaDica } from "./graficos.js";
import { pct2, usarHistorico } from "./rentabilidade.js";
import { brl, brlSinal, compacto, dataBR, esc, nomeMes, nomeMesCurto, somarMeses } from "./util.js";

const COR_GANHO = "var(--s3)";
const COR_PERDA = "var(--s8)";
const OPACIDADE_ESTIMADO = 0.45;
const PERIODOS_LINHA = [["1m", "1M"], ["3m", "3M"], ["6m", "6M"], ["ano", "No ano"], ["12m", "12M"], ["tudo", "Tudo"]];
const PERIODOS_MESES = [["ano", "No ano"], ["12m", "12 meses"], ["tudo", "Tudo"]];
// Cor fixa por visão, nunca pela posição (a escolhida vira a linha principal, mas mantém a cor).
const VISOES = {
  mercado: { nome: "A mercado", cor: "var(--s1)", explica: "o que você receberia vendendo hoje: sobe quando os juros caem e cai quando sobem" },
  curva: { nome: "Na curva", cor: "var(--s2)", explica: "pela taxa contratada de cada título, como no app do banco" },
};

// Escolhas que ficam entre renderizações: visão do Tesouro, período de cada cartão e o último histórico pintado.
export const visao = { tesouro: "mercado" };
const filtros = { linha: "12m", meses: "12m" };
let historico = null;

const formato1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const formatoMi = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// Máxima/mínima: acima de 1 milhão, duas casas (R$ 1,04 mi), para não virar "R$ 1 mi".
const valorCurto = (v) => (Math.abs(v) >= 1e6 ? `R$ ${formatoMi.format(v / 1e6)} mi` : compacto(v));
const sinal = (v) => (v > 0 ? "positivo" : v < 0 ? "negativo" : "");
const soma = (serie, de, ate) => serie.slice(de + 1, ate + 1).reduce((x, v) => x + v, 0);
const nota = (texto) => `<p class="mudo" style="font-size:12px;margin:8px 0 0">${texto}</p>`;
const carregando = nota("Montando o histórico da carteira… Na primeira vez o Open Balance baixa as cotações dos seus ativos; leva cerca de um minuto.");
const comTesouro = (id) => `Com o Tesouro ${VISOES[id].nome.toLowerCase()}`;

/** Séries da visão escolhida e da outra (null quando não há Tesouro, ou o servidor é anterior a esta versão). */
function series(h) {
  const porVisao = { mercado: h.carteira, curva: h.carteiraCurva || null };
  const escolhida = porVisao[visao.tesouro] ? visao.tesouro : "mercado";
  const outra = escolhida === "curva" ? "mercado" : "curva";
  return { escolhida, s: porVisao[escolhida], outra, o: porVisao[outra] };
}

const botoes = (grupo, periodos) => `<div class="segmentos compactos" data-grupo="${grupo}">${periodos.map(([id, nome]) =>
  `<button data-periodo="${id}" class="${filtros[grupo] === id ? "ativo" : ""}">${nome}</button>`).join("")}</div>`;

/** Escolha da visão do Tesouro, acima de tudo no Resumo (só aparece se houver Tesouro avaliado a mercado). */
export function barraTesouro(c) {
  if (!c?.resumoCurva) return "";
  return `<div class="filtros">
    <span class="mudo" style="font-size:12px">Tesouro Direto</span>
    <div class="segmentos compactos">${Object.entries(VISOES).map(([id, v]) =>
      `<button data-visao="${id}" class="${visao.tesouro === id ? "ativo" : ""}">${v.nome}</button>`).join("")}</div>
    <span class="mudo" style="font-size:12px">${VISOES[visao.tesouro].explica}</span>
  </div>`;
}

export function secaoEvolucao(cartao, topoCartao) {
  return cartao("c8", `${topoCartao("Evolução do patrimônio", botoes("linha", PERIODOS_LINHA))}<div id="evolucao-corpo">${carregando}</div>`);
}

export function secaoRendimento(cartao, topoCartao) {
  return cartao("c12", `${topoCartao("Rendimento por mês", botoes("meses", PERIODOS_MESES))}<div id="rendimento-corpo">${carregando}</div>`);
}

/** Liga os botões (período de cada cartão; a visão do Tesouro redesenha o Resumo inteiro) e pinta os dois cartões
 *  quando o histórico estiver disponível. */
export function desenharEvolucao(conteudo, api, redesenharResumo) {
  conteudo.querySelectorAll("[data-grupo] [data-periodo]").forEach((b) => b.addEventListener("click", () => {
    filtros[b.parentElement.dataset.grupo] = b.dataset.periodo;
    b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
    if (historico) pintar(historico);
  }));
  conteudo.querySelectorAll("[data-visao]").forEach((b) => b.addEventListener("click", () => {
    if (visao.tesouro === b.dataset.visao) return;
    visao.tesouro = b.dataset.visao;
    redesenharResumo();
  }));
  usarHistorico(api, pintar);
}

function pintar(h, erro) {
  const corpoLinha = document.getElementById("evolucao-corpo");
  const corpoMeses = document.getElementById("rendimento-corpo");
  if (!corpoLinha || !corpoMeses) return; // já saiu do Resumo
  historico = h;
  let aviso = null;
  if (erro) aviso = nota(`Não consegui montar o histórico da carteira: ${esc(erro.message)}`);
  else if (!h || h.vazio) aviso = carregando;
  else if (!h.datas?.length) aviso = nota("As cotações ainda estão sendo baixadas; os gráficos aparecem sozinhos.");
  else if (!h.carteira.ganho || (visao.tesouro === "curva" && !h.carteiraCurva)) {
    aviso = nota("Feche a janela do Open Balance e abra de novo para ver estes gráficos (o servidor ainda está rodando a versão anterior).");
  }
  if (aviso) { corpoLinha.innerHTML = corpoMeses.innerHTML = aviso; return; }
  pintarLinha(h, corpoLinha);
  pintarMeses(h, corpoMeses);
}

// ============================================================ evolução do patrimônio (linha)
/** Índice do dia-base do período: o último pregão antes dele começar. */
function inicioDoPeriodo(datas, periodo) {
  const ultima = datas[datas.length - 1];
  const meses = { "1m": 1, "3m": 3, "6m": 6, "12m": 12 }[periodo];
  const alvo = meses ? `${somarMeses(ultima.slice(0, 7), -meses)}${ultima.slice(7)}`
    : periodo === "ano" ? `${Number(ultima.slice(0, 4)) - 1}-12-31` : null;
  let s = 0;
  if (alvo) datas.forEach((d, k) => { if (d <= alvo) s = k; });
  return s;
}

/** Dias do período antes das compras e vendas informadas pelo banco (quantidades supostas). */
function diasEstimados(h, s) {
  if (!h.confiavelDesde || h.confiavelDesde <= h.datas[s]) return 0;
  const k = h.datas.findIndex((d) => d >= h.confiavelDesde);
  return (k < 0 ? h.datas.length : k) - s;
}

function pintarLinha(h, corpo) {
  const { datas } = h;
  const { escolhida, s: serie, outra, o: serieOutra } = series(h);
  const { valor, fluxo, ganho, cota } = serie;
  const e = datas.length - 1;
  const s = inicioDoPeriodo(datas, filtros.linha);
  const valores = valor.slice(s, e + 1);
  const valoresOutra = serieOutra ? serieOutra.valor.slice(s, e + 1) : null;
  const n = valores.length;
  const rendimento = soma(ganho, s, e);
  const aportes = soma(fluxo, s, e);
  const iMax = valores.indexOf(Math.max(...valores));
  const iMin = valores.indexOf(Math.min(...valores));
  const estimados = diasEstimados(h, s);
  // Quanto a marcação a mercado do Tesouro soma (juros caíram) ou tira (juros subiram) em relação à curva.
  const marcacao = h.carteiraCurva ? (i) => h.carteira.valor[s + i] - h.carteiraCurva.valor[s + i] : null;
  const progresso = h.progresso?.rodando ? nota(`Baixando cotações (${h.progresso.feitas} de ${h.progresso.total || "?"}); o gráfico se completa sozinho.`) : "";
  const notaEstimado = !h.confiavelDesde
    ? nota("Sem as compras e vendas (posições importadas por arquivo não trazem esse histórico), o gráfico simula as quantidades de hoje ao longo de todo o período.")
    : estimados >= 5 ? nota(`Trecho sombreado (até ${dataBR(h.confiavelDesde)}): o banco só informa compras e vendas a partir dessa data; antes dela o Open Balance supõe as mesmas quantidades.`) : "";
  const legenda = serieOutra ? `<div class="legenda">${[escolhida, outra].map((id) =>
    `<span><i style="background:${VISOES[id].cor};height:3px"></i>${comTesouro(id)}</span>`).join("")}</div>` : "";
  // Saldo em conta aplicado automaticamente: o banco não manda o histórico, só entra desde que o Open Balance o guarda.
  const kConta = Math.min(...h.ativos.filter((a) => String(a.id).startsWith("conta:")).map((a) => a.valor.findIndex((v) => v > 0)).filter((k) => k >= 0));
  const notaConta = Number.isFinite(kConta) && kConta > s
    ? ` O saldo em conta aplicado automaticamente entra a partir de ${dataBR(datas[kConta])}, quando o Open Balance começou a guardá-lo (o banco não manda o histórico desse saldo).` : "";

  corpo.innerHTML = `<div class="sub" style="margin-top:6px">De ${dataBR(datas[s])} a ${dataBR(datas[e])}:
      variação <b class="${sinal(valor[e] - valor[s])}">${brlSinal(valor[e] - valor[s])}</b> ·
      rendimento <b class="${sinal(rendimento)}">${brlSinal(rendimento)}</b> (${pct2((cota[e] / cota[s] - 1) * 100)}) ·
      aportes − resgates ${brlSinal(aportes)}${marcacao
        ? ` · marcação a mercado do Tesouro hoje <b class="${sinal(marcacao(n - 1))}">${brlSinal(marcacao(n - 1))}</b>` : ""}</div>
    <div id="g-patrimonio" style="margin-top:12px"></div>
    ${legenda}${progresso}${notaEstimado}
    ${nota(`Valor de cada dia pelas cotações de fechamento (Tesouro Transparente, CVM e Yahoo Finance) e pela taxa contratada dos CDBs; o último ponto pode diferir um pouco do valor que o banco informa.${serieOutra
      ? " A distância entre as linhas é a marcação a mercado do Tesouro: com os juros em queda, a linha a mercado passa da curva." : ""}${notaConta}`)}`;

  const el = document.getElementById("g-patrimonio");
  const curta = n <= 70; // até ~3 meses, o ano nas datas do eixo só ocupa espaço
  const marcas = Math.max(3, Math.min(6, Math.floor(el.clientWidth / 80))); // no celular cabem menos datas
  const linhas = [{ id: escolhida, nome: VISOES[escolhida].nome, valores, cor: VISOES[escolhida].cor },
    ...(valoresOutra ? [{ id: outra, nome: VISOES[outra].nome, valores: valoresOutra, cor: VISOES[outra].cor, fraca: true }] : [])];
  desenharLinhas(el, {
    series: linhas, n, altura: 260, incluirZero: false,
    marcasX: [...new Set(Array.from({ length: marcas }, (_, j) => Math.round((j * (n - 1)) / (marcas - 1))))],
    rotuloX: (i) => (curta ? dataBR(datas[s + i]).slice(0, 5) : `${dataBR(datas[s + i]).slice(0, 6)}${datas[s + i].slice(2, 4)}`),
    rotuloFim: valoresOutra && el.clientWidth > 600 ? (x) => `${x.nome} ${valorCurto(x.valores[x.valores.length - 1])}` : undefined,
    faixas: estimados >= 5 ? [{ de: 0, ate: estimados, rotulo: "estimado" }] : [],
    destaques: iMax === iMin ? [] : [{ i: iMax, texto: `Máx. ${valorCurto(valores[iMax])}` }, { i: iMin, texto: `Mín. ${valorCurto(valores[iMin])}` }],
    dica: (i) => `<div class="t">${dataBR(datas[s + i])}</div>${linhas.map((x) => linhaDica(x.cor, valoresOutra ? comTesouro(x.id) : "Patrimônio", brl(x.valores[i]))).join("")}${marcacao
      ? linhaDica(null, "Marcação a mercado", brlSinal(marcacao(i))) : ""}${i
      ? linhaDica(null, `Rendimento desde ${dataBR(datas[s]).slice(0, 5)}`, brlSinal(soma(ganho, s, s + i)))
        + linhaDica(null, "Aportes − resgates", brlSinal(soma(fluxo, s, s + i)))
      : ""}`,
  });
}

// ============================================================ rendimento por mês (colunas)
function pintarMeses(h, corpo) {
  const { datas } = h;
  const { escolhida, s: serie, outra, o: serieOutra } = series(h);
  const { cota, fluxo, ganho, valor } = serie;
  const cdi = h.indices.cdi || [];
  // Último pregão de cada mês; cada mês rende do fechamento do mês anterior até o seu.
  const fimMes = new Map();
  datas.forEach((d, k) => fimMes.set(d.slice(0, 7), k));
  const todos = [...fimMes.keys()];
  const atual = todos[todos.length - 1];
  const primeiro = filtros.meses === "12m" ? somarMeses(atual, -11) : filtros.meses === "ano" ? `${atual.slice(0, 4)}-01` : todos[0];
  const meses = todos.map((mes, j) => {
    const k0 = j > 0 ? fimMes.get(todos[j - 1]) : 0;
    const k = fimMes.get(mes);
    const rendimento = soma(ganho, k0, k);
    return {
      mes, k0, k, rendimento, aportes: soma(fluxo, k0, k), valor: valor[k],
      rentabilidade: (cota[k] / cota[k0] - 1) * 100,
      outra: serieOutra ? soma(serieOutra.ganho, k0, k) : null,
      cdi: cdi[k0] && cdi[k] ? (cdi[k] / cdi[k0] - 1) * 100 : null,
      estimado: !h.confiavelDesde || datas[k0] < h.confiavelDesde,
    };
  }).filter((x) => x.mes >= primeiro);

  const k0 = meses[0].k0;
  const k = meses[meses.length - 1].k;
  const total = meses.reduce((x, m) => x + m.rendimento, 0);
  const r = (cota[k] / cota[k0] - 1) * 100;
  const rCdi = cdi[k0] && cdi[k] ? (cdi[k] / cdi[k0] - 1) * 100 : null;
  const algumEstimado = meses.some((m) => m.estimado);
  const nomeOutra = serieOutra ? comTesouro(outra) : "";
  const totalOutra = serieOutra ? meses.reduce((x, m) => x + m.outra, 0) : null;

  corpo.innerHTML = `<div class="heroi ${sinal(total)}">${brlSinal(total)}</div>
    <div class="sub">rendimento de ${dataBR(datas[Math.min(k0 + 1, k)])} a ${dataBR(datas[k])}${serieOutra ? ` com o Tesouro ${VISOES[escolhida].nome.toLowerCase()}` : ""} ·
      carteira <b class="${sinal(r)}">${pct2(r)}</b>${rCdi > 0 ? ` · <b>${formato1.format((r / rCdi) * 100)}% do CDI</b> (CDI ${pct2(rCdi)})` : ""} ·
      média de ${brlSinal(total / meses.length)} por mês${serieOutra
        ? ` · ${nomeOutra.replace(/^Com/, "com")}: <b class="${sinal(totalOutra)}">${brlSinal(totalOutra)}</b> (${pct2((serieOutra.cota[k] / serieOutra.cota[k0] - 1) * 100)})` : ""}</div>
    <div id="g-rendimento" style="margin-top:12px"></div>
    <div class="legenda"><span><i style="background:${COR_GANHO};height:8px"></i>Ganho no mês</span><span><i style="background:${COR_PERDA};height:8px"></i>Perda no mês</span>${algumEstimado
      ? `<span><i style="background:${COR_GANHO};opacity:${OPACIDADE_ESTIMADO};height:8px"></i>Estimado (antes das compras e vendas informadas pelo banco)</span>` : ""}</div>
    ${nota(`Rendimento é quanto a carteira ganhou ou perdeu no mês sem contar aportes e resgates: a variação de preço mais dividendos, JCP e rendimentos de FIIs.${serieOutra
      ? ` Com o Tesouro a mercado, os meses de juros em alta pesam para baixo e os de juros em queda para cima; na curva, o Tesouro rende só a taxa contratada, como no app do banco. A escolha fica no topo do Resumo.` : ""}`)}`;

  // Com muitos meses (ou tela estreita), rotula um a cada `passo`, sempre o mais recente.
  const el = document.getElementById("g-rendimento");
  const passo = Math.ceil(meses.length / Math.max(2, Math.min(13, Math.floor((el.clientWidth - 64) / 46))));
  desenharColunas(el, {
    altura: 230, rotularDestaque: false,
    itens: meses.map((m, i) => ({
      rotulo: (meses.length - 1 - i) % passo === 0 ? nomeMesCurto(m.mes) : "",
      valor: m.rendimento, cor: m.rendimento >= 0 ? COR_GANHO : COR_PERDA, opacidade: m.estimado ? OPACIDADE_ESTIMADO : 1,
      dica: `<div class="t">${esc(nomeMes(m.mes))}${m.mes === atual ? ` (até ${dataBR(datas[m.k]).slice(0, 5)})` : ""}</div>
        ${linhaDica(m.rendimento >= 0 ? COR_GANHO : COR_PERDA, "Rendimento", brlSinal(m.rendimento))}
        ${linhaDica(null, "Rentabilidade", pct2(m.rentabilidade))}
        ${m.cdi === null ? "" : linhaDica(null, "CDI no mês", pct2(m.cdi))}
        ${serieOutra ? linhaDica(null, nomeOutra, brlSinal(m.outra)) : ""}
        ${linhaDica(null, "Aportes − resgates", brlSinal(m.aportes))}
        ${linhaDica(null, "Patrimônio no fim do mês", brl(m.valor))}
        ${m.estimado ? `<div class="mudo" style="font-size:11px;margin-top:4px">estimado: quantidades supostas</div>` : ""}`,
    })),
  });
}
