// Sub-aba Imposto (Investimentos) — estimativa do IR com os dados que o Open Balance tem; não é orientação tributária.
// Apuração mensal da renda variável (custo médio, isenção de R$ 20 mil, prejuízo a compensar, DARF 6015), custo dos ativos
// informado por você e o resumo para a declaração anual (Bens e Direitos, rendimentos isentos e de tributação exclusiva).
// Os cálculos vêm prontos do backend (openbalance/imposto.py); aqui é só apresentação e os formulários.
import { brl, brlSinal, dataBR, esc, nomeMes } from "./util.js";

const formatoQtd = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 });
// Quantidade × preço revelaria o valor: entra no borrão do modo privado.
const qtd = (v) => (v === null || v === undefined ? "—" : `<span class="dinheiro">${formatoQtd.format(v)}</span>`);
const vazio = `<span class="mudo">—</span>`;
const pequeno = (html, classe = "mudo") => `<div class="${classe}" style="font-size:11px">${html}</div>`;
const comSinal = (v) => `<span class="${v >= 0 ? "positivo" : "negativo"}">${brlSinal(v)}</span>`;
const CAMPO = "background:var(--superficie);border:1px solid var(--borda-forte);border-radius:8px;padding:6px 8px";
const NOME_CLASSE = { tesouro: "Tesouro Direto", renda_fixa: "Renda fixa", fundos: "Fundo", cripto: "Criptomoeda", acoes_exterior: "Exterior",
  reits: "REIT", renda_fixa_exterior: "Renda fixa no exterior", outros: "Outros" };
const ORIGEM = { "movimentações": "compras e vendas", informado: "informado por você", banco: "valor aplicado (banco)",
  estimado: "estimado (PU inicial de R$ 1,00)" };
const UNIDADE = { acao: "ações", bdr: "BDRs" };
// CDB, LCI e afins: a "quantidade" é o valor aplicado em unidades de R$ 1,00 — não vale mostrar.
const unidade = (x) => UNIDADE[x.categoria] || (x.classe === "tesouro" ? "títulos" : x.classe === "renda_fixa" ? null : "cotas");
const BOLSA = ["acoes", "etf", "fiis", "acoes_exterior", "reits"];
const FONTES = [
  ["Receita Federal — Perguntas e Respostas IRPF 2026 (renda variável: perguntas 706 a 731)", "https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/dirpf"],
  ["Receita Federal — cálculo e pagamento do imposto em bolsa", "https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/pagamento/renda-variavel/bolsa-de-valores-1/calculo-e-pagamento-do-imposto"],
  ["Lei 15.270/2025 — dividendos acima de R$ 50 mil por mês e tributação mínima", "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15270.htm"],
  ["Lei Complementar 224/2025 — JCP com 17,5% na fonte desde 2026", "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp224.htm"],
  ["Sicalc — emitir o DARF", "https://sicalc.receita.fazenda.gov.br/sicalc/principal"],
  ["ReVar — calculadora de renda variável da Receita (para conferir)", "https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/pagamento/renda-variavel/manual"],
];

// Estado da tela entre renderizações: ano escolhido e ativo com o formulário de custo aberto.
const tela = { ano: null, editando: null };

export function telaImposto(conteudo, estado, ui) {
  const im = estado.dados.imposto;
  const { cartao, topoCartao, tile } = ui;
  if (!im) {
    conteudo.innerHTML = `<div class="alerta-faixa">Feche a janela do Open Balance e abra de novo para ver a aba Imposto (o servidor ainda está rodando a versão anterior).</div>`;
    return;
  }
  if (im.erro) {
    conteudo.innerHTML = `<div class="alerta-faixa">Não consegui calcular o imposto: ${esc(im.erro)}</div>`;
    return;
  }
  if (!im.anos.includes(tela.ano)) tela.ano = im.anoPadrao;
  const ano = tela.ano;
  const a = im.porAno[String(ano)];
  const meses = im.meses.filter((m) => m.mes.startsWith(`${ano}-`));
  conteudo.innerHTML = `<div class="alerta-faixa"><b>Estimativa, não orientação tributária.</b> As contas usam as compras e vendas que a Pluggy informa (cerca de 12 meses), as posições importadas, o custo que você informar e os proventos divulgados pela B3. Confira com as notas de corretagem e os informes de rendimentos antes de pagar um DARF ou entregar a declaração; na dúvida, fale com um contador.</div>
    <div class="filtros"><span class="mudo" style="font-size:12px">Ano</span>
      <div class="segmentos compactos">${im.anos.map((x) => `<button data-ano="${x}" class="${x === ano ? "ativo" : ""}">${x}</button>`).join("")}</div>
      <span class="mudo" style="font-size:12px">${ano < Number(im.hoje.slice(0, 4)) ? `declaração de ${ano + 1} (ano-calendário ${ano})` : `ano em andamento · prévia da declaração de ${ano + 1}`}</span></div>
    <section class="grade">${[
      indicadores(im, a, meses, ano, tile, cartao),
      alertasDividendos(a),
      secaoApuracao(im, a, meses, ano, cartao, topoCartao),
      secaoCustos(im, cartao, topoCartao),
      secaoBens(a, ano, im.hoje, cartao, topoCartao),
      secaoIsentos(a, cartao, topoCartao),
      secaoExclusivos(a, cartao, topoCartao),
      secaoRegras(im, cartao, topoCartao),
    ].join("")}</section>`;
  ligar(conteudo, estado, ui);
}

// ============================================================ indicadores
function indicadores(im, a, meses, ano, tile, cartao) {
  const rv = a.rendaVariavel;
  const darfs = meses.filter((m) => m.darf);
  const proximo = im.proximoDarf?.mes.startsWith(`${ano}-`) || im.proximoDarf?.vencimento?.startsWith(`${ano}-`) ? im.proximoDarf : null;
  const vencidos = darfs.filter((m) => m.situacao === "vencido").length;
  const semCusto = im.ativos.filter((x) => x.precisaCusto).length;
  const prejuizo = (rv.prejuizoComum || 0) + (rv.prejuizoFii || 0);
  const ex = a.exclusivos;
  const rendaFixa = ex.rendaFixaLiquido;
  return cartao("c12", `<div class="tiles">
    ${tile("DARF de renda variável", brl(rv.darfs), darfs.length
      ? `${darfs.length} DARF${darfs.length > 1 ? "s" : ""} no ano (código 6015)${proximo ? ` · próximo vence ${dataBR(proximo.vencimento)}` : vencidos ? " · prazos já passaram" : ""}`
      : `nenhum DARF ${rv.acumulado ? `· ${brl(rv.acumulado)} abaixo de R$ 10 acumulado` : "no ano"}`, rv.darfs ? "negativo" : "")}
    ${tile("Prejuízo a compensar", brl(prejuizo), rv.prejuizoComum === null ? "sem vendas em bolsa registradas"
      : `operações comuns ${brl(rv.prejuizoComum)} · FIIs ${brl(rv.prejuizoFii)}`)}
    ${tile("Ganho isento com ações", brl(rv.ganhoIsento), "meses com até R$ 20 mil em vendas de ações", rv.ganhoIsento ? "positivo" : "")}
    ${tile("Dividendos e FIIs (isentos)", brl(a.isentos.dividendos + a.isentos.fii), `dividendos ${brl(a.isentos.dividendos)} · rendimentos de FII ${brl(a.isentos.fii)}`)}
    ${tile("JCP e renda fixa (IR na fonte)", brl(ex.jcpLiquido + Math.max(0, rendaFixa)), `JCP líquido ${brl(ex.jcpLiquido)} · renda fixa e fundos ~${brl(Math.max(0, rendaFixa))}`)}
    ${semCusto ? tile("Custo a informar", String(semCusto), `ativo${semCusto > 1 ? "s" : ""} sem custo conhecido · <a class="link" href="#/investimentos/imposto" data-rolar="custos-imposto">informar</a>`, "negativo") : ""}
  </div>`);
}

function alertasDividendos(a) {
  if (!a.alertasDividendos.length) return "";
  return `<div class="c12">${a.alertasDividendos.map((x) => `<div class="alerta-faixa" style="margin-bottom:8px">${esc(x.pagador || x.emissor)} pagou ${brl(x.total)} de dividendos em ${esc(nomeMes(x.mes))}: acima de R$ 50 mil no mês, ${x.transicao
    ? "mas os dividendos foram aprovados até 31/12/2025 e ficam fora da retenção (regra de transição da Lei 15.270/2025)."
    : `a empresa retém 10% sobre o total (${brl(x.retencao)}), valor que você compensa na declaração (Lei 15.270/2025).`}</div>`).join("")}</div>`;
}

// ============================================================ apuração mensal
function celulaDarf(m) {
  if (m.darf) {
    return `<b>${brl(m.darf)}</b>${pequeno(`código ${m.codigo} · ${m.situacao === "vencido" ? "venceu" : "vence"} ${dataBR(m.vencimento)}`, m.situacao === "vencido" ? "negativo" : "mudo")}`;
  }
  if (m.acumulado > 0) return `<span class="mudo" title="DARF abaixo de R$ 10 não se paga: soma no mês seguinte">${brl(m.acumulado)} acumula</span>`;
  return m.incompleto ? `<span style="color:var(--alerta)">falta custo</span>` : vazio;
}

function secaoApuracao(im, a, meses, ano, cartao, topoCartao) {
  const rv = a.rendaVariavel;
  const linhas = meses.filter((m) => m.vendas.length || m.darf || m.acumulado);
  const tabela = linhas.length ? `<div class="tabela-envolve" style="margin-top:12px"><table class="tabela"><thead><tr><th>Mês</th><th class="direita">Vendas de ações</th>
    <th class="direita">Resultado ações</th><th class="direita">ETFs e BDRs</th><th class="direita">FIIs</th><th class="direita">Prejuízo usado</th>
    <th class="direita">Imposto</th><th>DARF</th></tr></thead><tbody>${linhas.map((m) => {
    const compensado = m.compensadoComum + m.compensadoFii;
    return `<tr><td style="white-space:nowrap">${esc(nomeMes(m.mes))}${m.emAndamento ? pequeno("mês em andamento") : ""}</td>
      <td class="direita num">${m.vendasAcoes ? `${brl(m.vendasAcoes)}${pequeno(m.isento ? "até R$ 20 mil" : "acima de R$ 20 mil")}` : vazio}</td>
      <td class="direita num">${m.vendasAcoes ? `${comSinal(m.ganhoAcoes)}${m.ganhoIsento ? pequeno("isento") : ""}` : vazio}</td>
      <td class="direita num">${m.ganhoOutros ? comSinal(m.ganhoOutros) : vazio}</td>
      <td class="direita num">${m.ganhoFii ? comSinal(m.ganhoFii) : vazio}</td>
      <td class="direita num">${compensado ? brl(compensado) : vazio}</td>
      <td class="direita num">${m.imposto ? brl(m.imposto) : vazio}${m.irrfUsado ? pequeno(`− IRRF ${brl(m.irrfUsado)}`) : ""}</td>
      <td style="white-space:nowrap">${celulaDarf(m)}</td></tr>`;
  }).join("")}</tbody></table></div>` : `<p class="mudo" style="margin:12px 0 0">Nenhuma venda de ações, ETFs, BDRs ou FIIs em ${ano} nas movimentações — não há DARF de renda variável a pagar.</p>`;
  const vendas = linhas.flatMap((m) => m.vendas);
  const tabelaVendas = vendas.length ? `<details style="margin-top:12px"><summary class="link" style="cursor:pointer">Ver as ${vendas.length} venda${vendas.length > 1 ? "s" : ""} de ${ano}</summary>
    <div class="tabela-envolve" style="margin-top:8px"><table class="tabela"><thead><tr><th>Data</th><th>Ativo</th><th>Tipo</th><th class="direita">Quantidade</th>
    <th class="direita">Valor da venda</th><th class="direita">Custo médio</th><th class="direita">Resultado</th></tr></thead><tbody>${vendas.map((v) => `<tr>
      <td class="num">${dataBR(v.data)}</td><td><b>${esc(v.ativo)}</b></td><td>${esc(im.categorias[v.categoria] || v.categoria)}</td>
      <td class="direita num">${qtd(v.quantidade)}</td><td class="direita num">${brl(v.valor)}</td>
      <td class="direita num">${v.custoValor === null ? `<span style="color:var(--alerta)">desconhecido</span>` : brl(v.custoValor)}</td>
      <td class="direita num">${v.resultado === null ? vazio : comSinal(v.resultado)}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  const avisos = linhas.flatMap((m) => m.avisos.map((x) => `<li>${esc(nomeMes(m.mes))}: ${esc(x)}</li>`)).join("");
  const p = im.prejuizoInicial;
  return cartao("c12", `${topoCartao("Apuração mensal — renda variável", `<span class="mudo" style="font-size:12px">ações, ETFs, BDRs e FIIs vendidos em bolsa</span>`)}
    ${tabela}${tabelaVendas}
    ${avisos ? `<ul style="margin:12px 0 0;padding-left:18px;color:var(--alerta);font-size:13px">${avisos}</ul>` : ""}
    ${rv.prejuizoComum !== null ? `<p style="margin:12px 0 0;font-size:13px">Prejuízo a compensar ${ano < Number(im.hoje.slice(0, 4)) ? `em 31/12/${ano}` : "hoje"}: operações comuns <b>${brl(rv.prejuizoComum)}</b> · FIIs <b>${brl(rv.prejuizoFii)}</b>. Ele só vale se aparecer no Demonstrativo de Renda Variável da declaração, mês a mês, até ser todo usado.</p>` : ""}
    <div class="filtros" style="margin:12px 0 0">
      <span class="mudo" style="font-size:12px">Prejuízo de antes ${p.desde ? `de ${esc(nomeMes(p.desde))}` : "das movimentações"} (da última declaração):</span>
      <label class="alternar" style="color:var(--texto-2)">operações comuns R$ <input type="number" id="prejuizo-comum" min="0" step="0.01" value="${p.comum || ""}" placeholder="0" style="width:120px;${CAMPO}"></label>
      <label class="alternar" style="color:var(--texto-2)">FIIs R$ <input type="number" id="prejuizo-fii" min="0" step="0.01" value="${p.fii || ""}" placeholder="0" style="width:120px;${CAMPO}"></label>
      <button class="botao botao-fantasma" id="salvar-prejuizo">Salvar</button>
    </div>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">Custo médio pelas compras e vendas. Ações: o ganho é isento no mês em que as vendas de ações somam até R$ 20 mil; prejuízo desses meses continua compensável. ETFs e BDRs: 15%, sem isenção. FIIs: 20%, e prejuízo de FII só compensa ganho de FII. Já desconta o IRRF de 0,005% (“dedo-duro”). DARF código 6015, com o último dia do mês da venda como período de apuração, até o último dia útil do mês seguinte; abaixo de R$ 10 não se paga e soma no mês seguinte. Gere no Sicalc da Receita (DARF atrasado tem multa e juros). Corretagem e emolumentos não vêm nas movimentações: com as notas de corretagem em mãos, somá-los ao custo reduz o ganho.</p>`);
}

// ============================================================ custo dos ativos
function nomeAtivo(x) {
  return x.ticker || x.nome || x.codigo;
}

function formularioCusto(x, hoje) {
  const m = x.manual || {};
  const explica = !x.primeiraMovimentacao
    ? "Informe quanto você pagou no total por esta posição (custo de aquisição, com corretagem e taxas), numa data em que já tinha a posição de hoje."
    : x.quantidadeInicial > 0
      ? `As movimentações começam em ${dataBR(x.primeiraMovimentacao)} e não explicam ${qtd(x.quantidadeInicial)} ${unidade(x) || "unidades"} que você já tinha. Informe o custo total numa data: hoje (preço médio da corretora × ${qtd(x.quantidade)}) ou 31/12 do ano passado (o valor da sua última declaração). O restante sai do custo médio.`
      : "As compras e vendas já explicam toda a posição; um custo informado aqui não muda a conta.";
  return `<tr><td colspan="7" style="background:var(--superficie-2)">
    <p style="margin:0 0 8px;font-size:13px">${explica}</p>
    <div class="filtros" style="margin:0">
      <label class="alternar" style="color:var(--texto-2)">Custo total em <input type="date" id="custo-data" value="${esc(m.data || hoje)}" max="${esc(hoje)}" style="${CAMPO}"></label>
      <label class="alternar" style="color:var(--texto-2)">R$ <input type="number" id="custo-valor" min="0" step="0.01" value="${m.custo ?? ""}" placeholder="0,00" style="width:150px;${CAMPO}"></label>
      <button class="botao botao-acento" data-salvar-custo="${esc(x.codigo)}">Salvar</button>
      ${x.manual ? `<button class="botao botao-fantasma" data-apagar-custo="${esc(x.codigo)}">Apagar custo informado</button>` : ""}
      <button class="botao botao-fantasma" data-cancelar>Cancelar</button>
    </div></td></tr>`;
}

function secaoCustos(im, cartao, topoCartao) {
  const bolsa = (x) => BOLSA.includes(x.classe);
  const lista = [...im.ativos].sort((a, z) => (z.precisaCusto - a.precisaCusto) || (bolsa(z) - bolsa(a)) || nomeAtivo(a).localeCompare(nomeAtivo(z)));
  if (!lista.length) return "";
  // Renda fixa e fundos com custo já conhecido ficam recolhidos: raramente há o que informar neles.
  const recolher = (x) => !bolsa(x) && !x.precisaCusto && !x.manual && !x.aviso && tela.editando !== x.codigo;
  const opcoes = (x) => Object.entries(im.categorias).filter(([id]) => id !== "fora")
    .map(([id, nome]) => `<option value="${id}" ${id === x.categoria ? "selected" : ""}>${esc(nome)}</option>`).join("");
  const linha = (x) => {
    const tipo = bolsa(x)
      ? `<select data-categoria="${esc(x.codigo)}" aria-label="Tipo de ${esc(nomeAtivo(x))} para o IR" style="${CAMPO}">${opcoes(x)}</select>${x.categoriaIncerta ? pequeno("confira: o banco não diz se é ETF ou fundo de infraestrutura", "") : ""}`
      : esc(NOME_CLASSE[x.classe] || x.classe);
    const origem = x.origemCusto ? `${esc(ORIGEM[x.origemCusto] || x.origemCusto)}${x.origemCusto === "informado" && x.manual ? pequeno(`${brl(x.manual.custo)} em ${dataBR(x.manual.data)}`) : ""}` : vazio;
    const custo = x.custo !== null ? brl(x.custo) : x.precisaCusto ? `<span style="color:var(--alerta)">falta informar</span>` : vazio;
    // Histórico completo pelas movimentações: não há custo a informar (o formulário só diria isso).
    const completo = x.primeiraMovimentacao && !x.quantidadeInicial && !x.manual;
    return `<tr><td><b>${esc(nomeAtivo(x))}</b>${pequeno(esc([x.ticker ? x.nomeB3 : null, x.instituicao].filter(Boolean).join(" · ")))}${x.aviso ? pequeno(esc(x.aviso), "") : ""}</td>
      <td>${tipo}</td><td class="direita num">${x.semQuantidade || !unidade(x) ? vazio : qtd(x.quantidade)}</td>
      <td class="direita num">${custo}</td><td class="direita num">${x.precoMedio && unidade(x) ? brl(x.precoMedio) : vazio}</td>
      <td>${origem}</td>
      <td class="direita">${completo ? "" : `<button class="botao botao-fantasma" data-editar="${esc(x.codigo)}">${x.manual ? "Editar" : "Informar"}</button>`}</td></tr>
      ${tela.editando === x.codigo ? formularioCusto(x, im.hoje) : ""}`;
  };
  const cabecalho = `<thead><tr><th>Ativo</th><th>Tipo para o IR</th><th class="direita">Quantidade hoje</th>
    <th class="direita">Custo</th><th class="direita">Preço médio</th><th>De onde vem</th><th></th></tr></thead>`;
  const recolhidos = lista.filter(recolher);
  return `<div class="cartao c12" id="custos-imposto">${topoCartao("Custo dos ativos", `<span class="mudo" style="font-size:12px">base do custo médio, das vendas e de Bens e Direitos</span>`)}
    <div class="tabela-envolve" style="margin-top:12px"><table class="tabela">${cabecalho}<tbody>${lista.filter((x) => !recolher(x)).map(linha).join("")}</tbody></table></div>
    ${recolhidos.length ? `<details style="margin-top:10px"><summary class="link" style="cursor:pointer">Renda fixa e fundos com custo conhecido (${recolhidos.length})</summary>
      <div class="tabela-envolve" style="margin-top:8px"><table class="tabela">${cabecalho}<tbody>${recolhidos.map(linha).join("")}</tbody></table></div></details>` : ""}
    <p class="mudo" style="font-size:12px;margin:10px 0 0">A Pluggy traz só ~12 meses de compras e vendas, e posições importadas de planilha vêm sem custo. Para esses ativos, informe o custo total numa data — o preço médio que a corretora mostra hoje × a quantidade, ou o valor de Bens e Direitos da última declaração em 31/12. Renda fixa usa o valor aplicado que o banco informa. O tipo para o IR decide a regra: só ações têm a isenção de R$ 20 mil; ETFs e BDRs pagam 15% sempre; FIIs, 20%; fundos de infraestrutura (Lei 12.431) são isentos para pessoa física.</p>
  </div>`;
}

// ============================================================ Bens e Direitos
function situacao(s, x) {
  if (s.desconhecido) return `<span class="mudo" title="Antes das movimentações que o Open Balance tem: use o valor da declaração anterior">sem dados</span>`;
  if (s.quantidade === 0) return `<span class="mudo">${brl(0)}</span>`;
  const quantidade = s.quantidade === null || !unidade(x) ? "" : pequeno(`${qtd(s.quantidade)} ${unidade(x)}`);
  const semCusto = `<span style="color:var(--alerta)" title="Informe em Custo dos ativos ou use o valor da declaração anterior">custo desconhecido</span>`;
  return `${s.custo === null ? semCusto : brl(s.custo)}${quantidade}`;
}

function secaoBens(a, ano, hoje, cartao, topoCartao) {
  const fechado = `${ano}-12-31` < hoje;
  const linhas = a.bens.map((x, i) => `<tr>
    <td style="min-width:110px;max-width:190px">${x.grupo ? `<span class="etiqueta" title="${esc(x.nomeBem)}">${x.grupo}.${x.codigoBem}</span>${pequeno(esc(x.nomeBem))}` : `<span class="mudo" title="Bens no exterior seguem a Lei 14.754/2023">confira no programa</span>`}</td>
    <td><b>${esc(x.ticker || x.nome)}</b></td>
    <td style="min-width:260px"><span id="disc-${i}">${esc(x.discriminacao)}</span> <button class="botao-linha" data-copiar="disc-${i}" title="Copiar a discriminação" aria-label="Copiar a discriminação" style="font-size:13px">⧉</button></td>
    <td class="direita num">${situacao(x.anterior, x)}</td><td class="direita num">${situacao(x.atual, x)}</td></tr>`).join("");
  return cartao("c12", `${topoCartao(`Bens e Direitos — declaração de ${ano + 1}`, `<span class="mudo" style="font-size:12px">pelo custo de aquisição, nunca pelo valor de mercado</span>`)}
    ${a.bens.length ? `<div class="tabela-envolve" style="margin-top:12px"><table class="tabela"><thead><tr><th>Grupo.código</th><th>Ativo</th><th>Discriminação (sugestão)</th>
      <th class="direita">Em 31/12/${ano - 1}</th><th class="direita">${fechado ? `Em 31/12/${ano}` : "Hoje (prévia de 31/12)"}</th></tr></thead><tbody>${linhas}</tbody></table></div>`
      : `<p class="mudo" style="margin:12px 0 0">Nenhum investimento com posição em ${ano}.</p>`}
    <p class="mudo" style="font-size:12px;margin:10px 0 0">Um item por ativo, com o CNPJ da empresa ou do fundo (está no informe de rendimentos) e o da corretora ou banco. Códigos sugeridos conforme o programa IRPF 2026 — confira no programa do ano, que às vezes os renumera. “Sem dados”: a posição é anterior às movimentações que o Open Balance tem; repita o valor da declaração anterior. Saldo em conta corrente e o saldo aplicado automaticamente pelo banco não entram aqui (vêm no informe do banco).</p>`);
}

// ============================================================ rendimentos
// Nestas listas o detalhe é o que importa: quebra a linha em vez de cortar com reticências.
const QUEBRA = "white-space:normal";

function itemCodigo(codigo, titulo, valor, detalhe, pagadores = "") {
  return `<li><span class="etiqueta" style="min-width:34px;text-align:center">${codigo}</span>
    <div class="meio"><div class="titulo" style="${QUEBRA}">${titulo}</div>${detalhe ? `<div class="linha2" style="${QUEBRA}">${detalhe}</div>` : ""}${pagadores}</div>
    <div class="direita num"><b>${brl(valor)}</b></div></li>`;
}

function listaPagadores(lista, campo) {
  if (!lista.length) return "";
  return `<div class="linha2" style="margin-top:4px;${QUEBRA}">${lista.map((p) => `${esc(p.codigo)}${p.pagador ? ` (${esc(p.pagador)})` : ""} ${brl(p[campo])}${p.suposto ? "*" : ""}`).join(" · ")}</div>`;
}

function secaoIsentos(a, cartao, topoCartao) {
  const i = a.isentos;
  const pag = (tipo) => a.pagadores.filter((p) => p.tipo === tipo);
  const suposto = a.pagadores.some((p) => p.suposto);
  const itens = [
    itemCodigo("09", "Lucros e dividendos recebidos", i.dividendos, "", listaPagadores(pag("dividendos"), "bruto")),
    itemCodigo("99", "Outros — rendimentos de FII e Fiagro", i.fii, "", listaPagadores(pag("fii"), "bruto")),
    itemCodigo("20", "Ganhos com ações em meses de vendas até R$ 20 mil", i.ganhoAcoes, "da apuração mensal"),
    i.rendaFixa ? itemCodigo("12", "LCI, LCA, CRI e CRA", i.rendaFixa, "rendimento dos resgates (estimado: confira no informe do banco)") : "",
    i.outros ? itemCodigo("?", "Outros proventos de ativos de bolsa", i.outros, "tipo não identificado (ex.: rendimento de ETF ou de fundo de infraestrutura) — confira no informe", listaPagadores(pag("outros"), "bruto")) : "",
  ].join("");
  return cartao("c6", `${topoCartao("Rendimentos isentos e não tributáveis")}
    <ul class="lista">${itens}</ul>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">Proventos pela data de pagamento: anunciados na B3 × a quantidade que você tinha na data com, conferidos com o que caiu na conta.${suposto ? " *Posição importada sem as compras e vendas: supõe a quantidade de hoje na data com." : ""} Na declaração vale o informe de rendimentos de cada fonte pagadora.</p>`);
}

function secaoExclusivos(a, cartao, topoCartao) {
  const e = a.exclusivos;
  const jcp = a.pagadores.filter((p) => p.tipo === "jcp");
  const resgates = a.rendaFixa.filter((x) => !x.isento);
  const detalhes = resgates.length ? `<details style="margin-top:8px"><summary class="link" style="cursor:pointer;font-size:12px">Ver ${resgates.length} lançamento${resgates.length > 1 ? "s" : ""}</summary>
    <div class="tabela-envolve"><table class="tabela" style="font-size:12px"><thead><tr><th>Data</th><th>Aplicação</th><th class="direita">Bruto</th><th class="direita">IR retido</th><th class="direita">Rendimento</th></tr></thead>
    <tbody>${resgates.map((x) => `<tr><td class="num">${dataBR(x.data)}</td><td>${esc(x.ativo)}${pequeno(x.tipo)}</td><td class="direita num">${x.bruto ? brl(x.bruto) : vazio}</td>
      <td class="direita num">${brl(x.ir)}</td><td class="direita num">${x.rendimento === null ? vazio : `${x.estimado ? "~" : ""}${brl(x.rendimento)}`}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  const itens = [
    itemCodigo("10", "Juros sobre capital próprio", e.jcpLiquido, e.jcpBruto ? `líquido · bruto ${brl(e.jcpBruto)} − IR ${brl(e.jcpIr)} (15% até 2025, 17,5% desde 2026)` : "", listaPagadores(jcp, "liquido")),
    itemCodigo("06", "Rendimentos de aplicações financeiras", e.rendaFixaLiquido,
      `líquido estimado · rendimento ~${brl(e.rendaFixaRendimento)} · IR retido no ano ${brl(e.rendaFixaIr)}${e.rendaFixaSemRendimento ? ` · ${e.rendaFixaSemRendimento} resgate${e.rendaFixaSemRendimento > 1 ? "s" : ""} de fundo sem o rendimento calculado (veja o informe)` : ""}`, detalhes),
    e.creditadoConta ? itemCodigo("06", "Rendimentos creditados em conta", e.creditadoConta, "aplicação automática e afins, pelo extrato (líquido)") : "",
  ].join("");
  return cartao("c6", `${topoCartao("Rendimentos sujeitos à tributação exclusiva")}
    <ul class="lista">${itens}</ul>
    <p class="mudo" style="font-size:12px;margin:10px 0 0">O IR destes já foi retido na fonte; na declaração eles só são informados (pelo valor líquido do informe de rendimentos). Fundos de renda fixa e multimercado têm come-cotas em maio e novembro, que aparece aqui como IR retido. Os valores de renda fixa são estimativas: o informe do banco é a referência.</p>`);
}

// ============================================================ regras e fontes
function secaoRegras(im, cartao, topoCartao) {
  const p = im.parametros;
  return cartao("c12", `${topoCartao("Regras usadas e fontes", `<span class="mudo" style="font-size:12px">vigentes em ${esc(im.hoje.slice(0, 4))}</span>`)}
    <ul style="margin:10px 0 0;padding-left:18px;font-size:13px;line-height:1.6">
      <li>Operações comuns (ações, ETFs de ações, BDRs): 15% sobre o ganho líquido do mês; day trade: 20% (aqui só sinalizado).</li>
      <li>Ações à vista: ganho isento no mês em que o total vendido em ações não passa de ${brl(p.limiteIsencao)}. ETFs, BDRs e FIIs não têm essa isenção.</li>
      <li>FIIs e Fiagros: 20% sobre o ganho na venda; os rendimentos mensais seguem isentos para pessoa física (fundo com cotas em bolsa e ao menos 100 cotistas, e você com menos de 10% das cotas).</li>
      <li>Prejuízo compensa ganho do mesmo grupo nos meses seguintes, sem prazo: operações comuns com operações comuns, FIIs com FIIs. Ganho de um mês não é compensado com prejuízo de meses anteriores ao ganho.</li>
      <li>Juros sobre capital próprio: 15% na fonte até 2025 e 17,5% desde 1º/1/2026 (LC 224/2025).</li>
      <li>Dividendos: isentos, mas desde 2026 a mesma empresa que paga mais de ${brl(p.limiteDividendos)} a você num mês retém 10% sobre o total (Lei 15.270/2025), compensável na declaração; lucros aprovados até 31/12/2025 ficam de fora. Quem tem renda total acima de R$ 600 mil no ano paga a tributação mínima (até 10%) na declaração — o Open Balance não calcula, porque depende da sua renda toda.</li>
      <li>Aplicações no exterior (fora da B3) seguem a Lei 14.754/2023: 15% apurados na declaração anual, fora desta conta.</li>
    </ul>
    <ul style="margin:10px 0 0;padding-left:18px;font-size:13px;line-height:1.6">${FONTES.map(([nome, url]) => `<li><a class="link" href="${url}" target="_blank" rel="noopener noreferrer">${esc(nome)} ↗</a></li>`).join("")}</ul>`);
}

// ============================================================ eventos
function ligar(conteudo, estado, ui) {
  const redesenhar = () => telaImposto(conteudo, estado, ui);
  conteudo.querySelectorAll("[data-ano]").forEach((b) => b.addEventListener("click", () => { tela.ano = Number(b.dataset.ano); redesenhar(); }));
  conteudo.querySelectorAll("[data-rolar]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById(a.dataset.rolar)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }));
  conteudo.querySelectorAll("[data-categoria]").forEach((s) => s.addEventListener("change", () =>
    ui.salvarEdicao(() => ui.api("/api/imposto/custo", { codigo: s.dataset.categoria, categoria: s.value }), "Tipo do ativo para o IR salvo.")));
  conteudo.querySelectorAll("[data-editar]").forEach((b) => b.addEventListener("click", () => {
    tela.editando = tela.editando === b.dataset.editar ? null : b.dataset.editar;
    redesenhar();
    document.getElementById("custo-valor")?.focus();
  }));
  conteudo.querySelector("[data-cancelar]")?.addEventListener("click", () => { tela.editando = null; redesenhar(); });
  conteudo.querySelector("[data-salvar-custo]")?.addEventListener("click", (e) => {
    const valor = document.getElementById("custo-valor").value;
    if (valor === "") return ui.avisar("Informe o custo total em reais.", true);
    tela.editando = null;
    ui.salvarEdicao(() => ui.api("/api/imposto/custo", { codigo: e.currentTarget.dataset.salvarCusto, custo: Number(valor),
      data: document.getElementById("custo-data").value }), "Custo salvo.");
  });
  conteudo.querySelector("[data-apagar-custo]")?.addEventListener("click", (e) => {
    tela.editando = null;
    ui.salvarEdicao(() => ui.api("/api/imposto/custo", { codigo: e.currentTarget.dataset.apagarCusto, custo: null }), "Custo informado apagado.");
  });
  conteudo.querySelector("#salvar-prejuizo")?.addEventListener("click", () =>
    ui.salvarEdicao(() => ui.api("/api/imposto/prejuizo", { comum: document.getElementById("prejuizo-comum").value,
      fii: document.getElementById("prejuizo-fii").value }), "Prejuízo anterior salvo."));
  conteudo.querySelectorAll("[data-copiar]").forEach((b) => b.addEventListener("click", () => {
    const texto = document.getElementById(b.dataset.copiar)?.textContent || "";
    navigator.clipboard?.writeText(texto).then(() => ui.avisar("Discriminação copiada."), () => ui.avisar("Não consegui copiar.", true));
  }));
}
