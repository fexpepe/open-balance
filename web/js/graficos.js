// Gráficos em SVG/HTML desenhados à mão: linhas, colunas, rosca e calendário de calor.
// Specs: linhas de 2px, barras <= 24px com ponta arredondada de 4px, grade em hairline, dica no hover.
import { compacto, esc } from "./util.js";

const NS = "http://www.w3.org/2000/svg";

// ---------------------------------------------------------------- dica (tooltip)
const dica = () => document.getElementById("dica");

export function mostrarDica(html, x, y) {
  const el = dica();
  el.innerHTML = html;
  el.hidden = false;
  const r = el.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
  el.style.left = `${Math.max(8, left)}px`;
  el.style.top = `${Math.max(8, top)}px`;
}
export function esconderDica() { dica().hidden = true; }

export function linhaDica(cor, rotulo, valor) {
  const marca = cor ? `<span class="ponto" style="background:${cor}"></span>` : "";
  return `<div class="l"><span style="display:inline-flex;align-items:center;gap:6px">${marca}${esc(rotulo)}</span><b>${esc(valor)}</b></div>`;
}

/** Liga a dica a elementos com data-i dentro de `el`. */
export function ligarDica(el, conteudo) {
  el.addEventListener("mousemove", (e) => {
    const alvo = e.target.closest("[data-i]");
    if (!alvo || !el.contains(alvo)) return esconderDica();
    mostrarDica(conteudo(Number(alvo.dataset.i)), e.clientX, e.clientY);
  });
  el.addEventListener("mouseleave", esconderDica);
}

// ---------------------------------------------------------------- escalas
function passoBonito(bruto) {
  const e = 10 ** Math.floor(Math.log10(bruto));
  const f = bruto / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}
function escala(max, divisoes = 3) {
  if (!(max > 0)) max = 1;
  const passo = passoBonito(max / divisoes);
  const topo = Math.ceil(max / passo) * passo;
  const marcas = [];
  for (let v = 0; v <= topo + passo / 2; v += passo) marcas.push(v);
  return { topo, marcas };
}

/** Como escala(), mas aceita valores negativos (o zero vira uma das marcas). */
function escalaComNegativos(min, max, divisoes = 3) {
  if (!(min < 0)) return { ...escala(max, divisoes), fundo: 0 };
  const passo = passoBonito(Math.max(1, max - min) / divisoes);
  const fundo = Math.floor(min / passo) * passo;
  const topo = Math.max(passo, Math.ceil(max / passo) * passo);
  const marcas = [];
  for (let v = fundo; v <= topo + passo / 2; v += passo) marcas.push(Math.abs(v) < passo / 2 ? 0 : v);
  return { topo, fundo, marcas };
}

/** Escala só da faixa ocupada pelos valores, sem forçar o zero (linha de patrimônio, que varia pouco perto do total). */
function escalaDaFaixa(min, max, divisoes = 3) {
  if (!(max > min)) { const folga = Math.abs(max) * 0.05 || 1; min -= folga; max += folga; }
  const passo = passoBonito((max - min) / divisoes);
  const fundo = Math.floor(min / passo) * passo;
  const topo = Math.ceil(max / passo) * passo;
  const marcas = [];
  for (let v = fundo; v <= topo + passo / 2; v += passo) marcas.push(v);
  return { topo, fundo, marcas };
}
let clipes = 0;

function svg(largura, altura, conteudo) {
  return `<svg class="grafico" xmlns="${NS}" width="${largura}" height="${altura}" viewBox="0 0 ${largura} ${altura}" role="img">${conteudo}</svg>`;
}

// ---------------------------------------------------------------- linhas
/**
 * series: [{nome, valores: number[], cor, fraca?, corNegativa?}] — a primeira é a principal (recebe área e ponto final).
 * Valores negativos estendem o eixo abaixo de zero; com corNegativa, o trecho abaixo de zero muda de cor.
 * n: número de pontos no eixo X; rotuloX(i); dica(i) -> html.
 * faixas: [{de, ate, rotulo}] — trechos do eixo X sombreados (ex.: período estimado).
 * rotuloFim(serie) -> texto: rótulo direto no fim de cada linha, com o ponto da cor da série.
 * incluirZero: false deixa o eixo Y só na faixa dos valores (a área vai até o pé do gráfico).
 * destaques: [{i, texto}] — pontos da série principal com rótulo (ex.: máxima e mínima do período).
 */
export function desenharLinhas(el, { series, n, altura = 210, rotuloX = (i) => i + 1, marcasX, dica: dicaFn, formatoY = compacto, faixas = [], rotuloFim,
  incluirZero = true, destaques = [] }) {
  const largura = Math.max(280, el.clientWidth);
  const m = { e: 56, d: rotuloFim ? 116 : 14, t: 10, b: 26 };
  const w = largura - m.e - m.d;
  const h = altura - m.t - m.b;
  const todos = series.flatMap((s) => s.valores);
  const { topo, fundo, marcas } = incluirZero
    ? escalaComNegativos(Math.min(0, ...todos), Math.max(0, ...todos))
    : escalaDaFaixa(Math.min(...todos), Math.max(...todos));
  const x = (i) => m.e + (n <= 1 ? 0 : (i * w) / (n - 1));
  const y = (v) => m.t + h - ((v - fundo) / (topo - fundo)) * h;
  const piso = Math.min(Math.max(0, fundo), topo); // onde a área da série principal termina

  let c = "";
  for (const f of faixas) {
    const x0 = x(Math.max(0, f.de));
    const x1 = x(Math.min(n - 1, f.ate));
    if (x1 <= x0) continue;
    c += `<rect x="${x0}" y="${m.t}" width="${x1 - x0}" height="${h}" fill="var(--texto)" opacity="0.05"/>`;
    if (f.rotulo && x1 - x0 > 60) c += `<text x="${x0 + 6}" y="${m.t + 13}">${esc(f.rotulo)}</text>`;
  }
  for (const v of marcas) {
    c += `<line class="${v === 0 ? "base" : "grade-linha"}" x1="${m.e}" x2="${m.e + w}" y1="${y(v)}" y2="${y(v)}"/>`;
    c += `<text x="${m.e - 8}" y="${y(v) + 4}" text-anchor="end">${esc(formatoY(v))}</text>`;
  }
  for (const i of marcasX || [0, 7, 14, 21, n - 1].filter((i) => i < n)) {
    c += `<text x="${x(i)}" y="${altura - 6}" text-anchor="middle">${esc(rotuloX(i))}</text>`;
  }
  series.forEach((s, idx) => {
    if (!s.valores.length) return;
    const pontos = s.valores.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const area = (cor, clipe) => (idx === 0 && s.valores.length > 1
      ? `<path d="M${pontos[0]} L${pontos.join(" L")} L${x(s.valores.length - 1)},${y(piso)} L${x(0)},${y(piso)} Z" fill="${cor}" opacity="0.10"${clipe}/>` : "");
    const linha = (cor, clipe) => `<path d="M${pontos.join(" L")}" fill="none" stroke="${cor}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity="${s.fraca ? 0.75 : 1}"${clipe}/>`;
    if (s.corNegativa && fundo < 0) {
      // Desenha duas vezes, cada cópia recortada de um lado do zero.
      const id = `clipe-${++clipes}`;
      c += `<clipPath id="${id}-p"><rect x="0" y="0" width="${largura}" height="${y(0)}"/></clipPath>`;
      c += `<clipPath id="${id}-n"><rect x="0" y="${y(0)}" width="${largura}" height="${altura - y(0)}"/></clipPath>`;
      for (const [cor, lado] of [[s.cor, "p"], [s.corNegativa, "n"]]) {
        c += area(cor, ` clip-path="url(#${id}-${lado})"`) + linha(cor, ` clip-path="url(#${id}-${lado})"`);
      }
    } else {
      c += area(s.cor, "") + linha(s.cor, "");
    }
  });
  const principal = series[0];
  if (principal.valores.length) {
    const i = principal.valores.length - 1;
    const corFinal = principal.corNegativa && principal.valores[i] < 0 ? principal.corNegativa : principal.cor;
    c += `<circle cx="${x(i)}" cy="${y(principal.valores[i])}" r="4" fill="${corFinal}" stroke="var(--superficie)" stroke-width="2"/>`;
  }
  for (const d of destaques) {
    // Pílula acima do ponto (abaixo, se não couber), sem sair da área do gráfico.
    const v = principal.valores[d.i];
    if (v === undefined) continue;
    const larguraPilula = d.texto.length * 6.2 + 14;
    const px = Math.max(m.e, Math.min(m.e + w - larguraPilula, x(d.i) - larguraPilula / 2));
    const py = y(v) - 30 >= m.t ? y(v) - 30 : y(v) + 10;
    c += `<circle cx="${x(d.i)}" cy="${y(v)}" r="3.5" fill="${principal.cor}" stroke="var(--superficie)" stroke-width="2"/>`;
    c += `<rect x="${px}" y="${py}" width="${larguraPilula}" height="20" rx="10" fill="var(--superficie-3)" stroke="var(--borda)"/>`;
    c += `<text x="${px + larguraPilula / 2}" y="${py + 14}" text-anchor="middle" style="fill:var(--texto-2)">${esc(d.texto)}</text>`;
  }
  if (rotuloFim) {
    // Rótulos no fim das linhas, afastados para não encavalar (13px entre eles, sem passar do eixo).
    const fins = series.filter((s) => s.valores.length).map((s) => ({ s, y: y(s.valores[s.valores.length - 1]) }))
      .sort((a, z) => a.y - z.y);
    for (let k = 1; k < fins.length; k++) fins[k].y = Math.max(fins[k].y, fins[k - 1].y + 13);
    for (let k = fins.length - 1; k >= 0; k--) {
      fins[k].y = Math.min(fins[k].y, k === fins.length - 1 ? m.t + h + 6 : fins[k + 1].y - 13);
    }
    for (const f of fins) {
      c += `<circle cx="${m.e + w + 10}" cy="${f.y}" r="3.5" fill="${f.s.cor}"/>`;
      c += `<text x="${m.e + w + 18}" y="${f.y + 4}" style="fill:var(--texto-2)">${esc(rotuloFim(f.s))}</text>`;
    }
  }
  c += `<g class="mira" visibility="hidden"><line class="base" y1="${m.t}" y2="${m.t + h}"/>${series.map((s) =>
    `<circle r="4" fill="${s.cor}" stroke="var(--superficie)" stroke-width="2"/>`).join("")}</g>`;
  c += `<rect class="alvo" x="${m.e}" y="${m.t}" width="${w}" height="${h}" fill="transparent"/>`;
  el.innerHTML = svg(largura, altura, c);

  const raiz = el.querySelector("svg");
  const mira = raiz.querySelector(".mira");
  raiz.querySelector(".alvo").addEventListener("mousemove", (e) => {
    const caixa = raiz.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - caixa.left - m.e) / w) * (n - 1))));
    mira.setAttribute("visibility", "visible");
    mira.querySelector("line").setAttribute("x1", x(i));
    mira.querySelector("line").setAttribute("x2", x(i));
    mira.querySelectorAll("circle").forEach((ponto, k) => {
      const v = series[k].valores[i];
      ponto.setAttribute("visibility", v === undefined ? "hidden" : "visible");
      if (v !== undefined) { ponto.setAttribute("cx", x(i)); ponto.setAttribute("cy", y(v)); }
    });
    if (dicaFn) mostrarDica(dicaFn(i), e.clientX, e.clientY);
  });
  raiz.querySelector(".alvo").addEventListener("mouseleave", () => { mira.setAttribute("visibility", "hidden"); esconderDica(); });
}

// ---------------------------------------------------------------- colunas
/** itens: [{rotulo, valor, estilo: "normal" | "destaque" | "previsto", cor?, opacidade?, dica}].
 *  Valores negativos descem abaixo do zero, com a ponta arredondada embaixo. */
export function desenharColunas(el, { itens, altura = 220, formatoY = compacto, rotularDestaque = true }) {
  const largura = Math.max(280, el.clientWidth);
  const m = { e: 56, d: 8, t: 22, b: 26 };
  const w = largura - m.e - m.d;
  const h = altura - m.t - m.b;
  const valores = itens.map((i) => i.valor);
  const { topo, fundo, marcas } = escalaComNegativos(Math.min(0, ...valores), Math.max(0, ...valores));
  const banda = w / Math.max(1, itens.length);
  const larguraBarra = Math.min(24, banda * 0.6);
  const y = (v) => m.t + h - ((v - fundo) / (topo - fundo)) * h;
  const COR = { normal: "#4a4a47", destaque: "var(--acento)", previsto: "var(--acento)" };

  let c = "";
  for (const v of marcas) {
    c += `<line class="${v === 0 ? "base" : "grade-linha"}" x1="${m.e}" x2="${m.e + w}" y1="${y(v)}" y2="${y(v)}"/>`;
    c += `<text x="${m.e - 8}" y="${y(v) + 4}" text-anchor="end">${esc(formatoY(v))}</text>`;
  }
  itens.forEach((it, i) => {
    const cx = m.e + banda * i + banda / 2;
    const x0 = cx - larguraBarra / 2;
    // Ponta da barra (arredondada) no lado oposto ao zero: s = 1 para cima, -1 para baixo.
    const ponta = y(it.valor);
    const s = it.valor >= 0 ? 1 : -1;
    const alturaBarra = Math.abs(y(0) - ponta);
    const r = Math.min(4, alturaBarra, larguraBarra / 2);
    if (alturaBarra > 0.5) {
      c += `<path d="M${x0},${y(0)} V${ponta + s * r} Q${x0},${ponta} ${x0 + r},${ponta} H${x0 + larguraBarra - r} Q${x0 + larguraBarra},${ponta} ${x0 + larguraBarra},${ponta + s * r} V${y(0)} Z" fill="${it.cor || COR[it.estilo] || COR.normal}" opacity="${it.opacidade ?? (it.estilo === "previsto" ? 0.35 : 1)}"/>`;
    }
    if (rotularDestaque && it.estilo === "destaque") {
      c += `<text x="${cx}" y="${s > 0 ? ponta - 7 : ponta + 15}" text-anchor="middle" style="fill:var(--texto);font-weight:600">${esc(formatoY(it.valor))}</text>`;
    }
    c += `<text x="${cx}" y="${altura - 6}" text-anchor="middle">${esc(it.rotulo)}</text>`;
    c += `<rect data-i="${i}" x="${m.e + banda * i}" y="${m.t}" width="${banda}" height="${h}" fill="transparent"/>`;
  });
  el.innerHTML = svg(largura, altura, c);
  ligarDica(el, (i) => itens[i].dica);
}

// ---------------------------------------------------------------- colunas empilhadas
/** itens: [{rotulo, partes: [{valor, cor, opacidade?}], dica}] — partes de baixo para cima, 2px de respiro entre elas. */
export function desenharColunasEmpilhadas(el, { itens, altura = 240, formatoY = compacto }) {
  const largura = Math.max(280, el.clientWidth);
  const m = { e: 56, d: 8, t: 14, b: 26 };
  const w = largura - m.e - m.d;
  const h = altura - m.t - m.b;
  const totais = itens.map((it) => it.partes.reduce((s, p) => s + Math.max(0, p.valor), 0));
  const { topo, marcas } = escala(Math.max(0, ...totais));
  const banda = w / Math.max(1, itens.length);
  const larguraBarra = Math.min(24, banda * 0.6);
  const y = (v) => m.t + h - (v / topo) * h;

  let c = "";
  for (const v of marcas) {
    c += `<line class="${v === 0 ? "base" : "grade-linha"}" x1="${m.e}" x2="${m.e + w}" y1="${y(v)}" y2="${y(v)}"/>`;
    c += `<text x="${m.e - 8}" y="${y(v) + 4}" text-anchor="end">${esc(formatoY(v))}</text>`;
  }
  itens.forEach((it, i) => {
    const cx = m.e + banda * i + banda / 2;
    const x0 = cx - larguraBarra / 2;
    const partes = it.partes.filter((p) => p.valor > 0);
    let base = 0;
    partes.forEach((p, k) => {
      const ultima = k === partes.length - 1;
      const topoSeg = y(base + p.valor);
      const baseSeg = y(base) - (k > 0 ? 2 : 0); // respiro de 2px entre segmentos
      const alturaSeg = baseSeg - topoSeg;
      if (alturaSeg > 0.5) {
        const r = ultima ? Math.min(4, alturaSeg, larguraBarra / 2) : 0;
        c += `<path d="M${x0},${baseSeg} V${topoSeg + r} Q${x0},${topoSeg} ${x0 + r},${topoSeg} H${x0 + larguraBarra - r} Q${x0 + larguraBarra},${topoSeg} ${x0 + larguraBarra},${topoSeg + r} V${baseSeg} Z" fill="${p.cor}" opacity="${p.opacidade ?? 1}"/>`;
      }
      base += p.valor;
    });
    c += `<text x="${cx}" y="${altura - 6}" text-anchor="middle">${esc(it.rotulo)}</text>`;
    c += `<rect data-i="${i}" x="${m.e + banda * i}" y="${m.t}" width="${banda}" height="${h}" fill="transparent"/>`;
  });
  el.innerHTML = svg(largura, altura, c);
  ligarDica(el, (i) => itens[i].dica);
}

// ---------------------------------------------------------------- rosca
/** fatias: [{nome, valor, cor, dica}] */
export function desenharRosca(el, { fatias, tamanho = 180, centro = "", centroSub = "" }) {
  const r = tamanho / 2;
  const ri = r * 0.68;
  const total = fatias.reduce((s, f) => s + Math.max(0, f.valor), 0) || 1;
  let a0 = -Math.PI / 2;
  let c = "";
  const ponto = (ang, raio) => `${(r + raio * Math.cos(ang)).toFixed(2)},${(r + raio * Math.sin(ang)).toFixed(2)}`;
  fatias.forEach((f, i) => {
    const frac = Math.max(0, f.valor) / total;
    if (frac <= 0) return;
    const a1 = a0 + frac * Math.PI * 2 - (frac >= 1 ? 1e-4 : 0);
    const grande = a1 - a0 > Math.PI ? 1 : 0;
    c += `<path data-i="${i}" d="M${ponto(a0, r)} A${r},${r} 0 ${grande} 1 ${ponto(a1, r)} L${ponto(a1, ri)} A${ri},${ri} 0 ${grande} 0 ${ponto(a0, ri)} Z" fill="${f.cor}" stroke="var(--superficie)" stroke-width="2"/>`;
    a0 = a1;
  });
  c += `<text x="${r}" y="${r - 2}" text-anchor="middle" style="fill:var(--texto);font-size:15px;font-weight:650">${esc(centro)}</text>`;
  c += `<text x="${r}" y="${r + 16}" text-anchor="middle">${esc(centroSub)}</text>`;
  el.innerHTML = svg(tamanho, tamanho, c);
  ligarDica(el, (i) => fatias[i].dica);
}

// ---------------------------------------------------------------- dispersão
/**
 * pontos: [{x, y, cor, rotulo, dica, oco?}] — oco = referência (anel sem preenchimento).
 * Os eixos incluem o zero; a dica pega o ponto mais próximo do mouse (até 28px), sem precisar acertar o ponto.
 */
export function desenharDispersao(el, { pontos, altura = 300, formatoX = (v) => v, formatoY = (v) => v, tituloX = "", tituloY = "" }) {
  const largura = Math.max(280, el.clientWidth);
  const m = { e: 56, d: 18, t: 22, b: 42 };
  const w = largura - m.e - m.d;
  const h = altura - m.t - m.b;
  const xs = pontos.map((p) => p.x);
  const ys = pontos.map((p) => p.y);
  const folga = (min, max) => (max - min) * 0.06 || 1;
  const ex = escalaComNegativos(Math.min(0, ...xs), Math.max(0, ...xs) + folga(Math.min(0, ...xs), Math.max(0, ...xs)));
  const ey = escalaComNegativos(Math.min(0, ...ys) - (Math.min(...ys) < 0 ? folga(Math.min(...ys), Math.max(...ys)) : 0),
    Math.max(0, ...ys) + folga(Math.min(0, ...ys), Math.max(0, ...ys)));
  const X = (v) => m.e + ((v - ex.fundo) / (ex.topo - ex.fundo)) * w;
  const Y = (v) => m.t + h - ((v - ey.fundo) / (ey.topo - ey.fundo)) * h;

  let c = "";
  for (const v of ey.marcas) {
    c += `<line class="${v === 0 ? "base" : "grade-linha"}" x1="${m.e}" x2="${m.e + w}" y1="${Y(v)}" y2="${Y(v)}"/>`;
    c += `<text x="${m.e - 8}" y="${Y(v) + 4}" text-anchor="end">${esc(formatoY(v))}</text>`;
  }
  for (const v of ex.marcas) {
    c += `<line class="${v === 0 ? "base" : "grade-linha"}" x1="${X(v)}" x2="${X(v)}" y1="${m.t}" y2="${m.t + h}"/>`;
    c += `<text x="${X(v)}" y="${m.t + h + 16}" text-anchor="middle">${esc(formatoX(v))}</text>`;
  }
  if (tituloX) c += `<text x="${m.e + w}" y="${altura - 4}" text-anchor="end" style="fill:var(--texto-2)">${esc(tituloX)}</text>`;
  if (tituloY) c += `<text x="${m.e}" y="${m.t - 9}" style="fill:var(--texto-2)">${esc(tituloY)}</text>`;

  // Referências desenhadas por baixo e rotuladas primeiro; os demais rótulos só onde não encavalam em outro já posto.
  const ordem = pontos.map((p, i) => i).sort((a, z) => Number(!!pontos[z].oco) - Number(!!pontos[a].oco));
  const caixas = [];
  for (const i of ordem) {
    const p = pontos[i];
    const cx = X(p.x);
    const cy = Y(p.y);
    c += p.oco
      ? `<circle cx="${cx}" cy="${cy}" r="5" fill="var(--superficie)" stroke="${p.cor}" stroke-width="2"/>`
      : `<circle cx="${cx}" cy="${cy}" r="5.5" fill="${p.cor}" stroke="var(--superficie)" stroke-width="2"/>`;
  }
  for (const i of ordem) {
    const p = pontos[i];
    if (!p.rotulo) continue;
    const largo = p.rotulo.length * 6.4;
    let cx = X(p.x) + 9;
    if (cx + largo > m.e + w) cx = X(p.x) - 9 - largo;
    const caixa = { x0: cx, x1: cx + largo, y0: Y(p.y) - 7, y1: Y(p.y) + 7 };
    if (caixas.some((b) => caixa.x0 < b.x1 && caixa.x1 > b.x0 && caixa.y0 < b.y1 && caixa.y1 > b.y0)) continue;
    caixas.push(caixa);
    c += `<text x="${cx}" y="${Y(p.y) + 4}" style="fill:var(--texto-2)">${esc(p.rotulo)}</text>`;
  }
  c += `<circle class="realce" r="9" fill="none" stroke="var(--texto)" stroke-width="1.5" visibility="hidden"/>`;
  c += `<rect class="alvo" x="${m.e}" y="${m.t}" width="${w}" height="${h}" fill="transparent"/>`;
  el.innerHTML = svg(largura, altura, c);

  const raiz = el.querySelector("svg");
  const realce = raiz.querySelector(".realce");
  raiz.querySelector(".alvo").addEventListener("mousemove", (e) => {
    const caixa = raiz.getBoundingClientRect();
    const mx = e.clientX - caixa.left;
    const my = e.clientY - caixa.top;
    let melhor = null;
    let menor = 28 * 28;
    pontos.forEach((p, i) => {
      const d = (X(p.x) - mx) ** 2 + (Y(p.y) - my) ** 2;
      if (d < menor) { menor = d; melhor = i; }
    });
    if (melhor === null) { realce.setAttribute("visibility", "hidden"); return esconderDica(); }
    realce.setAttribute("cx", X(pontos[melhor].x));
    realce.setAttribute("cy", Y(pontos[melhor].y));
    realce.setAttribute("visibility", "visible");
    mostrarDica(pontos[melhor].dica, e.clientX, e.clientY);
  });
  raiz.querySelector(".alvo").addEventListener("mouseleave", () => { realce.setAttribute("visibility", "hidden"); esconderDica(); });
}

// ---------------------------------------------------------------- calendário de calor
/**
 * dias: [{dia, total, dica}] do mês; primeiroDiaSemana: 0 = domingo; hojeDia: dias depois dele ficam tracejados.
 * Intensidade por quantis (5 degraus de um único tom).
 */
export function desenharCalendario(el, { dias, primeiroDiaSemana, hojeDia }) {
  const semanas = Math.ceil((primeiroDiaSemana + dias.length) / 7);
  const valores = dias.filter((d) => d.total > 0).map((d) => d.total).sort((a, b) => a - b);
  const corte = (q) => valores[Math.min(valores.length - 1, Math.floor(q * valores.length))] ?? 0;
  const limites = [0.2, 0.4, 0.6, 0.8].map(corte);
  const OPACIDADE = [0.2, 0.34, 0.52, 0.72, 0.95];
  const nivel = (v) => limites.filter((l) => v > l).length;
  const rotulos = ["D", "S", "T", "Q", "Q", "S", "S"];

  let html = `<div class="calendario" style="grid-template-columns:18px repeat(${semanas},1fr)">`;
  for (let linha = 0; linha < 7; linha++) {
    html += `<span class="semana">${rotulos[linha]}</span>`;
    for (let s = 0; s < semanas; s++) {
      const idx = s * 7 + linha - primeiroDiaSemana;
      const d = dias[idx];
      if (!d) { html += `<span class="dia fora"></span>`; continue; }
      if (hojeDia && d.dia > hojeDia) { html += `<span class="dia futuro">${d.dia}</span>`; continue; }
      if (d.total <= 0) { html += `<span class="dia" data-i="${idx}">${d.dia}</span>`; continue; }
      const n = nivel(d.total);
      const cor = n >= 2 ? "#fff" : "var(--texto)";
      html += `<span class="dia" data-i="${idx}" style="background:rgba(var(--calor),${OPACIDADE[n]});color:${cor}">${d.dia}</span>`;
    }
  }
  html += `</div><div class="escala">Menos ${OPACIDADE.map((o) => `<i style="background:rgba(var(--calor),${o})"></i>`).join("")} Mais</div>`;
  el.innerHTML = html;
  ligarDica(el, (i) => dias[i].dica);
}
