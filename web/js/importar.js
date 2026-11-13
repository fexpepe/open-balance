// Aba Importar: arquivos exportados do banco (OFX, CSV, XLSX) entram no Open Balance sem precisar da Pluggy.
// Fluxo: escolher arquivos → prévia (conta, fatura, duplicados) → Importar. Tudo pode ser desfeito no histórico.
import { avatarInstituicao, brl, dataBR, esc, horaRelativa } from "./util.js";

const TIPOS = { conta: "Extrato de conta", cartao: "Fatura de cartão", investimentos: "Posição de investimentos" };
const ICONE_TIPO = { conta: "🏦", cartao: "💳", investimentos: "📈" };
const PAPEIS = [["", "—"], ["data", "Data"], ["descricao", "Descrição"], ["valor", "Valor"], ["credito", "Crédito (entrada)"],
  ["debito", "Débito (saída)"], ["sinal", "Tipo D/C"], ["parcela", "Parcela"], ["id", "Identificador"], ["saldo", "Saldo"]];
const NOME_TIPO_INVEST = { FIXED_INCOME: "Renda fixa", EQUITY: "Ações", ETF: "ETF", MUTUAL_FUND: "Fundos", SECURITY: "Previdência", OTHER: "Outros" };
const INSTITUICOES = ["Nubank", "Itaú", "Bradesco", "Santander", "Banco do Brasil", "Caixa", "Inter", "C6 Bank", "BTG Pactual", "XP",
  "Rico", "Clear", "Mercado Pago", "PicPay", "PagBank", "Neon", "Sicoob", "Sicredi", "Safra", "Banco Original", "Banrisul", "Will Bank"];
// Mudanças que alteram a prévia (duplicados, total da fatura…) e pedem uma nova análise no servidor.
const REANALISAR = new Set(["tipo", "contaId", "vencimento", "fechada", "modoFatura", "diaFechamento", "diaVencimento"]);
const CHAVES_FATURA = ["vencimento", "fechada", "modoFatura", "diaFechamento", "diaVencimento", "totalFatura"];
const MAX_BYTES = 20 * 1024 * 1024;

// Arquivos escolhidos e ainda não importados. Ficam fora da tela para sobreviver aos redesenhos.
const pendentes = [];
let sequencia = 0;
let ctx = null; // { dados, api, recarregar, avisar, conteudo }

export function telaImportar(contexto) {
  ctx = contexto;
  desenhar();
}

const naTela = () => location.hash.replace(/^#\/?/, "").startsWith("importar");

// ============================================================ estado das prévias
function partesVisiveis() {
  const lista = [];
  for (const arq of pendentes) {
    if (arq.carregando || arq.erro) lista.push({ arq, parte: null, i: 0 });
    else arq.partes.forEach((parte, i) => { if (!parte.feita) lista.push({ arq, parte, i }); });
  }
  return lista;
}

function achar(chave) {
  const [id, i] = chave.split(":").map(Number);
  const arq = pendentes.find((a) => a.id === id);
  return arq ? { arq, parte: arq.partes[i], i } : {};
}

function valor(parte, chave) {
  const o = parte.opcoes;
  const p = parte.previa;
  if (chave in o) return o[chave];
  switch (chave) {
    case "tipo": return p.tipo;
    case "contaId": return p.contaId || "";
    case "modoFatura": return p.fatura?.modo;
    case "vencimento": case "fechada": case "diaFechamento": case "diaVencimento": return p.fatura?.[chave];
    case "totalFatura": return p.fatura ? p.fatura.total.toFixed(2).replace(".", ",") : "";
    case "dataPosicao": return p.dataPosicao;
    case "instituicao": return p.instituicaoPadrao || "";
    default: return "";
  }
}

const valorNova = (parte, campo) => parte.opcoes.novaConta?.[campo] ?? parte.previa.novaConta?.[campo] ?? "";

function definir(parte, caminho, v) {
  if (caminho.startsWith("novaConta.")) {
    parte.opcoes.novaConta = { ...(parte.opcoes.novaConta || {}), [caminho.slice(10)]: v };
    return;
  }
  if (caminho === "tipo") parte.opcoes = {}; // outro tipo: conta sugerida e fatura recomeçam do zero
  if (caminho === "contaId") for (const k of CHAVES_FATURA) delete parte.opcoes[k]; // vale o que se sabe da outra conta
  parte.opcoes[caminho] = v;
}

function opcoesFinais(arq, parte, i) {
  const tipo = valor(parte, "tipo");
  const o = { parte: i, tipo, mapeamento: arq.mapeamento || parte.previa.mapeamento || undefined };
  if (tipo === "investimentos") return { ...o, dataPosicao: valor(parte, "dataPosicao"), instituicao: valor(parte, "instituicao") };
  o.contaId = valor(parte, "contaId");
  if (!o.contaId) o.novaConta = { instituicao: valorNova(parte, "instituicao"), nome: valorNova(parte, "nome"), final: valorNova(parte, "final") };
  if (tipo === "cartao") {
    for (const k of ["vencimento", "fechada", "modoFatura", "diaFechamento", "diaVencimento"]) o[k] = valor(parte, k);
    if (o.fechada && o.modoFatura === "unica") o.totalFatura = valor(parte, "totalFatura");
  } else if (valor(parte, "saldo")) {
    o.saldo = valor(parte, "saldo");
  }
  return o;
}

// ============================================================ servidor
function lerBase64(arquivo) {
  return new Promise((ok, falha) => {
    const leitor = new FileReader();
    leitor.onload = () => ok(String(leitor.result).split(",")[1] || "");
    leitor.onerror = () => falha(new Error("não consegui ler o arquivo"));
    leitor.readAsDataURL(arquivo);
  });
}

async function analisar(arq, opcoes = {}) {
  const r = await ctx.api("/api/importar/analisar", { nome: arq.nome, conteudo: arq.conteudo, opcoes: { ...opcoes, mapeamento: arq.mapeamento || undefined } });
  return r.partes;
}

async function adicionar(arquivos) {
  const novos = [];
  for (const f of arquivos) {
    if (f.size > MAX_BYTES) { ctx.avisar(`${f.name}: arquivo grande demais (máximo 20 MB).`, true); continue; }
    const arq = { id: ++sequencia, nome: f.name, conteudo: null, carregando: true, erro: null, partes: [], mapeamento: null };
    pendentes.push(arq);
    novos.push([arq, f]);
  }
  desenhar();
  await Promise.all(novos.map(async ([arq, f]) => {
    try {
      arq.conteudo = await lerBase64(f);
      arq.partes = (await analisar(arq)).map((previa) => ({ previa, opcoes: {} }));
    } catch (e) {
      arq.erro = e.message;
    }
    arq.carregando = false;
    desenhar();
  }));
}

async function reanalisar(arq, i) {
  const parte = arq.partes[i];
  parte.ocupado = true;
  desenhar();
  try {
    const partes = await analisar(arq, { ...parte.opcoes, parte: i });
    parte.previa = partes[i] || parte.previa;
    parte.erro = null;
  } catch (e) {
    parte.erro = e.message;
  }
  parte.ocupado = false;
  desenhar();
}

function mensagem(r) {
  if (r.posicoes !== undefined) return `${r.posicoes} posições de investimento importadas (${r.instituicoes.join(", ")}), total ${brl(r.total)}.`;
  const partes = [`${r.instituicao}: ${r.novas} lançamento(s) novo(s)`];
  if (r.duplicadas + r.atualizadas) partes.push(`${r.duplicadas + r.atualizadas} já existiam`);
  if (r.faturas) partes.push(`${r.faturas} fatura(s) fechada(s)`);
  if (r.projetadas) partes.push(`${r.projetadas} parcela(s) futura(s) prevista(s)`);
  return `${partes.join(", ")}.`;
}

async function importarParte(arq, i, { recarregar = true } = {}) {
  const parte = arq.partes[i];
  const o = opcoesFinais(arq, parte, i);
  if (o.tipo !== "investimentos" && !o.contaId && !o.novaConta.instituicao.trim()) {
    parte.erro = "Informe a instituição da conta nova.";
    desenhar();
    return false;
  }
  parte.ocupado = true;
  parte.erro = null;
  desenhar();
  try {
    const r = await ctx.api("/api/importar/confirmar", { nome: arq.nome, conteudo: arq.conteudo, opcoes: o });
    parte.feita = true;
    if (arq.partes.every((p) => p.feita)) pendentes.splice(pendentes.indexOf(arq), 1);
    ctx.avisar(mensagem(r));
    if (recarregar) await depoisDeImportar();
    return true;
  } catch (e) {
    parte.erro = e.message;
    parte.ocupado = false;
    desenhar();
    return false;
  }
}

async function depoisDeImportar() {
  await ctx.recarregar();
  // Outras prévias podem ter ficado velhas (conta recém-criada, lançamentos que agora já existem).
  for (const arq of pendentes) {
    arq.partes.forEach((parte, i) => { if (!parte.feita && !parte.previa.precisaMapeamento && !("contaId" in parte.opcoes)) reanalisar(arq, i); });
  }
}

async function importarTodos() {
  let feitas = 0;
  for (const { arq, i } of partesVisiveis().filter(({ parte }) => parte && !parte.previa.precisaMapeamento)) {
    if (await importarParte(arq, i, { recarregar: false })) feitas += 1;
  }
  if (feitas) {
    await depoisDeImportar();
    ctx.avisar(`${feitas} arquivo(s) importado(s).`);
  }
}

// ============================================================ desenho
function desenhar() {
  if (!ctx || !naTela()) return;
  const d = ctx.dados;
  const visiveis = partesVisiveis();
  const prontas = visiveis.filter(({ parte }) => parte && !parte.previa.precisaMapeamento && !parte.ocupado);
  ctx.conteudo.innerHTML = `<div class="importar">
    ${cartaoEnvio(d)}
    ${visiveis.length ? `<div class="secao-titulo"><h2>Arquivos para importar</h2><span class="mudo">${visiveis.length}</span><span class="espaco"></span>
      ${prontas.length > 1 ? `<button class="botao botao-acento" id="importar-todos">Importar todos (${prontas.length})</button>` : ""}</div>` : ""}
    ${visiveis.map(cartaoPrevia).join("")}
    ${cartaoConectar(d)}
    ${cartaoContas(d)}
    ${cartaoHistorico(d)}
    ${cartaoTitular(d)}
    <datalist id="lista-instituicoes">${INSTITUICOES.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
  </div>`;
  ligar();
}

function cartaoEnvio(d) {
  return `<div class="cartao">
    <div class="cartao-topo"><span class="rotulo">Importar arquivos do banco</span>${d.pluggy ? `<span class="mudo" style="font-size:12px">funciona junto com a Pluggy</span>` : ""}</div>
    <div class="sub">Exporte o extrato da conta, a fatura do cartão ou a posição de investimentos no app ou site do banco e envie aqui.
      Pode mandar todo mês — inclusive períodos repetidos: o que já está no Open Balance não é duplicado.</div>
    <label class="zona-soltar" id="zona-soltar">
      <input type="file" id="campo-arquivos" multiple accept=".ofx,.qfx,.csv,.txt,.xlsx,.xls,.htm,.html">
      <span class="zona-icone" aria-hidden="true">⇪</span>
      <b>Arraste os arquivos aqui ou clique para escolher</b>
      <span class="mudo">OFX, CSV, TXT ou Excel (.xlsx) · vários de uma vez</span>
    </label>
    <details class="dicas"><summary>Como exportar do meu banco</summary><ul>
      <li>Prefira <b>OFX</b> (às vezes chamado de “Money” ou “Quicken”): traz o saldo e um identificador de cada lançamento. CSV, TXT e Excel também funcionam — se as colunas não forem reconhecidas, você indica uma vez e o Open Balance lembra.</li>
      <li><b>Conta</b>: no extrato, procure “Exportar”, “Baixar” ou “Salvar como”. Pode escolher um período maior que o mês; o que se repetir é ignorado.</li>
      <li><b>Cartão</b>: exporte cada fatura (a fechada e, se quiser, a atual). Você confirma o vencimento e o Open Balance monta a fatura, as parcelas que ainda vão cair e o limite.</li>
      <li><b>Investimentos</b>: na Área do Investidor da B3, Extratos → Posição → baixar em Excel; ou preencha o <a class="link" href="modelos/investimentos.csv" download>modelo de planilha</a> com os saldos do mês.</li>
      <li>PDF não é aceito: não dá para ler com segurança.</li>
    </ul></details>
  </div>`;
}

function cabecalhoPrevia(arq, parte, i, chave) {
  return `<div class="previa-topo">
    <span class="previa-arquivo" title="${esc(arq.nome)}">${parte ? ICONE_TIPO[valor(parte, "tipo")] || "📄" : "📄"} ${esc(arq.nome)}</span>
    ${parte ? `<span class="marcador">${esc(parte.previa.formato)}</span>` : ""}
    ${arq.partes.length > 1 ? `<span class="marcador">parte ${i + 1} de ${arq.partes.length}</span>` : ""}
    <span class="espaco"></span>
    <button class="botao-linha" data-descartar="${chave}" title="Descartar este arquivo" aria-label="Descartar">✕</button>
  </div>`;
}

function cartaoPrevia({ arq, parte, i }) {
  const chave = `${arq.id}:${i}`;
  const topo = cabecalhoPrevia(arq, parte, i, chave);
  if (arq.carregando) return `<div class="cartao previa">${topo}<div class="mudo"><span class="sinc-giro girando"></span> Lendo o arquivo…</div></div>`;
  if (arq.erro) return `<div class="cartao previa">${topo}<div class="alerta-faixa erro">${esc(arq.erro)}</div></div>`;
  const p = parte.previa;
  const erro = parte.erro ? `<div class="alerta-faixa erro">${esc(parte.erro)}</div>` : "";
  if (p.precisaMapeamento) return `<div class="cartao previa">${topo}${erro}${formularioMapa(p, chave)}</div>`;
  const tipo = valor(parte, "tipo");
  const corpo = tipo === "investimentos" ? formularioPosicoes(parte, p) : formularioLancamentos(parte, p, tipo);
  const avisos = (p.avisos || []).map((a) => `<div class="alerta-faixa">${esc(a)}</div>`).join("");
  return `<div class="cartao previa${parte.ocupado ? " ocupada" : ""}" data-chave="${chave}">${topo}
    <div class="grade-form">
      <label class="campo">Tipo de arquivo
        <select data-op="tipo">${Object.entries(TIPOS).map(([v, r]) => `<option value="${v}" ${tipo === v ? "selected" : ""}>${r}</option>`).join("")}</select>
      </label>
      ${corpo}
    ${avisos}${erro}
    <div class="previa-acoes">
      ${parte.ocupado ? `<span class="mudo"><span class="sinc-giro girando"></span> Processando…</span>` : ""}
      <span class="espaco"></span>
      <button class="botao botao-fantasma" data-descartar="${chave}">Descartar</button>
      <button class="botao botao-acento" data-importar="${chave}" ${parte.ocupado ? "disabled" : ""}>Importar</button>
    </div>
  </div>`;
}

function campoTexto(rotulo, op, v, extra = "", ajuda = "") {
  return `<label class="campo">${rotulo}<input type="text" data-op="${op}" value="${esc(v ?? "")}" ${extra}>${ajuda ? `<small>${ajuda}</small>` : ""}</label>`;
}

function formularioLancamentos(parte, p, tipo) {
  const cartao = tipo === "cartao";
  const contaId = valor(parte, "contaId");
  const conta = p.contas.find((c) => c.id === contaId);
  const pluggy = conta && conta.origem !== "importacao";
  let campos = `<label class="campo">${cartao ? "Cartão" : "Conta"} de destino
      <select data-op="contaId">${p.contas.map((c) => `<option value="${esc(c.id)}" ${c.id === contaId ? "selected" : ""}>${esc(c.rotulo)}</option>`).join("")}
        <option value="" ${contaId ? "" : "selected"}>＋ ${cartao ? "Novo cartão" : "Nova conta"}…</option></select>
    </label>`;
  if (!contaId) {
    campos += campoTexto("Instituição", "novaConta.instituicao", valorNova(parte, "instituicao"), `list="lista-instituicoes" placeholder="ex.: Nubank" maxlength="40"`)
      + campoTexto("Apelido (opcional)", "novaConta.nome", valorNova(parte, "nome"), `placeholder="${cartao ? "ex.: Platinum" : "ex.: Conta conjunta"}" maxlength="40"`)
      + campoTexto("Final (4 dígitos)", "novaConta.final", valorNova(parte, "final"), `inputmode="numeric" maxlength="4" placeholder="opcional"`);
  }
  if (cartao) {
    const f = p.fatura;
    if (valor(parte, "modoFatura") === "varios") {
      campos += `<label class="campo">Dia de fechamento<input type="number" min="1" max="31" data-op="diaFechamento" value="${esc(valor(parte, "diaFechamento"))}"></label>
        <label class="campo">Dia de vencimento<input type="number" min="1" max="31" data-op="diaVencimento" value="${esc(valor(parte, "diaVencimento"))}">
        <small>O arquivo cobre vários meses: cada compra vai para a fatura do seu período. <a class="link" href="#" data-modo="unica">É uma fatura só?</a></small></label>`;
    } else {
      const fechada = valor(parte, "fechada");
      campos += `<label class="campo">Vencimento desta fatura<input type="date" data-op="vencimento" value="${esc(valor(parte, "vencimento"))}">
          <small><a class="link" href="#" data-modo="varios">Arquivo com vários meses?</a></small></label>
        <label class="campo">Situação<select data-op="fechada"><option value="1" ${fechada ? "selected" : ""}>Fechada</option><option value="0" ${fechada ? "" : "selected"}>Aberta (ainda recebendo compras)</option></select></label>`;
      if (fechada) campos += campoTexto("Total da fatura", "totalFatura", valor(parte, "totalFatura"), `inputmode="decimal"`, `somando o arquivo: ${brl(f.total)}`);
    }
  } else if (!pluggy) {
    const doArquivo = p.saldo !== null && p.saldo !== undefined;
    campos += campoTexto("Saldo atual (opcional)", "saldo", valor(parte, "saldo"), `inputmode="decimal" placeholder="${doArquivo ? "usar o do arquivo" : "não veio no arquivo"}"`,
      doArquivo ? `no arquivo: ${brl(p.saldo)} em ${dataBR(p.saldoData)}` : "sem saldo, a conta aparece com “—” até você informar");
  }
  campos += `</div>`; // fecha .grade-form

  const existentes = p.duplicadas + p.atualizadas;
  const resumo = [`<b>${p.novas} novo(s)</b>`];
  if (existentes) resumo.push(`${existentes} já estava(m) no Open Balance`);
  if (p.periodo) resumo.push(`${dataBR(p.periodo[0])} a ${dataBR(p.periodo[1])}`);
  if (cartao && p.parcelas) resumo.push(`${p.parcelas} parcela(s)`);
  if (cartao && p.pagamentos) resumo.push(`${p.pagamentos} pagamento(s) de fatura`);
  if (!cartao) resumo.push(`entradas ${brl(p.entradas)} · saídas ${brl(p.saidas)}`);
  if (cartao && p.fatura?.faturasFechadas?.length && valor(parte, "modoFatura") === "varios") resumo.push(`${p.fatura.faturasFechadas.length} fatura(s) fechada(s) completa(s)`);
  const linhas = p.amostra.map((a) => `<tr class="${a.nova ? "" : "esmaecida"}">
      <td class="num">${dataBR(a.data)}</td>
      <td><div class="corte">${esc(a.descricao)}${a.parcela ? `<span class="marcador">${a.parcela[0]}/${a.parcela[1]}</span>` : ""}${a.nova ? "" : `<span class="marcador">já existe</span>`}</div></td>
      <td><span class="etiqueta">${esc(a.categoria)}</span></td>
      <td class="direita num ${a.valor > 0 ? "positivo" : ""}">${a.valor > 0 ? "+" : "−"}${brl(Math.abs(a.valor))}</td></tr>`).join("");
  return `${campos}
    <div class="previa-resumo">${resumo.join(" · ")}</div>
    ${linhas ? `<div class="tabela-envolve"><table class="tabela tabela-mini"><tbody>${linhas}</tbody></table></div>
    <div class="mudo previa-nota">Mais recentes do arquivo. A categoria é sugerida pelo seu histórico e por palavras-chave; dá para ajustar depois na aba Transações.</div>` : ""}`;
}

function formularioPosicoes(parte, p) {
  let campos = `<label class="campo">Data da posição<input type="date" data-op="dataPosicao" value="${esc(valor(parte, "dataPosicao"))}"></label>`;
  if (p.semInstituicao) {
    campos += campoTexto("Instituição", "instituicao", valor(parte, "instituicao"), `list="lista-instituicoes" placeholder="ex.: XP" maxlength="40"`,
      `${p.semInstituicao} posição(ões) vieram sem instituição`);
  }
  campos += `</div>`;
  const linhas = p.posicoes.slice(0, 12).map((x) => `<tr><td><div class="corte">${esc(x.nome)}</div></td>
      <td><span class="etiqueta">${esc(NOME_TIPO_INVEST[x.tipo] || x.tipo)}</span></td>
      <td class="mudo">${esc(x.instituicao || valor(parte, "instituicao") || "—")}</td>
      <td class="direita num">${brl(x.saldo)}</td></tr>`).join("");
  return `${campos}
    <div class="previa-resumo"><b>${p.quantidade} posição(ões)</b> · total ${brl(p.total)}${p.instituicoesArquivo.length ? ` · ${esc(p.instituicoesArquivo.join(", "))}` : ""}</div>
    <div class="tabela-envolve"><table class="tabela tabela-mini"><tbody>${linhas}</tbody></table></div>
    ${p.quantidade > 12 ? `<div class="mudo previa-nota">+${p.quantidade - 12} posições</div>` : ""}
    <div class="mudo previa-nota">Substitui a posição importada antes desta mesma instituição (do mesmo tipo de planilha). Cada importação guarda o saldo do dia para o histórico.</div>`;
}

function formularioMapa(p, chave) {
  const papelDe = {};
  for (const [papel, cols] of Object.entries(p.colunas || {})) for (const c of cols) papelDe[c] = papel;
  const ncol = Math.max(p.cabecalho.length, ...p.amostra.map((l) => l.length));
  const nomes = Array.from({ length: ncol }, (_, j) => p.cabecalho[j] || `Coluna ${j + 1}`);
  return `<div class="alerta-faixa">Não reconheci as colunas deste arquivo. Diga o que é cada uma — precisa de <b>Data</b>, <b>Descrição</b> e
      <b>Valor</b> (ou Crédito e Débito). O Open Balance lembra disso nas próximas vezes.</div>
    <div class="tabela-envolve"><table class="tabela tabela-mini mapa"><thead><tr>${nomes.map((n, j) => `<th>
        <div class="corte mudo" title="${esc(n)}">${esc(n)}</div>
        <select data-mapa="${chave}" data-col="${j}">${PAPEIS.map(([v, r]) => `<option value="${v}" ${(papelDe[j] || "") === v ? "selected" : ""}>${r}</option>`).join("")}</select></th>`).join("")}</tr></thead>
      <tbody>${p.amostra.slice(0, 6).map((l) => `<tr>${nomes.map((_, j) => `<td><div class="corte">${esc(l[j] ?? "")}</div></td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="previa-acoes"><span class="espaco"></span><button class="botao botao-acento" data-aplicar-mapa="${chave}">Usar estas colunas</button></div>`;
}

const link = (url, texto) => `<a class="link" href="${url}" target="_blank" rel="noopener noreferrer">${texto}</a>`;

// Credenciais aparecem mascaradas; o botão de olho mostra (útil ao compartilhar a tela).
const ICONES_OLHO = `<svg class="olho-aberto" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>`
  + `<svg class="olho-fechado" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.4 0 10 7 10 7a17.6 17.6 0 0 1-2.16 3.19M6.6 6.6A17.4 17.4 0 0 0 2 12s3.6 7 10 7a9.3 9.3 0 0 0 5.4-1.6"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M2 2l20 20"/></svg>`;
const botaoRevelar = (rotulo) => `<button type="button" class="botao-revelar" data-rotulo="${rotulo}" aria-pressed="false" aria-label="Mostrar ${rotulo}" title="Mostrar">${ICONES_OLHO}</button>`;

function cartaoConectar(d) {
  const info = d.pluggyInfo || { itemIds: [] };
  const conectado = d.pluggy;
  const sinc = d.ultimaSincronizacao;
  return `<div class="cartao conectar" id="conectar">
    <div class="cartao-topo"><span class="rotulo">Conectar pelo Open Finance (Pluggy)</span>
      <span class="pilula ${conectado ? "bom" : "neutra"}">${conectado ? `Conectado · ${info.itemIds.length} banco(s)` : "Opcional · automático"}</span></div>
    <div class="sub">${conectado
      ? `Seus bancos conectados atualizam pelo botão <b>Atualizar</b>, no topo${sinc?.fim ? ` (última vez ${horaRelativa(sinc.fim)})` : " — ainda não sincronizado"}. Bancos sem conexão continuam podendo vir por arquivo.`
      : "Em vez de exportar arquivos todo mês, o Open Balance pode puxar sozinho contas, cartões, faturas e investimentos pelo Open Finance, usando a Pluggy. Para uso pessoal é gratuito (pelo MeuPluggy). Leva uns 20 minutos e é feito uma vez só."}</div>
    <details class="tutorial" ${conectado ? "" : "open"}><summary>${conectado ? "Ver o passo a passo de novo" : "Passo a passo"}</summary>
      <div class="alerta-faixa">A conta de desenvolvedor da Pluggy tem <b>15 dias de teste</b>, e só dá para vincular bancos ao MeuPluggy dentro desse prazo.
        Depois, os bancos já vinculados continuam atualizando, mas não dá para adicionar outros — então faça todos os passos de uma vez, com todos os seus bancos.</div>
      <ol class="passos">
        <li><b>Conecte seus bancos no MeuPluggy.</b> Crie uma conta grátis em ${link("https://meu.pluggy.ai", "meu.pluggy.ai")}, clique no botão de conectar
          e autorize cada banco pelo Open Finance (o mesmo tipo de consentimento que você dá a outros apps). Aceite todas as permissões — sem a de
          investimentos, a carteira não aparece. O consentimento vale 12 meses.</li>
        <li><b>Crie uma conta de desenvolvedor.</b> Em ${link("https://dashboard.pluggy.ai", "dashboard.pluggy.ai")}, cadastre-se (é aqui que começam os
          15 dias de teste) e crie um time, se for pedido.</li>
        <li><b>Crie uma aplicação.</b> No menu <b>Applications</b>, crie uma aplicação de desenvolvimento. Ela mostra o <b>Client ID</b> e o
          <b>Client Secret</b>: cole os dois aqui embaixo. Se o conector MeuPluggy não aparecer na lista de conectores da aplicação, habilite-o nas
          configurações dela.</li>
        <li><b>Ligue o MeuPluggy à aplicação.</b> Na página da aplicação, clique em <b>Ir para Demo</b>, escolha o conector <b>MeuPluggy</b> e entre com
          a sua conta do meu.pluggy.ai. Repita uma vez para cada banco.</li>
        <li><b>Copie os Item IDs.</b> Ainda na Demo, no menu <b>⋯</b> (canto superior direito) de cada conexão, clique em <b>Copiar Item ID</b> e cole
          aqui — um por banco, separados por vírgula.</li>
        <li><b>Clique em Conectar</b> e depois em <b>Atualizar</b>, no topo. A primeira vez traz até 12 meses de histórico; depois, os dados atualizam
          uma vez por dia no banco.</li>
      </ol>
      <ul class="mudo notas">
        <li>Só leitura: o Open Balance nunca faz pagamentos nem transferências. Na Pluggy, use só o produto de dados.</li>
        <li>As credenciais ficam no arquivo <b>.env</b> desta pasta, só neste computador. Não coloque a pasta do Open Balance no Google Drive, OneDrive ou Dropbox.</li>
        <li>Se um dia reconectar um banco, ele ganha um Item ID novo: é só trocar aqui. O histórico antigo é aproveitado.</li>
        <li>Mais detalhes: ${link("https://github.com/pluggyai/meu-pluggy", "MeuPluggy no GitHub")} · ${link("https://docs.pluggy.ai", "documentação da Pluggy")}.</li>
      </ul>
    </details>
    <form class="grade-form" id="form-pluggy" autocomplete="off">
      <label class="campo">Client ID<span class="campo-segredo"><input name="clientId" class="mascarado" value="${esc(info.clientId || "")}" placeholder="ex.: 1a2b3c4d-5e6f-…" spellcheck="false">${botaoRevelar("Client ID")}</span></label>
      <label class="campo">Client Secret<span class="campo-segredo"><input name="clientSecret" type="password" autocomplete="new-password" spellcheck="false"
        placeholder="${info.temSecret ? "salvo — deixe em branco para manter" : "cole aqui"}">${botaoRevelar("Client Secret")}</span></label>
      <label class="campo campo-largo">Item IDs (um por banco, separados por vírgula)
        <span class="campo-segredo"><textarea name="itemIds" class="mascarado" rows="2" spellcheck="false" placeholder="ex.: 9f8e7d6c-…, 1a2b3c4d-…">${esc(info.itemIds.join(", "))}</textarea>${botaoRevelar("Item IDs")}</span></label>
    </form>
    <div class="previa-acoes">
      ${conectado ? `<button class="botao" id="pluggy-atualizar">Atualizar agora</button>
        <button class="botao botao-fantasma" id="pluggy-desconectar">Desconectar</button>` : `<span class="mudo">A conexão é conferida na Pluggy antes de salvar.</span>`}
      <span class="espaco"></span>
      <button class="botao botao-acento" type="submit" form="form-pluggy" id="pluggy-conectar">${conectado ? "Salvar alterações" : "Conectar"}</button>
    </div>
  </div>`;
}

function cartaoContas(d) {
  const importadas = d.contas.filter((c) => c.origem === "importacao");
  if (!importadas.length) return "";
  const ultima = (id) => d.importacoes.find((i) => i.conta_id === id);
  return `<div class="cartao"><div class="cartao-topo"><span class="rotulo">Contas importadas</span><span class="mudo">${importadas.length}</span></div>
    <ul class="lista">${importadas.map((c) => {
      const imp = ultima(c.id);
      const cartao = c.tipo === "CREDIT";
      const detalhe = cartao
        ? (c.limite ? `limite ${brl(c.limite)}` : "limite não informado")
        : (c.semSaldo ? "saldo não informado" : `saldo ${brl(c.saldo)}${c.saldoData ? ` (base ${dataBR(c.saldoData)})` : ""}`);
      return `<li>${avatarInstituicao(c.instituicao)}<div class="meio"><div class="titulo">${esc(c.nome)}${c.final ? ` <span class="mudo">•••• ${esc(c.final)}</span>` : ""}</div>
        <div class="linha2">${cartao ? "Cartão" : esc(c.subtipo || "Conta")} · ${detalhe}${imp ? ` · arquivo mais recente ${horaRelativa(imp.criada_em)}` : ""}</div></div>
        <button class="botao botao-fantasma" data-editar-conta="${esc(c.id)}">Editar</button>
        <button class="botao botao-fantasma" data-excluir-conta="${esc(c.id)}" title="Excluir conta e lançamentos">Excluir</button></li>`;
    }).join("")}</ul></div>`;
}

function cartaoHistorico(d) {
  if (!d.importacoes.length) return "";
  return `<div class="cartao"><div class="cartao-topo"><span class="rotulo">Histórico de importações</span></div>
    <ul class="lista">${d.importacoes.map((i) => `<li><span class="icone-cat">${ICONE_TIPO[i.tipo] || "📄"}</span>
      <div class="meio"><div class="titulo" title="${esc(i.arquivo)}">${esc(i.arquivo)}</div>
      <div class="linha2">${horaRelativa(i.criada_em)} · ${esc(i.conta || TIPOS[i.tipo] || "")} · ${i.tipo === "investimentos" ? `${i.novas} posições` : `${i.novas} novo(s), ${i.existentes} já existia(m)`}${i.inicio ? ` · ${dataBR(i.inicio)}${i.fim && i.fim !== i.inicio ? ` a ${dataBR(i.fim)}` : ""}` : ""}</div></div>
      <button class="botao botao-fantasma" data-desfazer="${i.id}">Desfazer</button></li>`).join("")}</ul></div>`;
}

function cartaoTitular(d) {
  return `<div class="cartao"><div class="cartao-topo"><span class="rotulo">Seu nome</span></div>
    <div class="sub">Usado para reconhecer Pix e TEDs entre as suas próprias contas nos arquivos importados (eles não contam como gasto nem como receita).</div>
    <form class="linha-form" id="form-titular">
      <input type="text" id="campo-titular" value="${esc(d.nomeTitular || "")}" placeholder="Nome completo, como aparece no banco" maxlength="80" autocomplete="name">
      <button class="botao" type="submit">Salvar</button>
    </form></div>`;
}

// ============================================================ eventos
function ligar() {
  const raiz = ctx.conteudo;
  const campo = raiz.querySelector("#campo-arquivos");
  const zona = raiz.querySelector("#zona-soltar");
  campo.addEventListener("change", () => { adicionar([...campo.files]); campo.value = ""; });
  zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("arrastando"); });
  zona.addEventListener("dragleave", () => zona.classList.remove("arrastando"));
  zona.addEventListener("drop", (e) => { e.preventDefault(); zona.classList.remove("arrastando"); adicionar([...e.dataTransfer.files]); });

  raiz.querySelectorAll("[data-chave]").forEach((cartao) => {
    const { arq, parte, i } = achar(cartao.dataset.chave);
    cartao.querySelectorAll("[data-op]").forEach((el) => {
      const op = el.dataset.op;
      const reanalisa = REANALISAR.has(op);
      el.addEventListener(reanalisa ? "change" : "input", () => {
        let v = el.value;
        if (op === "fechada") v = v === "1";
        definir(parte, op, v);
        if (reanalisa) reanalisar(arq, i);
      });
    });
    cartao.querySelectorAll("[data-modo]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      definir(parte, "modoFatura", a.dataset.modo);
      reanalisar(arq, i);
    }));
  });
  raiz.querySelectorAll("[data-importar]").forEach((b) => b.addEventListener("click", () => {
    const { arq, i } = achar(b.dataset.importar);
    if (arq) importarParte(arq, i);
  }));
  raiz.querySelectorAll("[data-descartar]").forEach((b) => b.addEventListener("click", () => {
    const { arq, parte } = achar(b.dataset.descartar);
    if (!arq) return;
    if (parte && arq.partes.filter((p) => !p.feita).length > 1) parte.feita = true;
    else pendentes.splice(pendentes.indexOf(arq), 1);
    desenhar();
  }));
  raiz.querySelector("#importar-todos")?.addEventListener("click", importarTodos);
  raiz.querySelectorAll("[data-aplicar-mapa]").forEach((b) => b.addEventListener("click", async () => {
    const { arq } = achar(b.dataset.aplicarMapa);
    const p = arq.partes[0].previa;
    const papeis = {};
    raiz.querySelectorAll(`[data-mapa="${b.dataset.aplicarMapa}"]`).forEach((s) => {
      if (s.value) (papeis[s.value] = papeis[s.value] || []).push(Number(s.dataset.col));
    });
    if (!papeis.data || !papeis.descricao || !(papeis.valor || papeis.credito || papeis.debito)) {
      ctx.avisar("Escolha ao menos Data, Descrição e Valor (ou Crédito/Débito).", true);
      return;
    }
    arq.mapeamento = { aba: p.aba || "", cabecalho: p.linhaCabecalho ?? -1, papeis };
    arq.carregando = true;
    desenhar();
    try {
      arq.partes = (await analisar(arq)).map((previa) => ({ previa, opcoes: {} }));
      if (arq.partes[0]?.previa.precisaMapeamento) arq.partes[0].erro = "Com essas colunas não encontrei nenhum lançamento. Confira a escolha.";
    } catch (e) {
      arq.erro = e.message;
    }
    arq.carregando = false;
    desenhar();
  }));
  raiz.querySelectorAll("[data-desfazer]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Desfazer esta importação? Os lançamentos, faturas e posições que ela trouxe serão apagados (o que já existia antes continua).")) return;
    await acao(() => ctx.api("/api/importar/desfazer", { id: Number(b.dataset.desfazer) }), "Importação desfeita.");
  }));
  raiz.querySelectorAll("[data-excluir-conta]").forEach((b) => b.addEventListener("click", async () => {
    const conta = ctx.dados.contas.find((c) => c.id === b.dataset.excluirConta);
    if (!confirm(`Excluir “${conta.nome}” e todos os lançamentos importados dela? Isso não pode ser desfeito.`)) return;
    await acao(() => ctx.api("/api/contas/excluir", { contaId: conta.id }), "Conta excluída.");
  }));
  raiz.querySelectorAll("[data-editar-conta]").forEach((b) => b.addEventListener("click", () => editarConta(b.dataset.editarConta)));
  raiz.querySelectorAll(".botao-revelar").forEach((b) => b.addEventListener("click", () => {
    const campo = b.parentElement.querySelector("input, textarea");
    const mostrar = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(mostrar));
    b.setAttribute("aria-label", `${mostrar ? "Ocultar" : "Mostrar"} ${b.dataset.rotulo}`);
    b.title = mostrar ? "Ocultar" : "Mostrar";
    if (campo.name === "clientSecret") campo.type = mostrar ? "text" : "password";
    else campo.classList.toggle("mascarado", !mostrar);
  }));
  raiz.querySelector("#form-pluggy").addEventListener("submit", async (e) => {
    e.preventDefault();
    const botao = raiz.querySelector("#pluggy-conectar");
    botao.disabled = true;
    botao.textContent = "Conferindo na Pluggy…";
    try {
      const r = await ctx.api("/api/pluggy/conectar", Object.fromEntries(new FormData(e.target)));
      await ctx.recarregar();
      ctx.avisar(`Conectado: ${r.itens.length} banco(s) encontrado(s) na Pluggy. Agora clique em Atualizar (no topo) para puxar os dados.`);
    } catch (erro) {
      ctx.avisar(`Não conectou: ${erro.message}`, true);
      botao.disabled = false;
      botao.textContent = ctx.dados.pluggy ? "Salvar alterações" : "Conectar";
    }
  });
  raiz.querySelector("#pluggy-atualizar")?.addEventListener("click", () => document.getElementById("botao-sinc").click());
  raiz.querySelector("#pluggy-desconectar")?.addEventListener("click", () => {
    if (!confirm("Desconectar a Pluggy? O que já foi sincronizado continua no Open Balance; só para de atualizar sozinho. As credenciais são apagadas do arquivo .env.")) return;
    acao(() => ctx.api("/api/pluggy/desconectar", {}), "Pluggy desconectada. Os dados já sincronizados continuam aqui.");
  });
  raiz.querySelector("#form-titular").addEventListener("submit", (e) => {
    e.preventDefault();
    acao(() => ctx.api("/api/preferencias", { titular: raiz.querySelector("#campo-titular").value }), "Nome salvo.");
  });
}

async function acao(fazer, sucesso) {
  try {
    await fazer();
    await ctx.recarregar();
    ctx.avisar(sucesso);
  } catch (e) {
    ctx.avisar(`Não deu certo: ${e.message}`, true);
  }
}

// ============================================================ editar conta importada
function modalConta() {
  let modal = document.getElementById("modal-conta");
  if (modal) return modal;
  modal = document.createElement("dialog");
  modal.id = "modal-conta";
  modal.className = "modal";
  document.body.append(modal);
  return modal;
}

function editarConta(id) {
  const c = ctx.dados.contas.find((x) => x.id === id);
  if (!c) return;
  const cartao = c.tipo === "CREDIT";
  const fatura = c.fatura || {};
  const numeroBR = (v) => (v === null || v === undefined ? "" : String(v).replace(".", ","));
  const modal = modalConta();
  modal.innerHTML = `<form method="dialog" id="form-conta">
    <h2>Editar ${cartao ? "cartão" : "conta"}</h2>
    <p class="modal-sub">${esc(c.nome)}${c.final ? ` · final ${esc(c.final)}` : ""}</p>
    <div class="grade-form">
      <label class="campo">Instituição<input name="instituicao" list="lista-instituicoes" value="${esc(c.instituicao)}" maxlength="40"></label>
      <label class="campo">Apelido<input name="nome" value="${esc(c.apelido || "")}" maxlength="40" placeholder="opcional"></label>
      <label class="campo">Final<input name="final" value="${esc(c.final)}" maxlength="4" inputmode="numeric"></label>
      ${cartao ? `
        <label class="campo">Limite total<input name="limite" value="${esc(numeroBR(c.limite))}" inputmode="decimal" placeholder="ex.: 5.000,00"></label>
        <label class="campo">Limite disponível<input name="disponivel" value="${esc(numeroBR(c.disponivel))}" inputmode="decimal" placeholder="estimar">
          <small>Em branco: limite − o que ainda falta pagar.</small></label>
        <label class="campo">Dia de fechamento<input name="diaFechamento" type="number" min="1" max="31" value="${esc(fatura.diaFechamento || "")}"></label>
        <label class="campo">Dia de vencimento<input name="diaVencimento" type="number" min="1" max="31" value="${esc(fatura.diaVencimento || "")}"></label>`
      : `<label class="campo">Saldo atual<input name="saldo" inputmode="decimal" placeholder="${c.semSaldo ? "não informado" : esc(numeroBR(c.saldo))}">
          <small>Os próximos arquivos somam a partir deste saldo.</small></label>`}
    </div>
    <div class="modal-acoes"><span class="espaco"></span>
      <button type="button" class="botao botao-fantasma" id="conta-cancelar">Cancelar</button>
      <button type="submit" class="botao botao-acento">Salvar</button></div>
  </form>`;
  modal.querySelector("#conta-cancelar").onclick = () => modal.close();
  modal.querySelector("#form-conta").onsubmit = (e) => {
    e.preventDefault();
    const dados = Object.fromEntries(new FormData(e.target));
    modal.close();
    acao(() => ctx.api("/api/contas/editar", { contaId: id, ...dados }), "Conta atualizada.");
  };
  modal.showModal();
}
