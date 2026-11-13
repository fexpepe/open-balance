// Aba "A revisar": despesas em categorias genéricas (Serviços, Pix, Boleto, Outros…) agrupadas por recebedor.
// A decisão de cada grupo vira uma regra comum (/api/regras), que vale para o histórico e para o que vier depois.
// O agrupamento e a sugestão de categoria ficam no backend (openbalance/revisao.py).
import { impacto } from "./dados.js";
import { brl, dataBR, dataCurta, esc, NATUREZAS, nomeMes } from "./util.js";

// Mesmo conjunto de openbalance/revisao.py (GENERICAS). Serve para o indicador antes de a lista carregar.
export const GENERICAS = new Set([
  "07000000", "05000000", "05010000", "05030000", "05040000", "05060000", "05070000", "05080000",
  "05090000", "05090001", "05090002", "05090003", "05090004", "05090005", "99999999",
]);

let cache = { dados: null, revisao: null, erro: null, carregando: null };
let verIgnorados = false;

/** Quanto do gasto do mês está em categoria genérica: { valor, total, fracao }. */
export function fatiaGenerica(base, mes) {
  let valor = 0;
  let total = 0;
  for (const t of base.doMes(mes)) {
    if (t.natureza !== "despesa") continue;
    const v = impacto(t);
    total += v;
    if (GENERICAS.has(t.categoriaId)) valor += v;
  }
  return { valor, total, fracao: total > 0 ? Math.max(0, valor / total) : 0 };
}

/** Frase curta para a aba Categorias. */
export function resumoGenerico(base, mes) {
  const f = fatiaGenerica(base, mes);
  if (f.valor <= 0) return "";
  return `${Math.round(f.fracao * 100)}% do gasto do mês está em categoria genérica · <a class="link" href="#/revisar">revisar ↗</a>`;
}

async function buscar(estado, api) {
  if (cache.dados === estado.dados && (cache.revisao || cache.erro)) return;
  if (cache.carregando && cache.dados === estado.dados) return cache.carregando;
  cache = { dados: estado.dados, revisao: null, erro: null, carregando: null };
  cache.carregando = api("/api/revisao")
    .then((r) => { cache.revisao = r; })
    .catch((e) => { cache.erro = e.message; })
    .finally(() => { cache.carregando = null; });
  return cache.carregando;
}

export async function telaRevisar(conteudo, estado, ui) {
  const { api } = ui;
  const pronto = cache.dados === estado.dados && cache.revisao;
  if (!pronto) {
    desenhar(conteudo, estado, ui, null);
    await buscar(estado, api);
    if (location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] !== "revisar") return;  // o usuário já saiu da aba
  }
  desenhar(conteudo, estado, ui, cache.revisao);
}

function desenhar(conteudo, estado, ui, r) {
  const { cartao, topoCartao } = ui;
  const b = estado.base;
  const mes = estado.mes;
  const f = fatiaGenerica(b, mes);
  const grupos = r ? r.grupos.filter((g) => g.ignorado === verIgnorados) : [];
  const pendentes = r ? r.grupos.filter((g) => !g.ignorado) : [];
  const nIgnorados = r ? r.grupos.length - pendentes.length : 0;
  const totalPendente = pendentes.reduce((s, g) => s + g.total, 0);

  const indicador = cartao("c12", `${topoCartao(`Gasto em ${nomeMes(mes)} em categoria genérica`)}
    <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-top:6px">
      <div class="heroi">${Math.round(f.fracao * 100)}%</div>
      <div class="mudo">${brl(f.valor)} de ${brl(f.total)} em despesas</div>
    </div>
    <div class="trilho grosso" style="margin-top:10px"><span style="width:${Math.min(100, f.fracao * 100)}%;background:var(--negativo)"></span></div>
    <div class="sub" style="margin-top:8px">Categorias como “Serviços”, “Transferência - PIX”, “Boleto” e “Outros” só dizem como você pagou, não com o quê.
      Escolha a categoria de cada recebedor abaixo: vira uma regra, que vale para o histórico todo e para os próximos lançamentos.</div>`);

  let lista;
  if (!r) {
    lista = cache.erro
      ? `<div class="vazio"><h2>Não consegui montar a lista</h2><p>${esc(cache.erro)}</p></div>`
      : `<div class="vazio">Agrupando lançamentos…</div>`;
  } else {
    const cabecalho = `<div class="segmentos" style="margin:0 0 4px">
        <button data-ver="0" class="${verIgnorados ? "" : "ativo"}">A revisar · ${pendentes.length}</button>
        <button data-ver="1" class="${verIgnorados ? "ativo" : ""}">Ignorados · ${nIgnorados}</button>
        <span class="mudo" style="font-size:12px">${verIgnorados ? "" : `${brl(totalPendente)} em despesas desde ${dataBR(r.inicio)}, do maior para o menor`}</span></div>`;
    lista = cabecalho + (grupos.length
      ? `<ul class="lista revisar-lista">${grupos.map((g) => linhaGrupo(g, b, ui)).join("")}</ul>`
      : `<div class="vazio">${verIgnorados ? "Nenhum grupo ignorado." : "Nada a revisar: nenhuma despesa recente em categoria genérica sem regra. 🎉"}</div>`);
  }

  conteudo.innerHTML = `<section class="grade">${indicador}${cartao("c12", lista)}</section>`;
  if (!r) return;
  ligar(conteudo, estado, ui, r);
}

function linhaGrupo(g, b, ui) {
  const atuais = Object.entries(g.categorias).sort((a, z) => z[1] - a[1]).map(([c]) => b.categoria(c).nome).join(", ");
  const sug = g.sugestao;
  const exemplos = g.exemplos.map((t) => `<li><span class="mudo num">${dataCurta(t.data)}</span> <span>${esc(t.descricao)}</span>
    <span class="num">−${brl(t.valor)}</span></li>`).join("");
  const cabeca = `<div class="revisar-cabeca">
      <div class="meio"><div class="titulo">${esc(g.nome)}</div>
        <div class="linha2">${g.quantidade} lançamento${g.quantidade > 1 ? "s" : ""} · último em ${dataBR(g.ultima)} · hoje em ${esc(atuais)}</div></div>
      <div class="direita"><b class="num">${brl(g.total)}</b></div></div>
    <details class="revisar-exemplos"><summary>ver lançamentos</summary><ul>${exemplos}${g.quantidade > g.exemplos.length ? `<li class="mudo">e mais ${g.quantidade - g.exemplos.length}…</li>` : ""}</ul></details>`;

  if (g.ignorado) {
    return `<li class="revisar-grupo">${cabeca}<div class="revisar-acoes"><span class="espaco"></span>
      <button class="botao botao-fantasma" data-desfazer="${esc(g.chave)}">Voltar para a revisão</button></div></li>`;
  }
  if (g.semNome) {
    return `<li class="revisar-grupo">${cabeca}
      <div class="alerta-faixa">O banco não informa o recebedor destes lançamentos, então uma regra pegaria todos eles juntos. Classifique um a um pelo ⋮ na aba Transações.</div>
      <div class="revisar-acoes"><span class="espaco"></span>
        <button class="botao" data-buscar="${esc(g.exemplos[0]?.descricao || "")}">Abrir em Transações</button>
        <button class="botao botao-fantasma" data-ignorar="${esc(g.chave)}">Ignorar</button></div></li>`;
  }
  const outros = g.alcance - g.cobertos;
  const avisos = [
    sug ? `Sugestão: <b>${esc(b.categoria(sug.categoriaId).nome)}</b> ${sug.origem === "historico" ? "(como no seu histórico para esse recebedor)" : "(pelo nome)"}` : "",
    outros > 0 ? `a regra também vale para mais ${outros} lançamento${outros > 1 ? "s" : ""} com esse trecho (entradas, meses antigos ou já categorizados)` : "",
    g.cobertos < g.quantidade ? `o trecho cobre ${g.cobertos} de ${g.quantidade} lançamentos; encurte-o para pegar todos` : "",
  ].filter(Boolean);
  return `<li class="revisar-grupo" data-chave="${esc(g.chave)}">${cabeca}
    <div class="revisar-acoes">
      <label class="revisar-campo">Descrição contém<input type="text" data-campo="padrao" value="${esc(g.padrao)}" autocomplete="off"></label>
      <label class="revisar-campo">Categoria<select data-campo="categoria"><option value="">— manter —</option>${sug ? `<option value="${esc(sug.categoriaId)}" selected>${esc(b.categoria(sug.categoriaId).nome)}</option>` : ""}</select></label>
      <label class="revisar-campo">Natureza<select data-campo="natureza"><option value="">— manter (despesa) —</option>${Object.entries(NATUREZAS)
        .filter(([v]) => v !== "despesa").map(([v, rot]) => `<option value="${v}">${esc(rot)}</option>`).join("")}</select></label>
      <button class="botao botao-acento" data-aplicar>Aplicar</button>
      <button class="botao botao-fantasma" data-ignorar="${esc(g.chave)}">Ignorar</button>
    </div>
    ${avisos.length ? `<div class="mudo revisar-nota">${avisos.join(" · ")}</div>` : ""}</li>`;
}

function ligar(conteudo, estado, ui, r) {
  const { api, avisar, salvarEdicao, irPara } = ui;
  const redesenhar = () => desenhar(conteudo, estado, ui, r);
  // A lista completa de categorias só entra no select quando ele é aberto (são ~90 grupos × ~140 categorias).
  conteudo.querySelectorAll('[data-campo="categoria"]').forEach((sel) => {
    const completar = () => {
      if (sel.dataset.completo) return;
      sel.innerHTML = ui.opcoesCategorias(sel.value, { vazio: "— manter —" });
      sel.dataset.completo = "1";
    };
    sel.addEventListener("mousedown", completar);
    sel.addEventListener("focus", completar);
    sel.addEventListener("keydown", completar);
  });
  conteudo.querySelectorAll("[data-ver]").forEach((bt) => bt.addEventListener("click", () => { verIgnorados = bt.dataset.ver === "1"; redesenhar(); }));
  conteudo.querySelectorAll("[data-buscar]").forEach((bt) => bt.addEventListener("click", () =>
    irPara("transacoes", { busca: bt.dataset.buscar, periodo: "12m", tipo: "despesa", categoria: "", conta: "" })));

  const marcarIgnorado = async (chave, desfazer) => {
    try {
      await api("/api/revisao/ignorar", { chave, desfazer });
      const g = r.grupos.find((x) => x.chave === chave);
      if (g) g.ignorado = !desfazer;
      redesenhar();
      avisar(desfazer ? "O grupo voltou para a revisão." : "Grupo ignorado. Ele fica na lista “Ignorados”.");
    } catch (e) {
      avisar(`Não consegui salvar: ${e.message}`, true);
    }
  };
  conteudo.querySelectorAll("[data-ignorar]").forEach((bt) => bt.addEventListener("click", () => marcarIgnorado(bt.dataset.ignorar, false)));
  conteudo.querySelectorAll("[data-desfazer]").forEach((bt) => bt.addEventListener("click", () => marcarIgnorado(bt.dataset.desfazer, true)));

  conteudo.querySelectorAll("[data-aplicar]").forEach((bt) => bt.addEventListener("click", () => {
    const li = bt.closest("li[data-chave]");
    const padrao = li.querySelector('[data-campo="padrao"]').value.trim();
    const categoriaId = li.querySelector('[data-campo="categoria"]').value || null;
    const natureza = li.querySelector('[data-campo="natureza"]').value || null;
    if (padrao.length < 3) return avisar("O trecho da descrição precisa ter ao menos 3 letras.", true);
    if (!categoriaId && !natureza) return avisar("Escolha uma categoria ou uma natureza.", true);
    bt.disabled = true;
    let nova = null;
    salvarEdicao(async () => { nova = await api("/api/regras", { padrao, categoriaId, natureza }); },
      `Regra “contém ${padrao}” criada.`).then(() => {
      if (!nova) return;
      const n = estado.dados.transacoes.filter((t) => t.regraId === nova.id).length;
      avisar(`Regra “contém ${padrao}” criada e aplicada a ${n} lançamento${n === 1 ? "" : "s"}.`);
    });
  }));
}
