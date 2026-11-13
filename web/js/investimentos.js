// Área Investimentos — inspirada em Investidor10, Kinvo, Status Invest e Gorila.
// Sub-abas: Resumo (indicadores, evolução e rendimento por mês em evolucao.js, alocação) · Rentabilidade e Risco (rentabilidade.js) ·
// Proventos (a receber, pela B3) · Composição (meta de alocação, vencimentos, indexadores) · Ativos (classes e encerradas) · Movimentações ·
// Imposto (imposto.js: apuração mensal, DARF e resumo para a declaração).
// Os cálculos vêm prontos do backend (openbalance/carteira.py, historico.py e imposto.py); aqui é só apresentação.
import { barraTesouro, desenharEvolucao, secaoEvolucao, secaoRendimento, visao } from "./evolucao.js";
import { desenharColunas, desenharColunasEmpilhadas, desenharRosca, linhaDica } from "./graficos.js";
import { telaImposto } from "./imposto.js";
import { preCarregarHistorico, telaRentabilidade, telaRisco } from "./rentabilidade.js";
import { avatarInstituicao, brl, brlSinal, compacto, dataBR, esc, horaRelativa, nomeMes, nomeMesCurto, pct, somarMeses } from "./util.js";

export const CLASSES_INVESTIMENTO = [
  { id: "tesouro", nome: "Tesouro Direto", cor: "var(--s1)", icone: "🏛️" },
  { id: "fundos", nome: "Fundos de investimento", cor: "var(--s2)", icone: "🧺" },
  { id: "renda_fixa", nome: "Renda fixa", cor: "var(--s3)", icone: "🏦" },
  { id: "acoes", nome: "Ações", cor: "var(--s4)", icone: "📈" },
  { id: "etf", nome: "ETFs", cor: "var(--s-etf)", icone: "🧾" },
  { id: "fiis", nome: "Fundos imobiliários", cor: "var(--s7)", icone: "🏢" },
  { id: "acoes_exterior", nome: "Ações internacionais", cor: "var(--s-acoes-ext)", icone: "🌎" },
  { id: "reits", nome: "REITs", cor: "var(--s-reits)", icone: "🏙️" },
  { id: "renda_fixa_exterior", nome: "Renda fixa internacional", cor: "var(--s-rf-ext)", icone: "💵" },
  { id: "cripto", nome: "Criptomoedas", cor: "var(--s5)", icone: "🪙" },
  { id: "outros", nome: "Outros", cor: "var(--s-outros)", icone: "📦" },
];
const NOME_ATIVO = { STOCK: "Ação", ETF: "ETF", BDR: "BDR", REAL_ESTATE_FUND: "FII", MULTIMARKET_FUND: "Multimercado",
  FIXED_INCOME_FUND: "Renda fixa", STOCK_FUND: "Ações", INVESTMENT_FUND: "Fundo", CDB: "CDB", LCI: "LCI", LCA: "LCA",
  STRUCTURED_NOTE: "COE", DEBENTURES: "Debêntures", CRI: "CRI", CRA: "CRA", AUTOMATIC_INVESTMENT: "Saldo em conta",
  REIT: "REIT", FOREIGN_STOCK: "Ação", FOREIGN_FIXED_INCOME: "Renda fixa", CRYPTO: "Cripto" };

const formatoQtd = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
// Provento por ação/cota: até 4 casas (R$ 0,2810), como a B3 divulga.
const formatoCota = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 4 });
const porCota = (v) => formatoCota.format(v || 0);
// Quantidade × preço revelaria o valor: entra no borrão do modo privado.
const qtd = (v) => (v === null || v === undefined ? "—" : `<span class="dinheiro">${formatoQtd.format(v)}</span>`);
const etiquetaBolsa = (p) => (p.classe === "fiis" ? (p.tipoB3 === "fiagro" ? "Fiagro" : "FII") : NOME_ATIVO[p.subtipo] || p.subtipo || "");
const semSinal = (v) => pct(v).replace("+", "");
const vazio = `<span class="mudo">—</span>`;

function comSinal(valor, percentual) {
  if (valor === null || valor === undefined) return vazio;
  const pctTexto = percentual === null || percentual === undefined ? "" : ` <span class="mudo">${pct(percentual)}</span>`;
  return `<span class="${valor >= 0 ? "positivo" : "negativo"}">${brlSinal(valor)}</span>${pctTexto}`;
}

function pctDoCdi(p) {
  if (p.pctCdi === null || p.pctCdi === undefined) return vazio;
  const ipca = p.acimaIpca === null || p.acimaIpca === undefined ? "" : `<div class="mudo" style="font-size:11px">IPCA ${pct(p.acimaIpca)}</div>`;
  return `<span class="${p.pctCdi >= 100 ? "positivo" : ""}">${semSinal(p.pctCdi)}</span>${ipca}`;
}

// Tesouro: mostra o preço de mercado usado e o valor na curva (o que o banco/Open Finance informa).
function precoTesouro(p) {
  if (p.fonteValor !== "mercado") return p.compra ? `comprado em ${dataBR(p.compra)}` : "";
  const taxa = p.taxaMercado !== null && p.taxaMercado !== undefined ? ` · taxa hoje ${String(p.taxaMercado).replace(".", ",")}%` : "";
  const curva = p.puCurva ? ` · na curva ${brl(p.puCurva)}` : "";
  return `a mercado: ${brl(p.puMercado)} em ${dataBR(p.dataPreco).slice(0, 5)}${taxa}${curva}`;
}

// Posições que o banco ainda lista, mas que as movimentações mostram resgatadas: ficam fora dos totais.
function notaIgnoradas(c) {
  if (!c?.ignoradas?.length) return "";
  const itens = c.ignoradas.map((x) => `${esc(x.nome)} (${brl(x.valor)}, resgatado em ${dataBR(x.resgate)})`).join("; ");
  return `<p class="mudo" style="font-size:12px;margin:8px 0 0">Fora dos totais: ${itens}. O banco ainda mostra ${c.ignoradas.length === 1 ? "essa posição" : "essas posições"} com o valor parado no dia do resgate, mas as movimentações indicam que ${c.ignoradas.length === 1 ? "ela foi resgatada" : "foram resgatadas"}.</p>`;
}

// Estado da calculadora de aporte (fica entre renderizações).
const calculadora = { aporte: "" };
// Classe clicada na alocação do Resumo: a sub-aba Ativos rola até ela depois de desenhar.
let rolarParaClasse = null;

export function renderInvestimentos(conteudo, estado, ui, sub = "resumo") {
  if (sub === "rentabilidade") return telaRentabilidade(conteudo, estado, ui);
  if (sub === "risco") return telaRisco(conteudo, estado, ui);
  if (sub === "imposto") return telaImposto(conteudo, estado, ui);
  // Já pede o histórico: na primeira vez o servidor leva ~1 minuto baixando cotações.
  if (estado.dados.investimentos.length) preCarregarHistorico(ui.api);
  const { cartao, topoCartao, tile } = ui;
  const d = estado.dados;
  const b = estado.base;
  const c = d.carteira;
  const extra = c?.posicoes || {};
  // No Resumo, o Tesouro pode estar na curva (escolha no topo); nas outras sub-abas fica sempre a mercado.
  const naCurva = sub === "resumo" && visao.tesouro === "curva" && !!c?.resumoCurva;
  const posicoes = d.investimentos.map((p) => {
    const x = { ...p, ...(extra[p.id] || {}) };
    return naCurva && x.saldoCurva !== undefined ? { ...x, saldo: x.saldoCurva } : x;
  });
  const totalPos = posicoes.reduce((s, p) => s + p.saldo, 0);
  const classes = CLASSES_INVESTIMENTO.map((cl) => {
    const lista = posicoes.filter((p) => p.classe === cl.id).sort((a, z) => z.saldo - a.saldo);
    return { ...cl, lista, total: lista.reduce((s, p) => s + p.saldo, 0) };
  }).filter((cl) => cl.lista.length);

  // Servidor aberto antes desta versão não manda a carteira calculada.
  if (posicoes.length && !c) {
    conteudo.innerHTML = `<div class="alerta-faixa">Feche a janela do Open Balance e abra de novo para ver a nova aba de investimentos (o servidor ainda está rodando a versão anterior).</div>`;
    return;
  }

  const semPosicoes = `<div class="alerta-faixa c12">${d.pluggy === false
    ? "Nenhuma posição de investimento ainda. Importe a posição (planilha da B3 ou o modelo) em <b>Importar</b>, no topo da tela."
    : "A Pluggy não retornou posições de investimento para as suas conexões. Normalmente isso acontece quando o consentimento no Meu Pluggy não incluiu <b>investimentos</b>. Reconectar a instituição marcando essa permissão costuma resolver."}</div>`;
  const comPosicoes = (montar) => (posicoes.length ? montar() : [semPosicoes]);
  const telas = {
    resumo: () => comPosicoes(() => [secaoIndicadores(c, naCurva, tile, cartao), secaoEvolucao(cartao, topoCartao), secaoAlocacao(classes, totalPos, cartao, topoCartao),
      secaoRendimento(cartao, topoCartao)]),
    proventos: () => comPosicoes(() => [secaoAReceber(c, cartao, topoCartao), secaoRenda(c, cartao, topoCartao), secaoProventosPorAtivo(c, cartao, topoCartao)]),
    composicao: () => comPosicoes(() => [secaoMetas(classes, totalPos, c.metas || {}, cartao, topoCartao), secaoVencimentos(c, cartao, topoCartao), secaoIndexadores(c, cartao, topoCartao)]),
    ativos: () => comPosicoes(() => [...classes.map((cl) => cartaoClasse(cl, totalPos)), c.encerradas?.length ? secaoEncerradas(c.encerradas, cartao, topoCartao) : "",
      c.ignoradas?.length ? `<div class="c12">${notaIgnoradas(c)}</div>` : ""]),
    movimentacoes: () => [secaoMovimentacoes(b, cartao, topoCartao, tile), secaoEmprestimos(d.emprestimos, cartao, topoCartao)],
  };

  // Mesma largura da Visão geral: grade de 12 colunas.
  const barra = sub === "resumo" && posicoes.length ? barraTesouro(c) : "";
  conteudo.innerHTML = `${barra}<section class="grade">${(telas[sub] || telas.resumo)().join("")}</section>`;

  if (posicoes.length) {
    if (document.getElementById("evolucao-corpo")) desenharEvolucao(conteudo, ui.api, () => renderInvestimentos(conteudo, estado, ui, sub));
    const rosca = document.getElementById("g-carteira");
    if (rosca) desenharRosca(rosca, {
      tamanho: 170, centro: compacto(totalPos), centroSub: "investido",
      fatias: classes.map((cl) => ({
        nome: cl.nome, valor: cl.total, cor: cl.cor,
        dica: `<div class="t">${esc(cl.nome)}</div>${linhaDica(cl.cor, "Valor", brl(cl.total))}${linhaDica(null, "Da carteira", semSinal((cl.total / totalPos) * 100))}${linhaDica(null, "Posições", String(cl.lista.length))}`,
      })),
    });
    graficoProventos(c);
    graficoVencimentos(c);
    ligarMetas(classes, totalPos, ui);
  }
  conteudo.querySelectorAll("[data-classe-link]").forEach((a) => a.addEventListener("click", () => { rolarParaClasse = a.dataset.classeLink; }));
  if (sub === "ativos" && rolarParaClasse) {
    document.getElementById(`classe-${rolarParaClasse}`)?.scrollIntoView({ block: "start" });
    rolarParaClasse = null;
  }
  conteudo.querySelector("#ver-emprestimos")?.addEventListener("click", (e) => {
    e.preventDefault();
    ui.irPara("transacoes", { tipo: "emprestimo", periodo: "tudo", categoria: "", busca: "" });
  });
}

// ============================================================ indicadores (Investidor10)
function secaoIndicadores(c, naCurva, tile, cartao) {
  const r = naCurva ? c.resumoCurva : c.resumo;
  // Quanto a marcação a mercado do Tesouro soma (juros caíram) ou tira (juros subiram) em relação à curva.
  const marcacao = c.resumoCurva ? c.resumo.patrimonio - c.resumoCurva.patrimonio : null;
  const idx = c.indices || {};
  const ar = c.proventos.aReceber;
  const partesRenda = [
    r.rendaFixaMensal ? `renda fixa ~${brl(r.rendaFixaMensal)}` : "",
    r.rendaFiisMensal ? `FIIs ~${brl(r.rendaFiisMensal)}` : "",
    r.rendaAcoesMensal ? `ações ~${brl(r.rendaAcoesMensal)}` : "",
    r.rendaExteriorMensal ? `exterior ~${brl(r.rendaExteriorMensal)}` : "",
    r.rendaOutrosMensal >= 1 ? `outros ~${brl(r.rendaOutrosMensal)}` : "",
  ].filter(Boolean).join(" + ");
  const rentab = [
    r.pctCdi !== null && r.pctCdi !== undefined ? `${semSinal(r.pctCdi)} do CDI` : null,
    idx.cdi12m !== null && idx.cdi12m !== undefined ? `CDI 12m ${semSinal(idx.cdi12m)}` : null,
    idx.ipca12m !== null && idx.ipca12m !== undefined ? `IPCA 12m ${semSinal(idx.ipca12m)}` : null,
  ].filter(Boolean).join(" · ") || "sem índices de referência ainda";
  return cartao("c12", `<div class="tiles">
    ${tile("Patrimônio investido", brl(r.patrimonio), `bruto · líquido estimado ${brl(r.patrimonioLiquido)} · IR estimado ${brl(r.ir)}${marcacao === null ? ""
      : ` · <span title="Diferença entre o Tesouro a mercado e na curva">marcação a mercado do Tesouro <span class="${marcacao >= 0 ? "positivo" : "negativo"}">${brlSinal(marcacao)}</span></span>`}`)}
    ${tile("Valor aplicado", brl(r.aplicado), `${r.semCusto ? `custo conhecido de ${semSinal(r.cobertura * 100)} das aplicações (${r.semCusto} sem custo)` : "custo de todas as posições"}${r.saldoEmConta
      ? ` · fora o saldo em conta (${brl(r.saldoEmConta)})` : ""}`)}
    ${tile("Lucro total", brlSinal(r.lucro), `posições ${brlSinal(r.ganhoAberto)} · vendas ${brlSinal(r.ganhoRealizado)} · proventos ${brl(r.proventos)}`, r.lucro >= 0 ? "positivo" : "negativo")}
    ${tile("Rentabilidade", r.rentabilidade === null || r.rentabilidade === undefined ? "—" : pct(r.rentabilidade), rentab, r.rentabilidade >= 0 ? "positivo" : "negativo")}
    ${tile("Renda por mês", brl(r.rendaMensal), `${partesRenda || "sem renda estimada"} (estimativa bruta)`)}
    ${ar?.ativos ? tile("Proventos a receber", brl(ar.total), `${ar.total ? `já anunciados${ar.ate ? `, até ${dataBR(ar.ate)}` : ""}` : "nada anunciado ainda"}${ar.estimado ? ` · + ~${brl(ar.estimado)} estimado dos FIIs` : ""} · <a class="link" href="#/investimentos/proventos">ver</a>`, ar.total ? "positivo" : "") : ""}
  </div>
  <p class="mudo" style="font-size:12px;margin:10px 0 0">Valores brutos, como no app do banco${r.saldoEmConta
    ? `, com o saldo em conta que o banco aplica automaticamente (${brl(r.saldoEmConta)}, em renda fixa)` : ""}${naCurva ? "; Tesouro Direto na curva (pela taxa contratada de cada título, como o banco informa)"
    : c.precoTesouro?.titulos ? `; Tesouro Direto a preço de mercado de ${esc(dataBR(c.precoTesouro.data))} (o que você receberia vendendo, antes do IR)` : ""}. Rentabilidade = lucro total ÷ valor aplicado (posições com custo conhecido); “% do CDI” compara o ganho bruto com o que o CDI teria rendido nas mesmas datas de aplicação.${idx.cdiAte ? ` CDI até ${esc(nomeMesCurto(idx.cdiAte))}, IPCA até ${esc(nomeMesCurto(idx.ipcaAte || idx.cdiAte))} (fonte: ${esc(Object.values(idx.fonte || {})[0] || "—")}).` : ""}</p>
  ${notaIgnoradas(c)}`);
}

// ============================================================ alocação
function secaoAlocacao(classes, total, cartao, topoCartao) {
  return cartao("c4", `${topoCartao("Ativos na carteira")}
    <div style="display:flex;justify-content:center;margin:10px 0 6px"><div id="g-carteira"></div></div>
    <ul class="lista">${classes.map((cl) => `<li><span class="ponto" style="background:${cl.cor}"></span>
      <div class="meio"><a class="titulo" href="#/investimentos/ativos" data-classe-link="${cl.id}" style="text-decoration:none">${cl.icone} ${esc(cl.nome)}</a></div>
      <div class="direita"><div class="num"><b>${brl(cl.total)}</b></div><div class="linha2 mudo">${semSinal((cl.total / total) * 100)}</div></div></li>`).join("")}</ul>`);
}

// ============================================================ proventos a receber (B3)
const SITUACAO = {
  garantido: `<span class="positivo">garantido</span>`,
  "se mantiver": `<span title="A data com ainda não chegou: recebe quem tiver o ativo no fim desse dia">se mantiver até a data com</span>`,
  estimado: `<span class="mudo" title="O FII ainda não anunciou: repete o último rendimento com as cotas de hoje">estimado</span>`,
};

function secaoAReceber(c, cartao, topoCartao) {
  const a = c.proventos.aReceber;
  if (!a?.ativos) return "";
  const aprox = (x, texto) => (x.situacao === "estimado" ? `~${texto}` : texto);
  const linhas = a.itens.map((x) => `<tr>
    <td><b>${esc(x.codigo)}</b> <span class="etiqueta">${x.classe === "fiis" ? "FII" : "Ação"}</span></td>
    <td>${esc(x.tipo)}${x.referencia ? `<div class="mudo" style="font-size:11px">${esc(x.referencia)}</div>` : ""}</td>
    <td class="num">${aprox(x, dataBR(x.dataCom))}</td>
    <td class="num">${x.pagamento ? aprox(x, dataBR(x.pagamento)) : `<span class="mudo">a definir</span>`}</td>
    <td class="direita num">${porCota(x.porCota)}</td><td class="direita num">${qtd(x.quantidade)}</td>
    <td class="direita num"><b class="${x.situacao === "estimado" ? "mudo" : ""}">${aprox(x, brl(x.valor))}</b></td>
    <td>${x.suposto ? `<span title="Posição importada de planilha, sem as compras e vendas: supõe que você já tinha essa quantidade na data com">se já tinha em ${dataBR(x.dataCom).slice(0, 5)}</span>` : SITUACAO[x.situacao]}</td></tr>`).join("");
  const avisos = [
    a.naoConsultados.length ? `Ainda sem consulta à B3: ${esc(a.naoConsultados.join(", "))} (sai na próxima atualização).` : "",
    a.semQuantidade.length ? `Sem a quantidade de ${esc(a.semQuantidade.join(", "))}: importe a planilha de posição da B3, que traz a coluna Quantidade.` : "",
  ].filter(Boolean).join(" ");
  return cartao("c12", `${topoCartao("Proventos a receber", `<span class="mudo" style="font-size:12px">já anunciados na B3 e ainda não pagos</span>`)}
    <div class="heroi">${brl(a.total)} <small>${a.total ? `anunciados${a.ate ? `, pagos até ${dataBR(a.ate)}` : ""}` : "nenhum provento anunciado para os seus ativos"}</small></div>
    ${a.estimado ? `<div class="sub">+ cerca de ${brl(a.estimado)} dos FIIs que ainda não anunciaram o rendimento do mês (último rendimento × cotas de hoje)</div>` : ""}
    ${a.itens.length ? `<div class="tabela-envolve" style="margin-top:12px"><table class="tabela"><thead><tr><th>Ativo</th><th>Tipo</th><th>Data com</th><th>Pagamento</th><th class="direita">Por cota</th><th class="direita">Quantidade</th><th class="direita">Valor</th><th>Situação</th></tr></thead>
    <tbody>${linhas}</tbody></table></div>` : ""}
    <p class="mudo" style="font-size:12px;margin:10px 0 0">Data com = último dia para ter o ativo e receber o provento. Garantido: a data com já passou e você tinha o ativo nela. Valores brutos; no JCP o banco desconta o IR na fonte. Fonte: B3 (eventos corporativos)${a.atualizadoEm ? `, consultada ${esc(horaRelativa(a.atualizadoEm))}` : ""}.${avisos ? ` ${avisos}` : ""}</p>`);
}

// ============================================================ renda mensal (Status Invest / Kinvo)
function secaoRenda(c, cartao, topoCartao) {
  const r = c.resumo;
  const meses = c.proventos.porMes;
  // Ignora centavos da aplicação automática ao mostrar o "último provento".
  const ultimo = c.proventos.ultimos.find((p) => p.valor >= 1) || c.proventos.ultimos[0];
  const temAReceber = meses.some((m) => m.aReceber);
  return cartao("c8", `${topoCartao("Renda mensal — proventos recebidos", `<span class="mudo" style="font-size:12px">dividendos, JCP e rendimentos que caíram na conta</span>`)}
    <div class="heroi">${brl(r.proventos12m)} <small>em 12 meses · média ${brl(r.proventos12m / 12)}/mês</small></div>
    ${ultimo ? `<div class="sub">Último: ${esc(ultimo.origem)} · ${esc(ultimo.tipo)} · ${brl(ultimo.valor)} em ${dataBR(ultimo.data)}</div>` : ""}
    <div id="g-proventos" style="margin-top:12px"></div>
    ${temAReceber ? `<div class="legenda"><span><i style="background:var(--acento);height:8px"></i>Recebido</span><span><i style="background:var(--acento);opacity:.35;height:8px"></i>A receber (anunciado ou estimado)</span></div>` : ""}
    ${r.rendaFixaMensal ? `<p class="mudo" style="font-size:12px;margin:8px 0 0">Além disso, a renda fixa rende cerca de <b>${brl(r.rendaFixaMensal)}/mês</b> (estimativa bruta pelas taxas dos ${r.rendaFixaPosicoes} títulos e pelo CDI/IPCA recentes). Esse rendimento fica acumulado no título — não cai na conta todo mês.</p>` : ""}
    ${meses.every((m) => !m.total) ? `<p class="mudo">Nenhum provento nos últimos 12 meses.</p>` : ""}`);
}

function graficoProventos(c) {
  const el = document.getElementById("g-proventos");
  if (!el) return;
  // Recebido (cheio) e, no mês atual e nos próximos, o que já foi anunciado ou é estimado (claro).
  desenharColunasEmpilhadas(el, {
    altura: 200,
    itens: c.proventos.porMes.map((m) => ({
      rotulo: nomeMesCurto(m.mes),
      partes: [{ valor: m.total, cor: "var(--acento)" }, { valor: m.aReceber, cor: "var(--acento)", opacidade: 0.35 }],
      dica: `<div class="t">${esc(nomeMes(m.mes))}</div>${m.total || !m.aReceber ? linhaDica(null, "Recebido", brl(m.total)) : ""}${m.itens.slice(0, 6).map((x) => linhaDica(null, x.origem, brl(x.valor))).join("")}${m.aReceber
        ? linhaDica(null, "A receber", brl(m.aReceber)) + m.itensAReceber.slice(0, 6).map((x) => linhaDica(null, `${x.origem}${x.estimado ? " (estimado)" : ""}`, brl(x.valor))).join("") : ""}`,
    })),
  });
}

function secaoProventosPorAtivo(c, cartao, topoCartao) {
  const lista = c.proventos.porOrigem;
  return cartao("c4", `${topoCartao("Proventos por ativo", `<span class="mudo" style="font-size:12px">12 meses</span>`)}
    <ul class="lista">${lista.map((o) => `<li><span class="avatar pequeno">${esc((o.origem || "?").slice(0, 2))}</span>
      <div class="meio"><div class="titulo">${esc(o.origem)} ${o.naCarteira || !o.codigo ? "" : `<span class="etiqueta">vendido</span>`}</div>
      <div class="linha2">${esc(o.tipos.join(" + "))} · ${o.pagamentos} pagamento${o.pagamentos === 1 ? "" : "s"}${o.yieldOnCost !== null && o.yieldOnCost !== undefined ? ` · yield on cost ${semSinal(o.yieldOnCost)}` : ""}</div></div>
      <div class="direita num"><b>${brl(o.total12m)}</b></div></li>`).join("") || `<li class="mudo">Nenhum provento nos últimos 12 meses.</li>`}</ul>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">Yield on cost = proventos de 12 meses ÷ quanto você pagou pelo ativo.</p>`);
}

// ============================================================ vencimentos e indexadores (Gorila)
function secaoVencimentos(c, cartao, topoCartao) {
  const v = c.vencimentos;
  return cartao("c8", `${topoCartao("Escada de vencimentos", `<span class="mudo" style="font-size:12px">quando o dinheiro da renda fixa fica disponível</span>`)}
    <div id="g-vencimentos" style="margin-top:12px"></div>
    <div class="rodape-cartao"><span>Sem vencimento (fundos e bolsa)</span><b class="num" style="color:var(--texto)">${brl(v.semVencimento)}</b></div>`);
}

function graficoVencimentos(c) {
  const el = document.getElementById("g-vencimentos");
  if (!el) return;
  const porAno = new Map(c.vencimentos.porAno.map((a) => [a.ano, a]));
  const anos = c.vencimentos.porAno.map((a) => a.ano);
  desenharColunas(el, {
    altura: 200,
    itens: anos.map((ano) => {
      const a = porAno.get(ano);
      return {
        rotulo: ano, valor: a.total, cor: "var(--s5)",
        dica: `<div class="t">Vencem em ${esc(ano)}</div>${linhaDica(null, "Total", brl(a.total))}${a.itens.slice(0, 8).map((x) => linhaDica(null, `${dataBR(x.vencimento).slice(0, 5)} · ${x.nome.slice(0, 26)}`, brl(x.valor))).join("")}${a.itens.length > 8 ? `<div class="l">+${a.itens.length - 8} títulos</div>` : ""}`,
      };
    }),
    rotularDestaque: false,
  });
}

function secaoIndexadores(c, cartao, topoCartao) {
  const lista = c.indexadores;
  const maior = Math.max(1, ...lista.map((i) => i.valor));
  return cartao("c4", `${topoCartao("Renda fixa por indexador")}
    <ul class="lista">${lista.map((i) => `<li><div class="meio"><div class="titulo">${esc(i.nome)}</div>
      <div class="trilho" style="margin-top:6px"><span style="width:${(i.valor / maior) * 100}%;background:var(--s5)"></span></div></div>
      <div class="direita"><div class="num"><b>${brl(i.valor)}</b></div><div class="linha2 mudo">${semSinal(i.pct)}</div></div></li>`).join("") || `<li class="mudo">Sem renda fixa.</li>`}</ul>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">IPCA+ protege da inflação; pós-fixado acompanha os juros; prefixado trava a taxa.</p>`);
}

// ============================================================ meta de alocação (Status Invest / Kinvo)
function secaoMetas(classes, total, metas, cartao, topoCartao) {
  // Todas as classes, mesmo sem posição: dá para pôr meta numa classe que ainda vai entrar na carteira.
  const linhas = CLASSES_INVESTIMENTO.map((cl) => {
    const atual = classes.find((x) => x.id === cl.id)?.total || 0;
    const meta = metas[cl.id];
    return `<tr data-classe="${cl.id}" data-atual="${atual}">
      <td><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${cl.cor}"></span>${cl.icone} ${esc(cl.nome)}</span></td>
      <td class="direita num">${brl(atual)}</td>
      <td class="direita num">${semSinal(total ? (atual / total) * 100 : 0)}</td>
      <td class="direita"><input type="number" class="campo-meta" min="0" max="100" step="0.5" value="${meta ?? ""}" placeholder="—" aria-label="Meta de ${esc(cl.nome)} em %" style="width:76px;text-align:right;background:var(--superficie);border:1px solid var(--borda-forte);border-radius:8px;padding:6px 8px"> %</td>
      <td class="direita num" data-col="diferenca">—</td>
      <td class="direita num" data-col="ajuste">—</td>
      <td class="direita num" data-col="aporte">—</td></tr>`;
  }).join("");
  return cartao("c12", `${topoCartao("Meta de alocação", `<span class="mudo" style="font-size:12px">defina o % de cada classe e veja onde aportar</span>`)}
    <div class="filtros" style="margin:12px 0 4px">
      <label class="alternar" style="color:var(--texto-2)">Vou aportar R$ <input type="number" id="valor-aporte" min="0" step="100" value="${esc(calculadora.aporte)}" placeholder="0" style="width:140px;background:var(--superficie);border:1px solid var(--borda-forte);border-radius:10px;padding:8px 10px"></label>
      <span class="espaco"></span>
      <span class="mudo" id="soma-metas"></span>
      <button class="botao botao-acento" id="salvar-metas">Salvar metas</button>
    </div>
    <div class="tabela-envolve"><table class="tabela" id="tabela-metas"><thead><tr><th>Classe</th><th class="direita">Atual</th><th class="direita">% atual</th><th class="direita">Meta</th><th class="direita">Diferença</th><th class="direita">Para chegar na meta</th><th class="direita">Onde pôr o aporte</th></tr></thead>
    <tbody>${linhas}</tbody></table></div>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">“Para chegar na meta” = quanto falta (ou sobra) em cada classe hoje. “Onde pôr o aporte” divide o valor que você vai aportar entre as classes que estão abaixo da meta, sem vender nada. É só uma conta sobre as metas que você definir, não uma recomendação de investimento.</p>`);
}

function distribuirAporte(linhas, aporte, totalAtual) {
  const total = totalAtual + aporte;
  const faltas = linhas.map((l) => (l.meta === null ? 0 : Math.max(0, (l.meta / 100) * total - l.atual)));
  const somaFaltas = faltas.reduce((s, v) => s + v, 0);
  const somaMetas = linhas.reduce((s, l) => s + (l.meta || 0), 0);
  if (aporte <= 0) return linhas.map(() => 0);
  if (somaFaltas >= aporte) return faltas.map((f) => (aporte * f) / somaFaltas);
  // Cobre todas as faltas e divide o resto pela proporção das metas.
  return faltas.map((f, i) => f + (somaMetas ? ((aporte - somaFaltas) * (linhas[i].meta || 0)) / somaMetas : 0));
}

function ligarMetas(classes, total, ui) {
  const tabela = document.getElementById("tabela-metas");
  if (!tabela) return;
  const entradaAporte = document.getElementById("valor-aporte");
  const recalcular = () => {
    calculadora.aporte = entradaAporte.value;
    const linhas = [...tabela.querySelectorAll("tbody tr")].map((tr) => {
      const valor = tr.querySelector(".campo-meta").value;
      return { tr, atual: Number(tr.dataset.atual), meta: valor === "" ? null : Number(valor) };
    });
    const soma = linhas.reduce((s, l) => s + (l.meta || 0), 0);
    const somaEl = document.getElementById("soma-metas");
    somaEl.textContent = linhas.some((l) => l.meta !== null) ? `Soma das metas: ${semSinal(soma)}` : "Sem metas definidas";
    somaEl.style.color = Math.abs(soma - 100) < 0.01 || !linhas.some((l) => l.meta !== null) ? "" : "var(--alerta)";
    const aportes = distribuirAporte(linhas, Number(entradaAporte.value) || 0, total);
    linhas.forEach((l, i) => {
      const celula = (col) => l.tr.querySelector(`[data-col="${col}"]`);
      if (l.meta === null) { celula("diferenca").innerHTML = vazio; celula("ajuste").innerHTML = vazio; }
      else {
        const pontos = (l.atual / total) * 100 - l.meta;
        celula("diferenca").innerHTML = `<span class="${Math.abs(pontos) < 1 ? "mudo" : pontos > 0 ? "negativo" : "positivo"}">${pontos > 0 ? "+" : pontos < 0 ? "−" : ""}${Math.abs(pontos).toFixed(1).replace(".", ",")} p.p.</span>`;
        const ajuste = (l.meta / 100) * total - l.atual;
        celula("ajuste").innerHTML = `<span class="${ajuste >= 0 ? "positivo" : "negativo"}">${brlSinal(ajuste)}</span>`;
      }
      celula("aporte").innerHTML = aportes[i] > 0.5 ? `<b>${brl(aportes[i])}</b>` : vazio;
    });
  };
  tabela.querySelectorAll(".campo-meta").forEach((el) => el.addEventListener("input", recalcular));
  entradaAporte.addEventListener("input", recalcular);
  document.getElementById("salvar-metas").addEventListener("click", () => {
    const metas = {};
    tabela.querySelectorAll("tbody tr").forEach((tr) => {
      const valor = tr.querySelector(".campo-meta").value;
      if (valor !== "") metas[tr.dataset.classe] = Number(valor);
    });
    ui.salvarEdicao(() => ui.api("/api/metas-alocacao", { metas }), "Metas de alocação salvas.");
  });
  recalcular();
}

// ============================================================ classes
function cartaoClasse(cl, totalCarteira) {
  const linhaTitulo = (p, extra = "") => `<div style="display:flex;align-items:center;gap:10px">${avatarInstituicao(p.instituicao, true)}<div style="min-width:0"><div>${esc(p.nome)}</div>${extra ? `<div class="mudo" style="font-size:12px">${extra}</div>` : ""}</div></div>`;
  const parteClasse = (p) => semSinal((p.saldo / cl.total) * 100);
  const ganhoComLiquido = (p) => p.ganho === null || p.ganho === undefined ? vazio
    : `${comSinal(p.ganho, p.ganhoPct)}${p.ganhoLiquido !== null && p.ganhoLiquido !== undefined && Math.abs(p.ganhoLiquido - p.ganho) > 0.5 ? `<div class="mudo" style="font-size:11px">líquido ${brlSinal(p.ganhoLiquido)}</div>` : ""}`;
  const atualComLiquido = (p) => `<b>${brl(p.saldo)}</b>${p.liquido !== undefined && Math.abs(p.liquido - p.saldo) > 0.5 ? `<div class="mudo" style="font-size:11px">líquido ${brl(p.liquido)}</div>` : ""}`;
  let cabecalho;
  let linhas;
  if (cl.id === "tesouro" || cl.id === "renda_fixa") {
    cabecalho = `<th>${cl.id === "tesouro" ? "Título" : "Produto"}</th><th>Rentabilidade</th><th>Vencimento</th><th class="direita">Aplicado</th><th class="direita">Atual</th><th class="direita">Ganho</th><th class="direita">% do CDI</th><th class="direita">Renda/mês*</th>`;
    linhas = cl.lista.map((p) => `<tr><td>${linhaTitulo(p, cl.id === "renda_fixa" ? [NOME_ATIVO[p.subtipo], p.emissor && !p.nome.includes(p.emissor) ? p.emissor : ""].filter(Boolean).join(" · ") : precoTesouro(p))}</td>
      <td style="white-space:nowrap">${esc(p.rentabilidade || "—")}</td><td class="num">${dataBR(p.vencimento)}</td>
      <td class="direita num">${p.custo ? brl(p.custo) : vazio}</td><td class="direita num">${atualComLiquido(p)}</td>
      <td class="direita num">${ganhoComLiquido(p)}</td><td class="direita num">${pctDoCdi(p)}</td>
      <td class="direita num">${p.rendaMensalEstimada ? brl(p.rendaMensalEstimada) : vazio}</td></tr>`);
  } else if (cl.id === "fundos") {
    cabecalho = `<th>Fundo</th><th class="direita">Cotas</th><th class="direita">Valor da cota</th><th class="direita">Aplicado</th><th class="direita">Atual</th><th class="direita">Ganho</th><th class="direita">% do CDI</th><th class="direita">% da classe</th>`;
    linhas = cl.lista.map((p) => `<tr><td>${linhaTitulo(p, [NOME_ATIVO[p.subtipo], p.codigo ? `CNPJ ${p.codigo}` : ""].filter(Boolean).join(" · "))}</td>
      <td class="direita num">${qtd(p.quantidade)}</td><td class="direita num">${p.precoUnitario ? brl(p.precoUnitario) : vazio}</td>
      <td class="direita num">${p.custo ? brl(p.custo) : `<span class="mudo" title="Compras anteriores aos 12 meses que o Open Finance informa">sem custo</span>`}</td>
      <td class="direita num">${atualComLiquido(p)}</td><td class="direita num">${ganhoComLiquido(p)}</td>
      <td class="direita num">${pctDoCdi(p)}</td><td class="direita num mudo">${parteClasse(p)}</td></tr>`);
  } else if (["acoes", "etf", "fiis", "acoes_exterior", "reits"].includes(cl.id)) {
    const fii = cl.id === "fiis";
    const nomeBolsa = (p) => `<div style="display:flex;align-items:center;gap:10px">${avatarInstituicao(p.instituicao, true)}<div><b>${esc(p.codigo || p.nome)}</b> <span class="etiqueta">${esc(etiquetaBolsa(p))}</span>${p.emissor ? `<div class="mudo" style="font-size:12px">${esc(p.emissor)}</div>` : ""}${p.desde ? `<div class="mudo" style="font-size:12px">desde ${dataBR(p.desde)}</div>` : ""}</div></div>`;
    const aReceber = (p) => (p.aReceber ? `<div class="positivo" style="font-size:11px">a receber ${brl(p.aReceber)}</div>` : "");
    // FII: último rendimento por cota e quando caiu, dividend yield de 12 meses e a renda que as cotas dão por mês.
    const ultimoRend = (p) => (p.ultimoProvento ? `${porCota(p.ultimoProvento.porCota)}<div class="mudo" style="font-size:11px">${p.ultimoProvento.pagamento ? `pago ${dataBR(p.ultimoProvento.pagamento).slice(0, 5)}` : `data com ${dataBR(p.ultimoProvento.dataCom).slice(0, 5)}`}</div>` : vazio);
    cabecalho = `<th>Ativo</th><th class="direita">${fii ? "Cotas" : "Quantidade"}</th><th class="direita">Preço médio</th><th class="direita">Preço atual</th><th class="direita">Custo</th><th class="direita">Atual</th><th class="direita">Ganho</th>${fii
      ? `<th class="direita">Último rendimento</th><th class="direita">DY 12m</th><th class="direita">Renda/mês*</th>`
      : `<th class="direita">Proventos</th><th class="direita">DY 12m</th><th class="direita">CDI no período</th>`}`;
    linhas = cl.lista.map((p) => `<tr><td>${nomeBolsa(p)}</td>
      <td class="direita num">${qtd(p.quantidade)}</td><td class="direita num">${p.precoMedio ? brl(p.precoMedio) : vazio}</td>
      <td class="direita num">${p.precoUnitario ? brl(p.precoUnitario) : vazio}</td><td class="direita num">${p.custo ? brl(p.custo) : vazio}</td>
      <td class="direita num"><b>${brl(p.saldo)}</b></td><td class="direita num">${comSinal(p.ganho, p.ganhoPct)}</td>
      ${fii ? `<td class="direita num">${ultimoRend(p)}</td>` : `<td class="direita num">${p.proventos ? brl(p.proventos) : vazio}${aReceber(p)}</td>`}
      <td class="direita num">${p.dy12m ? semSinal(p.dy12m) : vazio}</td>
      ${fii ? `<td class="direita num">${p.rendaMensalProventos ? brl(p.rendaMensalProventos) : vazio}${aReceber(p)}</td>`
    : `<td class="direita num">${p.cdiPeriodo !== null && p.cdiPeriodo !== undefined ? `<span class="mudo">${pct(p.cdiPeriodo)}</span>` : vazio}</td>`}</tr>`);
  } else {
    cabecalho = `<th>Nome</th><th>Tipo</th><th class="direita">Atual</th>`;
    linhas = cl.lista.map((p) => `<tr><td>${linhaTitulo(p)}</td><td>${esc(p.subtipo || p.tipo || "")}</td><td class="direita num"><b>${brl(p.saldo)}</b></td></tr>`);
  }
  const comCusto = cl.lista.filter((p) => p.custo);
  const semCusto = cl.lista.filter((p) => !p.custo && !p.conta).length; // saldo em conta não tem custo a informar
  const aplicado = comCusto.reduce((s, p) => s + p.custo, 0);
  const ganho = comCusto.reduce((s, p) => s + p.ganho, 0);
  const proximo = cl.lista.map((p) => p.vencimento).filter(Boolean).sort()[0];
  const aReceber = cl.lista.reduce((s, p) => s + (p.aReceber || 0), 0);
  const rendaMes = cl.id === "fiis" ? cl.lista.reduce((s, p) => s + (p.rendaMensalProventos || 0), 0) : 0;
  const resumo = [
    aplicado ? `aplicado ${brl(aplicado)} · ganho ${comSinal(ganho, (ganho / aplicado) * 100)}` : "",
    proximo ? `próximo vencimento ${dataBR(proximo)}` : "",
    rendaMes ? `renda ~${brl(rendaMes)}/mês` : "",
    aReceber ? `<a class="link" href="#/investimentos/proventos">a receber ${brl(aReceber)}</a>` : "",
    semCusto && cl.id !== "outros" ? `${semCusto} sem custo informado` : "",
  ].filter(Boolean).join(" · ");
  const rodape = cl.id === "tesouro" || cl.id === "renda_fixa"
    ? `<p class="mudo" style="font-size:12px;margin:10px 0 0">Atual e ganho são brutos; embaixo, o líquido depois do IR estimado. % do CDI compara o ganho bruto com o CDI no mesmo período (embaixo: quanto rendeu acima do IPCA). *Renda/mês: estimativa bruta do quanto o título rende por mês nas taxas atuais.</p>`
    : cl.id === "acoes" || cl.id === "etf" ? `<p class="mudo" style="font-size:12px;margin:10px 0 0">Preço médio e custo pelas compras informadas pela corretora. DY 12m = proventos por ação com data com nos últimos 12 meses (B3) ÷ preço atual. “CDI no período”: quanto o CDI rendeu nas mesmas datas, para comparar.</p>`
    : cl.id === "fiis" ? `<p class="mudo" style="font-size:12px;margin:10px 0 0">Preço médio e custo pelas compras informadas pela corretora. Rendimentos pela B3: DY 12m = rendimentos por cota dos últimos 12 meses ÷ preço atual. *Renda/mês: último rendimento × suas cotas (FII que paga todo mês).</p>` : "";
  return `<div class="cartao c12" id="classe-${cl.id}">
    <div class="cartao-topo"><span style="display:inline-flex;align-items:center;gap:8px"><span class="ponto" style="background:${cl.cor}"></span><span class="rotulo">${cl.icone} ${esc(cl.nome)}</span><span class="mudo">· ${cl.lista.length}</span></span>
      <span class="mudo">${semSinal((cl.total / totalCarteira) * 100)} da carteira</span></div>
    <div class="heroi">${brl(cl.total)}</div>
    ${resumo ? `<div class="sub">${resumo}</div>` : ""}
    <div class="tabela-envolve" style="margin-top:12px"><table class="tabela"><thead><tr>${cabecalho}</tr></thead><tbody>${linhas.join("")}</tbody></table></div>
    ${rodape}
  </div>`;
}

// ============================================================ posições encerradas
function secaoEncerradas(lista, cartao, topoCartao) {
  const total = lista.reduce((s, e) => s + e.resultado, 0);
  return cartao("c12", `${topoCartao("Posições encerradas", `<span class="mudo" style="font-size:12px">vendidas nos últimos 12 meses</span>`)}
    <div class="sub">Resultado somado: ${comSinal(total, null)}</div>
    <div class="tabela-envolve" style="margin-top:12px"><table class="tabela"><thead><tr><th>Ativo</th><th>Período</th><th class="direita">Investido</th><th class="direita">Resgatado</th><th class="direita">Proventos</th><th class="direita">Resultado</th></tr></thead>
    <tbody>${lista.map((e) => `<tr><td><b>${esc(e.nome)}</b></td><td class="num">${dataBR(e.inicio)} → ${dataBR(e.fim)}</td>
      <td class="direita num">${brl(e.investido)}</td><td class="direita num">${brl(e.resgatado)}</td><td class="direita num">${e.proventos ? brl(e.proventos) : vazio}</td>
      <td class="direita num">${comSinal(e.resultado, e.resultadoPct)}</td></tr>`).join("")}</tbody></table></div>`);
}

// ============================================================ empréstimos e movimentações do extrato
function secaoEmprestimos(emprestimos, cartao, topoCartao) {
  if (!emprestimos.length) return "";
  return cartao("c12", `${topoCartao("Empréstimos a terceiros", `<a class="link" href="#/transacoes" id="ver-emprestimos">ver transações ↗</a>`)}
    <div class="heroi">${brl(emprestimos.reduce((s, p) => s + p.saldo, 0))} <small>a receber</small></div>
    <ul class="lista">${emprestimos.map((p) => `<li><span class="avatar">${esc(p.nome.slice(0, 1))}</span><div class="meio"><div class="titulo">${esc(p.nome)}</div>
      <div class="linha2">emprestado ${brl(p.emprestado)} · devolvido ${brl(p.devolvido)} · ${p.transacoes} transações · última em ${dataBR(p.ultima)}</div>
      <div class="trilho" style="margin-top:6px"><span style="width:${p.emprestado ? (p.devolvido / p.emprestado) * 100 : 0}%"></span></div></div>
      <div class="direita"><div class="num"><b>${brl(p.saldo)}</b></div><div class="linha2 mudo">a receber</div></div></li>`).join("")}</ul>
    <p class="mudo" style="font-size:12px;margin-bottom:0">Não entra nos gastos. A barra mostra quanto já voltou. Classificado pelas suas regras com a natureza “Empréstimo”.</p>`);
}

function secaoMovimentacoes(b, cartao, topoCartao, tile) {
  const meses = Array.from({ length: 12 }, (_, i) => somarMeses(b.mesAtual, -i)).filter((m) => m >= b.primeiroMes);
  const linhas = meses.map((m) => ({ mes: m, ...b.totais(b.doMes(m)) }));
  const soma = (k) => linhas.reduce((s, l) => s + l[k], 0);
  const maxMov = Math.max(1, ...linhas.map((l) => Math.max(l.aplicado, l.resgatado)));
  return cartao("c12", `${topoCartao("Movimentações de investimento no extrato", `<span class="mudo" style="font-size:12px">conta corrente, últimos ${linhas.length} meses</span>`)}
    <div class="tiles" style="margin:12px 0 6px">
      ${tile("Aplicado", brl(soma("aplicado")))}
      ${tile("Resgatado", brl(soma("resgatado")))}
      ${tile("Aplicado líquido", brlSinal(soma("investidoLiquido")), "aplicado − resgatado", soma("investidoLiquido") >= 0 ? "positivo" : "negativo")}
      ${tile("Rendimentos e dividendos", brl(soma("rendimentos")), "creditados em conta", "positivo")}
    </div>
    <div class="tabela-envolve"><table class="tabela"><thead><tr><th>Mês</th><th class="direita">Aplicado</th><th class="direita">Resgatado</th><th style="width:30%">Movimento</th><th class="direita">Líquido</th><th class="direita">Rendimentos</th></tr></thead>
    <tbody>${linhas.map((l) => `<tr><td>${esc(nomeMesCurto(l.mes))}</td><td class="direita num">${brl(l.aplicado)}</td><td class="direita num">${brl(l.resgatado)}</td>
      <td><div class="trilho" style="margin-bottom:3px"><span style="width:${(l.aplicado / maxMov) * 100}%;background:var(--s1)"></span></div><div class="trilho"><span style="width:${(l.resgatado / maxMov) * 100}%;background:var(--s2)"></span></div></td>
      <td class="direita num ${l.investidoLiquido >= 0 ? "positivo" : "negativo"}">${brlSinal(l.investidoLiquido)}</td><td class="direita num">${brl(l.rendimentos)}</td></tr>`).join("")}</tbody></table></div>
    <div class="legenda"><span><i style="background:var(--s1)"></i>Aplicado</span><span><i style="background:var(--s2)"></i>Resgatado</span></div>
    <p class="mudo" style="font-size:12px;margin-bottom:0">Aplicações automáticas (ex.: Itaú "APLIC AUT MAIS") entram e saem várias vezes por mês; por isso aplicado e resgatado podem ser bem maiores que o valor investido de fato.</p>`);
}
