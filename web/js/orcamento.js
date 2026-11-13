// Orçamento mensal por categoria e fechamento do mês.
// Os limites e as sugestões (mediana de 6 meses) vêm de openbalance/orcamento.py; o gasto de cada mês é calculado aqui
// com a mesma Base do resto do painel: só despesas, compra no cartão no mês da data, cada parcela no seu mês.
import { usarHistorico } from "./rentabilidade.js";
import { brl, brlSinal, corGrupo, diasNoMes, esc, iconeGrupo, nomeMes, nomeMesCurto, nomeMesSo, pct, somarMeses } from "./util.js";

const PERTO = 0.8; // aviso a partir de 80% do limite
const DIAS_CARD_FECHAMENTO = 10; // o card do fechamento aparece no topo da Visão geral nos primeiros dias do mês
const CHAVE_FECHAMENTO_VISTO = "openbalance.fechamentoVisto";
const fmtPct = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const fmtPct2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ============================================================ cálculo
/** Situação do orçamento num mês: um item por limite definido, com gasto, % e nível de alerta. */
export function situacaoOrcamento(estado, mes) {
  const b = estado.base;
  const orc = estado.dados.orcamento || { limites: {} };
  const { cats, grupos } = b.porCategoria(mes);
  const atual = mes === b.mesAtual;
  const fracao = atual ? Number(b.hoje.slice(8, 10)) / diasNoMes(mes) : 1;
  const itens = Object.entries(orc.limites).map(([id, limite]) => {
    const ehGrupo = b.grupoDe(id) === id;
    const gasto = Math.max(0, ehGrupo ? grupos.get(id) || 0 : cats.get(id) || 0);
    const p = limite > 0 ? gasto / limite : 0;
    const nivel = p >= 1 ? "estourou" : p >= PERTO ? "perto" : atual && gasto > limite * fracao * 1.1 && fracao < 0.9 ? "ritmo" : "ok";
    return { id, nome: b.categoria(id).nome, grupo: b.grupoDe(id), ehGrupo, limite, gasto, p, nivel };
  }).sort((a, z) => z.p - a.p || z.gasto - a.gasto);
  // Total: grupos com limite + subcategorias cujo grupo não tem limite (sem contar a mesma despesa duas vezes).
  const comLimiteGrupo = new Set(itens.filter((i) => i.ehGrupo).map((i) => i.id));
  const somados = itens.filter((i) => i.ehGrupo || !comLimiteGrupo.has(i.grupo));
  const total = { limite: somados.reduce((s, i) => s + i.limite, 0), gasto: somados.reduce((s, i) => s + i.gasto, 0) };
  const coberto = (catId) => comLimiteGrupo.has(b.grupoDe(catId)) || itens.some((i) => !i.ehGrupo && i.id === catId);
  let fora = 0;
  const foraPorGrupo = new Map();
  for (const [c, v] of cats) {
    if (coberto(c)) continue;
    fora += v;
    foraPorGrupo.set(b.grupoDe(c), (foraPorGrupo.get(b.grupoDe(c)) || 0) + v);
  }
  return { itens, total, fora, foraPorGrupo, fracao, atual, temLimites: itens.length > 0 };
}

const ROTULO_NIVEL = { estourou: "estourou", perto: "perto do limite", ritmo: "acima do ritmo", ok: "dentro" };

function barra(item, fracao) {
  const largura = Math.min(100, item.p * 100);
  return `<div class="orc-barra ${item.nivel}" title="${fmtPct.format(item.p * 100)}% do limite">
    <span style="width:${largura}%"></span>${fracao < 1 ? `<i style="left:${fracao * 100}%" title="ritmo esperado até hoje"></i>` : ""}</div>`;
}

function linhaItem(b, item, fracao, { compacta = false } = {}) {
  const resto = item.limite - item.gasto;
  const nome = item.ehGrupo ? esc(item.nome) : `${esc(item.nome)} <span class="mudo">· ${esc(b.nomeGrupo(item.grupo))}</span>`;
  return `<li class="orc-item" data-cat="${esc(item.id)}">
    <span class="icone-cat">${iconeGrupo(item.grupo)}</span>
    <div class="meio">
      <div class="orc-linha1"><span class="titulo">${nome}</span>
        <span class="num"><b>${brl(item.gasto)}</b> <span class="mudo">de ${brl(item.limite)}</span></span></div>
      ${barra(item, fracao)}
      ${compacta ? "" : `<div class="orc-linha2"><span class="orc-nivel ${item.nivel}">${fmtPct.format(item.p * 100)}% · ${ROTULO_NIVEL[item.nivel]}</span>
        <span class="mudo">${resto >= 0 ? `sobram ${brl(resto)}` : `<span class="negativo">${brl(-resto)} acima</span>`}</span></div>`}
    </div></li>`;
}

/** Frases para os destaques da Visão geral (no máximo duas). */
export function destaquesOrcamento(estado, mes) {
  const s = situacaoOrcamento(estado, mes);
  const estouradas = s.itens.filter((i) => i.nivel === "estourou");
  const perto = s.itens.filter((i) => i.nivel === "perto");
  const frases = [];
  if (estouradas.length) frases.push(`<b class="negativo">Orçamento estourado</b> em ${estouradas.slice(0, 3).map((i) => `<b>${esc(i.nome)}</b> (${fmtPct.format(i.p * 100)}%)`).join(", ")}${estouradas.length > 3 ? ` e mais ${estouradas.length - 3}` : ""}.`);
  if (perto.length) frases.push(`<b class="orc-texto-alerta">Perto do limite</b>: ${perto.slice(0, 3).map((i) => `<b>${esc(i.nome)}</b> (${fmtPct.format(i.p * 100)}%)`).join(", ")}${perto.length > 3 ? ` e mais ${perto.length - 3}` : ""}.`);
  return frases;
}

// ============================================================ Visão geral
/** Card de orçamento da Visão geral (HTML). */
export function cartaoOrcamentoVisao(estado, { cartao, topoCartao }) {
  const b = estado.base;
  const mes = estado.mes;
  const s = situacaoOrcamento(estado, mes);
  if (!s.temLimites) {
    const sug = sugestaoTotal(estado);
    return cartao("c12", `${topoCartao("Orçamento do mês", `<a class="link" href="#/orcamento">definir limites ↗</a>`)}
      <div class="sub">Você ainda não tem orçamento. ${sug ? `Pelos últimos ${estado.dados.orcamento.mesesBase.length} meses, seu gasto típico (mediana) é de <b>${brl(sug)}</b> por mês; dá para começar daí.` : ""}
      <a class="link" href="#/orcamento">Criar orçamento ↗</a></div>`);
  }
  const totalItem = { ...s.total, p: s.total.limite ? s.total.gasto / s.total.limite : 0 };
  totalItem.nivel = totalItem.p >= 1 ? "estourou" : totalItem.p >= PERTO ? "perto" : "ok";
  return cartao("c12", `${topoCartao(`Orçamento de ${nomeMesSo(mes)}`, `<a class="link" href="#/orcamento">ver tudo ↗</a>`)}
    <div class="orc-resumo">
      <div><div class="heroi">${brl(s.total.gasto)} <small>de ${brl(s.total.limite)}</small></div>
        ${barra(totalItem, s.fracao)}
        <div class="sub">${s.total.limite - s.total.gasto >= 0 ? `Sobram <b>${brl(s.total.limite - s.total.gasto)}</b>` : `<b class="negativo">${brl(s.total.gasto - s.total.limite)} acima</b> do orçamento`}${s.atual ? ` · o traço marca o ritmo esperado até hoje` : ""}${s.fora > 0.5 ? ` · ${brl(s.fora)} em categorias sem limite` : ""}</div></div>
      <ul class="lista orc-lista">${s.itens.slice(0, 6).map((i) => linhaItem(b, i, s.fracao, { compacta: true })).join("")}</ul>
    </div>`);
}

function sugestaoTotal(estado) {
  const b = estado.base;
  const sug = estado.dados.orcamento?.sugestoes || {};
  return Object.entries(sug).filter(([id]) => b.grupoDe(id) === id).reduce((s, [, v]) => s + v, 0);
}

/** Card do fechamento no topo da Visão geral nos primeiros dias do mês (some quando você fecha). */
export function cartaoFechamentoTopo(estado, { cartao }) {
  const b = estado.base;
  if (estado.mes !== b.mesAtual || Number(b.hoje.slice(8, 10)) > DIAS_CARD_FECHAMENTO) return "";
  const mes = somarMeses(b.mesAtual, -1);
  if (mes < b.primeiroMes || lerVisto() === mes) return "";
  const r = resumoMes(estado, mes);
  const partes = [`gastou <b>${brl(r.tot.despesas)}</b>${r.variacao === null ? "" : ` (${r.variacao > 0 ? "↑" : "↓"} ${fmtPct.format(Math.abs(r.variacao))}% vs ${nomeMesSo(r.anterior)})`}`];
  if (r.orc.temLimites) {
    const estouradas = r.orc.itens.filter((i) => i.p >= 1).length;
    partes.push(estouradas ? `estourou o orçamento em <b>${estouradas} ${estouradas === 1 ? "categoria" : "categorias"}</b>` : "ficou <b>dentro do orçamento</b> em todas as categorias");
  }
  partes.push(r.tot.resultado >= 0 ? `sobrou <b class="positivo">${brl(r.tot.resultado)}</b>` : `faltou <b class="negativo">${brl(-r.tot.resultado)}</b>`);
  return cartao("c12 orc-fechamento-topo", `<div class="orc-fech-topo">
    <span class="orc-fech-icone" aria-hidden="true">✓</span>
    <div class="meio"><div class="titulo"><b>${esc(nomeMes(mes).replace(/^./, (c) => c.toUpperCase()))} fechou.</b> Você ${partes.join(", ")}.</div></div>
    <a class="botao botao-acento" href="#/fechamento" style="text-decoration:none">Ver fechamento</a>
    <button class="botao-icone" data-fechar-fechamento="${esc(mes)}" aria-label="Dispensar" title="Dispensar (continua na aba Fechamento)">×</button></div>`);
}

export function ligarCartaoFechamento(conteudo, recarregar) {
  conteudo.querySelector("[data-fechar-fechamento]")?.addEventListener("click", (e) => {
    gravarVisto(e.currentTarget.dataset.fecharFechamento);
    recarregar();
  });
}

function lerVisto() { try { return localStorage.getItem(CHAVE_FECHAMENTO_VISTO); } catch { return null; } }
function gravarVisto(mes) { try { localStorage.setItem(CHAVE_FECHAMENTO_VISTO, mes); } catch { /* sem armazenamento */ } }

// ============================================================ aba Orçamento
export function telaOrcamento(conteudo, estado, { cartao, topoCartao, api, avisar, recarregar }) {
  const b = estado.base;
  const mes = estado.mes;
  const orc = estado.dados.orcamento || { limites: {}, sugestoes: {}, mesesBase: [] };
  const s = situacaoOrcamento(estado, mes);
  const nBase = orc.mesesBase.length;
  const editando = estado.orcEditando ?? !s.temLimites;

  // Grupos que aparecem no editor: os com gasto nos últimos meses, os com limite e os com gasto neste mês.
  const { cats, grupos } = b.porCategoria(mes);
  const idsGrupo = new Set([...Object.keys(orc.sugestoes), ...Object.keys(orc.limites), ...cats.keys()].map((id) => b.grupoDe(id)));
  const ordemGrupos = [...idsGrupo].sort((a, z) => (orc.sugestoes[z] || 0) - (orc.sugestoes[a] || 0) || b.nomeGrupo(a).localeCompare(b.nomeGrupo(z)));
  const filhosDe = (g) => [...new Set([...Object.keys(orc.sugestoes), ...Object.keys(orc.limites), ...cats.keys()])]
    .filter((id) => id !== g && b.grupoDe(id) === g)
    .sort((a, z) => (orc.sugestoes[z] || 0) - (orc.sugestoes[a] || 0));

  const campo = (id) => `<input type="number" class="orc-campo" data-limite="${esc(id)}" min="0" step="any" inputmode="decimal"
      value="${orc.limites[id] ?? ""}" placeholder="${orc.sugestoes[id] ? Math.round(orc.sugestoes[id]) : "sem limite"}">`;
  const sugestaoTexto = (id) => (orc.sugestoes[id] ? `<button type="button" class="link orc-usar" data-usar="${esc(id)}" title="Usar a mediana">mediana ${brl(orc.sugestoes[id])}</button>` : `<span class="mudo">—</span>`);
  const editor = `<form id="form-orcamento">
    <div class="sub" style="margin-bottom:10px">Defina um limite por <b>grupo</b> (cobre todas as subcategorias) ou abra o grupo para limitar uma subcategoria específica.
      O valor sugerido é a mediana do gasto dos últimos ${nBase || "—"} meses fechados${nBase ? ` (${nomeMesCurto(orc.mesesBase[0])} a ${nomeMesCurto(orc.mesesBase[nBase - 1])})` : ""}. Deixe vazio para não limitar.</div>
    <div class="orc-editor">${ordemGrupos.map((g) => {
      const filhos = filhosDe(g);
      return `<details class="orc-grupo"${filhos.some((f) => orc.limites[f] !== undefined) ? " open" : ""}>
        <summary><span class="seta">${filhos.length ? "›" : ""}</span><span class="icone-cat">${iconeGrupo(g)}</span><b>${esc(b.nomeGrupo(g))}</b>
          <span class="orc-sug">${sugestaoTexto(g)}</span>${campo(g)}</summary>
        ${filhos.length ? `<ul class="orc-subs">${filhos.map((c) => `<li><span>${esc(b.categoria(c).nome)}</span><span class="orc-sug">${sugestaoTexto(c)}</span>${campo(c)}</li>`).join("")}</ul>` : ""}
      </details>`;
    }).join("") || `<div class="vazio">Ainda não há despesas para sugerir um orçamento.</div>`}</div>
    <div class="modal-acoes" style="margin-top:14px">
      <button type="button" class="botao botao-fantasma" id="orc-preencher">Preencher grupos vazios com a mediana</button>
      <span class="espaco"></span>
      ${s.temLimites ? `<button type="button" class="botao botao-fantasma" id="orc-cancelar">Cancelar</button>` : ""}
      <button type="submit" class="botao botao-acento">Salvar orçamento</button>
    </div></form>`;

  const totalItem = { ...s.total, p: s.total.limite ? s.total.gasto / s.total.limite : 0 };
  totalItem.nivel = totalItem.p >= 1 ? "estourou" : totalItem.p >= PERTO ? "perto" : "ok";
  const foraLista = [...s.foraPorGrupo].filter(([, v]) => v > 0.5).sort((a, z) => z[1] - a[1]);
  const contagem = { estourou: 0, perto: 0, ritmo: 0, ok: 0 };
  s.itens.forEach((i) => { contagem[i.nivel] += 1; });

  conteudo.innerHTML = `<section class="grade">
    ${s.temLimites ? cartao("c12", `${topoCartao(`Orçamento de ${nomeMes(mes)}`, `<span class="mudo" style="font-size:12px">compras no cartão contam no mês da compra; parcelas, cada uma no seu mês</span>`)}
      <div class="heroi">${brl(s.total.gasto)} <small>de ${brl(s.total.limite)} · ${fmtPct.format(totalItem.p * 100)}%</small></div>
      ${barra(totalItem, s.fracao)}
      <div class="sub">${s.total.limite - s.total.gasto >= 0 ? `Sobram <b>${brl(s.total.limite - s.total.gasto)}</b>` : `<b class="negativo">${brl(s.total.gasto - s.total.limite)} acima</b>`}
        · ${contagem.estourou ? `<span class="orc-nivel estourou">${contagem.estourou} estourada(s)</span> · ` : ""}${contagem.perto ? `<span class="orc-nivel perto">${contagem.perto} perto do limite</span> · ` : ""}${contagem.ritmo ? `<span class="orc-nivel ritmo">${contagem.ritmo} acima do ritmo</span> · ` : ""}${contagem.ok} dentro
        ${s.atual ? `<br><span class="mudo">O traço em cada barra marca o ritmo esperado até hoje (dia ${b.hoje.slice(8, 10)} de ${diasNoMes(mes)}).</span>` : ""}</div>`) : ""}
    ${editando ? cartao("c12", `${topoCartao(s.temLimites ? "Editar limites" : "Criar orçamento mensal")}${editor}`) : `
      ${cartao("c8", `${topoCartao("Limites", `<button class="botao botao-fantasma" id="orc-editar">Editar limites</button>`)}
        <ul class="lista orc-lista">${s.itens.map((i) => linhaItem(b, i, s.fracao)).join("")}</ul>`)}
      ${cartao("c4", `${topoCartao("Sem limite neste mês")}
        <div class="heroi">${brl(s.fora)}</div><div class="sub">gasto em categorias sem orçamento</div>
        <ul class="lista">${foraLista.slice(0, 8).map(([g, v]) => `<li><span class="icone-cat">${iconeGrupo(g)}</span><div class="meio"><div class="titulo">${esc(b.nomeGrupo(g))}</div>
          <div class="linha2">${orc.sugestoes[g] ? `mediana ${brl(orc.sugestoes[g])}/mês` : ""}</div></div><div class="direita num">${brl(v)}</div></li>`).join("") || `<li class="mudo">Tudo o que você gastou tem limite.</li>`}</ul>`)}`}
  </section>`;

  conteudo.querySelector("#orc-editar")?.addEventListener("click", () => { estado.orcEditando = true; telaOrcamento(conteudo, estado, { cartao, topoCartao, api, avisar, recarregar }); });
  conteudo.querySelector("#orc-cancelar")?.addEventListener("click", () => { estado.orcEditando = false; telaOrcamento(conteudo, estado, { cartao, topoCartao, api, avisar, recarregar }); });
  conteudo.querySelectorAll(".orc-campo, .orc-usar").forEach((el) => el.addEventListener("click", (e) => e.stopPropagation())); // não abre/fecha o <details>
  conteudo.querySelectorAll("[data-usar]").forEach((botao) => botao.addEventListener("click", (e) => {
    e.preventDefault();
    const id = botao.dataset.usar;
    const input = conteudo.querySelector(`[data-limite="${CSS.escape(id)}"]`);
    if (input) input.value = Math.round(orc.sugestoes[id]);
  }));
  conteudo.querySelector("#orc-preencher")?.addEventListener("click", () => {
    conteudo.querySelectorAll(".orc-grupo > summary .orc-campo").forEach((input) => {
      const id = input.dataset.limite;
      if (!input.value && orc.sugestoes[id]) input.value = Math.round(orc.sugestoes[id]);
    });
  });
  conteudo.querySelector("#form-orcamento")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const limites = {};
    conteudo.querySelectorAll("[data-limite]").forEach((input) => {
      const id = input.dataset.limite;
      const valor = input.value === "" ? null : Number(input.value);
      if ((valor || null) !== (orc.limites[id] ?? null)) limites[id] = valor || null;
    });
    try {
      if (Object.keys(limites).length) await api("/api/orcamento", { limites });
      estado.orcEditando = false;
      avisar("Orçamento salvo.");
      await recarregar();
    } catch (erro) {
      avisar(`Não deu para salvar: ${erro.message}`, true);
    }
  });
}

// ============================================================ aba Fechamento
function resumoMes(estado, mes) {
  const b = estado.base;
  const anterior = somarMeses(mes, -1);
  const tot = b.totais(b.doMes(mes));
  const totAnt = b.totais(b.doMes(anterior));
  const temAnterior = anterior >= b.primeiroMes && totAnt.despesas > 0;
  const variacao = temAnterior ? (tot.despesas / totAnt.despesas - 1) * 100 : null;
  return { mes, anterior, tot, totAnt, temAnterior, variacao, orc: situacaoOrcamento(estado, mes) };
}

/** Mês mostrado no fechamento: o escolhido no seletor se já fechou; senão, o mês anterior. */
export function mesDoFechamento(estado) {
  const b = estado.base;
  return estado.mes < b.mesAtual ? estado.mes : somarMeses(b.mesAtual, -1);
}

export function telaFechamento(conteudo, estado, { cartao, topoCartao, tile, pilulaVariacao, api, irPara }) {
  const b = estado.base;
  const mes = mesDoFechamento(estado);
  if (mes < b.primeiroMes) {
    conteudo.innerHTML = `<div class="vazio"><h2>Ainda não há mês fechado</h2><p>O fechamento aparece quando houver um mês inteiro de dados.</p></div>`;
    return;
  }
  const r = resumoMes(estado, mes);
  const { tot, totAnt, orc } = r;
  const nomeAnt = nomeMesSo(r.anterior);
  const entradas = tot.receitas + tot.rendimentos;
  const taxaPoupanca = entradas > 0 ? (tot.resultado / entradas) * 100 : null;

  // Maiores variações por subcategoria contra o mês anterior.
  const cats = b.porCategoria(mes).cats;
  const catsAnt = b.porCategoria(r.anterior).cats;
  const variacoes = [...new Set([...cats.keys(), ...catsAnt.keys()])]
    .map((c) => ({ c, atual: cats.get(c) || 0, ant: catsAnt.get(c) || 0 }))
    .map((x) => ({ ...x, dif: x.atual - x.ant }))
    .filter((x) => Math.abs(x.dif) >= 1);
  const subiram = variacoes.filter((x) => x.dif > 0).sort((a, z) => z.dif - a.dif).slice(0, 6);
  const cairam = variacoes.filter((x) => x.dif < 0).sort((a, z) => a.dif - z.dif).slice(0, 4);
  const linhaVar = (x) => `<tr data-cat="${esc(x.c)}" style="cursor:pointer">
    <td><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${corGrupo(b.grupoDe(x.c))}"></span>${iconeGrupo(b.grupoDe(x.c))} ${esc(b.categoria(x.c).nome)}</span></td>
    <td class="direita num mudo">${brl(x.ant)}</td><td class="direita num"><b>${brl(x.atual)}</b></td>
    <td class="direita num ${x.dif > 0 ? "negativo" : "positivo"}" title="${x.ant ? `${fmtPct.format((x.atual / x.ant - 1) * 100)}%` : "novo"}">${brlSinal(x.dif)}</td></tr>`;

  const estouradas = orc.itens.filter((i) => i.p >= 1);
  const orcTile = orc.temLimites
    ? tile("Orçamento", `${fmtPct.format((orc.total.gasto / orc.total.limite) * 100)}%`, `${brl(orc.total.gasto)} de ${brl(orc.total.limite)} · ${estouradas.length ? `${estouradas.length} estourada(s)` : "nenhuma estourada"}`, orc.total.gasto > orc.total.limite ? "negativo" : "positivo")
    : tile("Orçamento", "—", `<a class="link" href="#/orcamento">definir limites</a>`);

  conteudo.innerHTML = `<section class="grade">
    ${cartao("c12", `<h1 style="margin:0 0 4px">Fechamento de ${esc(nomeMes(mes))}</h1>
      <div class="sub">Resumo do mês inteiro${estado.mes === b.mesAtual ? ` · use ‹ › no topo para ver outros meses` : ""}</div>
      <div class="tiles" style="margin-top:14px">
        ${tile("Gastos", brl(tot.despesas), r.temAnterior ? `${pilulaVariacao(r.variacao)} vs ${brl(totAnt.despesas)} em ${esc(nomeAnt)}` : "sem mês anterior para comparar")}
        ${orcTile}
        ${tile("Entradas", brl(entradas), tot.rendimentos > 0.01 ? `inclui ${brl(tot.rendimentos)} de rendimentos` : r.temAnterior ? `${brl(totAnt.receitas + totAnt.rendimentos)} em ${esc(nomeAnt)}` : "", "positivo")}
        ${tile("Resultado", brlSinal(tot.resultado), taxaPoupanca === null ? "entradas − gastos" : `${fmtPct.format(taxaPoupanca)}% das entradas`, tot.resultado >= 0 ? "positivo" : "negativo")}
        ${tile("Investido (líquido)", brlSinal(tot.investidoLiquido), `aplicado ${brl(tot.aplicado)} · resgatado ${brl(tot.resgatado)}`)}
        <div class="tile" id="fech-carteira"><div class="rotulo">Carteira vs CDI</div><div class="valor mudo">…</div><div class="detalhe">carregando o histórico</div></div>
      </div>`)}
  </section>
  <section class="grade">
    ${cartao("c5", `${topoCartao("Orçamento", `<a class="link" href="#/orcamento">${orc.temLimites ? "editar ↗" : "criar ↗"}</a>`)}
      ${orc.temLimites ? `<ul class="lista orc-lista">${orc.itens.map((i) => linhaItem(b, i, 1)).join("")}</ul>
        ${orc.fora > 0.5 ? `<div class="rodape-cartao"><span>Gasto em categorias sem limite</span><b>${brl(orc.fora)}</b></div>` : ""}`
        : `<div class="sub">Sem orçamento definido. <a class="link" href="#/orcamento">Crie um</a> a partir da mediana dos últimos meses.</div>`}`)}
    ${cartao("c7", `${topoCartao(`Maiores variações vs ${nomeAnt}`, `<span class="mudo" style="font-size:12px">por categoria</span>`)}
      ${r.temAnterior ? `<div class="tabela-envolve"><table class="tabela" id="t-variacoes"><thead><tr><th>Categoria</th><th class="direita">${esc(nomeMesCurto(r.anterior))}</th><th class="direita">${esc(nomeMesCurto(mes))}</th><th class="direita">Diferença</th></tr></thead>
        <tbody>${subiram.length ? `<tr><td colspan="4" class="mudo orc-sep">Subiram</td></tr>${subiram.map(linhaVar).join("")}` : ""}
        ${cairam.length ? `<tr><td colspan="4" class="mudo orc-sep">Caíram</td></tr>${cairam.map(linhaVar).join("")}` : ""}
        ${!subiram.length && !cairam.length ? `<tr><td colspan="4" class="mudo">Sem variações.</td></tr>` : ""}</tbody></table></div>`
        : `<div class="sub">Sem dados do mês anterior para comparar.</div>`}`)}
  </section>
  <section class="grade">${cartao("c12", `${topoCartao("Investimentos no mês", `<a class="link" href="#/investimentos/rentabilidade">rentabilidade ↗</a>`)}<div id="fech-invest" class="sub">Carregando o histórico da carteira…</div>`)}</section>`;

  conteudo.querySelectorAll("#t-variacoes tr[data-cat]").forEach((tr) => tr.addEventListener("click", () => {
    estado.mes = mes;
    irPara("transacoes", { categoria: tr.dataset.cat, periodo: "mes", tipo: "" });
  }));
  conteudo.querySelectorAll(".orc-item[data-cat]").forEach((li) => li.addEventListener("click", () => {
    estado.mes = mes;
    irPara("transacoes", { categoria: li.dataset.cat, periodo: "mes", tipo: "" });
  }));

  usarHistorico(api, (h, erro) => {
    const tileEl = document.getElementById("fech-carteira");
    const caixa = document.getElementById("fech-invest");
    if (!tileEl || !caixa) return; // a tela já mudou
    const m = h && !h.vazio ? rendimentoNoMes(h, mes) : null;
    if (!m) {
      const motivo = erro ? `Histórico indisponível: ${esc(erro.message)}` : h?.vazio ? "Sem investimentos cadastrados." : h ? `Sem histórico da carteira em ${esc(nomeMesSo(mes))}.` : "Histórico indisponível.";
      tileEl.innerHTML = `<div class="rotulo">Carteira vs CDI</div><div class="valor mudo">—</div><div class="detalhe">${motivo}</div>`;
      caixa.innerHTML = motivo;
      return;
    }
    const doCdi = m.cdi > 0 && m.carteira > 0 ? (m.carteira / m.cdi) * 100 : null;
    const contraCdi = doCdi !== null ? `${fmtPct.format(doCdi)}% do CDI` : `${fmtPct2.format(Math.abs(m.carteira - m.cdi))} p.p. ${m.carteira >= m.cdi ? "acima" : "abaixo"} do CDI`;
    const classe = m.carteira >= m.cdi ? "positivo" : "negativo";
    tileEl.innerHTML = `<div class="rotulo">Carteira vs CDI</div><div class="valor ${classe}">${pctSinal(m.carteira)}</div>
      <div class="detalhe">CDI ${pctSinal(m.cdi)} · ${contraCdi}</div>`;
    caixa.innerHTML = `<div class="tiles">
      ${tile("Rentabilidade da carteira", pctSinal(m.carteira), "método de cotas (sem contar aportes)", classe)}
      ${tile("CDI no mês", pctSinal(m.cdi), `a carteira ficou ${contraCdi.replace(/^(\d)/, "em $1")}`)}
      ${m.curva !== null ? tile("Com o Tesouro na curva", pctSinal(m.curva), "como o banco mostra (taxa contratada)", m.curva >= m.cdi ? "positivo" : "negativo") : ""}
      ${tile("Ganho em reais", brlSinal(m.ganho), "valorização + proventos", m.ganho >= 0 ? "positivo" : "negativo")}
      ${tile("Aportes − resgates", brlSinal(m.fluxo), "na carteira")}
      ${tile("Patrimônio no fim do mês", brl(m.valorFim), `${brlSinal(m.valorFim - m.valorInicio)} no mês`)}
    </div>
    <div class="mudo" style="font-size:12px;margin-top:8px">${m.parcial ? `O histórico começa em ${esc(m.de.split("-").reverse().join("/"))}: o mês não está completo. ` : ""}Do pregão de ${esc(m.de.split("-").reverse().join("/"))} ao de ${esc(m.ate.split("-").reverse().join("/"))}. ${m.curva !== null ? "Tesouro a preço de mercado (o card ao lado mostra na curva)" : "Valores"}; brutos, antes do IR.${m.estimado ? " Antes das primeiras movimentações informadas o histórico é estimado." : ""}</div>`;
  });
}

const pctSinal = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtPct2.format(Math.abs(v))}%`;

/** Rentabilidade da carteira e do CDI no mês, a partir do histórico diário (/api/historico). */
function rendimentoNoMes(h, mes) {
  const datas = h.datas || [];
  const fim = `${mes}-31`;
  const inicio = `${mes}-01`;
  let e = -1;
  for (let k = 0; k < datas.length && datas[k] <= fim; k++) e = k;
  if (e < 0 || datas[e] < inicio) return null;
  let s = -1;
  for (let k = 0; k < datas.length && datas[k] < inicio; k++) s = k;
  const parcial = s < 0;
  if (parcial) s = 0;
  const cota = h.carteira.cota;
  const cdi = h.indices.cdi;
  if (!cota[s] || !cota[e] || !cdi[s] || !cdi[e] || s === e) return null;
  let ganho = 0;
  let fluxo = 0;
  for (let k = s + 1; k <= e; k++) { ganho += h.carteira.ganho?.[k] || 0; fluxo += h.carteira.fluxo?.[k] || 0; }
  return {
    carteira: (cota[e] / cota[s] - 1) * 100, cdi: (cdi[e] / cdi[s] - 1) * 100, ganho, fluxo,
    curva: h.carteiraCurva?.cota?.[s] && h.carteiraCurva.cota[e] ? (h.carteiraCurva.cota[e] / h.carteiraCurva.cota[s] - 1) * 100 : null,
    estimado: Boolean(h.confiavelDesde && h.confiavelDesde > h.datas[0] && mes <= h.confiavelDesde.slice(0, 7)),
    valorInicio: h.carteira.valor[s], valorFim: h.carteira.valor[e], de: datas[s], ate: datas[e], parcial,
  };
}
