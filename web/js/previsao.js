// Aba Previsão: saldo das contas dia a dia até o fim do 3º mês seguinte, com tudo o que deve entrar e sair.
// O cálculo fica no backend (openbalance/previsao.py); aqui só desenha e grava os ajustes do usuário.
import { desenharColunas, desenharLinhas, linhaDica } from "./graficos.js";
import { avatarInstituicao, brl, brlSinal, dataCurta, dataLonga, diasNoMes, esc, iconeGrupo, nomeMes, nomeMesCurto, nomeMesSo } from "./util.js";

const LIMITE_EVENTOS = 14;
let mostrarTodos = false;

// Previsão em reais inteiros: centavos aqui seriam precisão de mentira.
const reais = (v) => { const r = Math.round(v) || 0; return (r < 0 ? "−" : "") + brl(Math.abs(r)).replace(/,00$/, ""); };
const reaisSinal = (v) => brlSinal(Math.round(v) || 0).replace(/,00$/, "");

const fimDoMes = (mes) => `${mes}-${String(diasNoMes(mes)).padStart(2, "0")}`;
const maiuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);
function somarDias(iso, n) {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(a, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Frase para os destaques da Visão geral: como as contas devem fechar o mês corrente. */
export function destaquePrevisao(p) {
  const m = p.meses[0];
  const link = ` <a class="link" href="#/previsao">ver previsão ↗</a>`;
  if (!p.saldoConhecido) {
    return `Pela previsão, de hoje até ${dataCurta(fimDoMes(m.mes))} devem ${m.final < 0 ? "sair" : "sobrar"} <b>${reais(Math.abs(m.final))}</b> nas contas.${link}`;
  }
  const alerta = p.alerta && p.alerta.data <= fimDoMes(m.mes) ? `, mas ficam no negativo a partir de ${dataCurta(p.alerta.data)}` : "";
  return `Pela previsão, as contas fecham ${nomeMesSo(m.mes)} com <b class="${m.final < 0 ? "negativo" : ""}">${reais(m.final)}</b>${alerta}.${link}`;
}

export function telaPrevisao(conteudo, estado, ui) {
  const { cartao, topoCartao, tile } = ui;
  const p = estado.dados.previsao;
  const b = estado.base;
  if (!p) {
    conteudo.innerHTML = `<div class="vazio"><h2>Ainda não dá para prever</h2><p>Importe o extrato da conta e a fatura do cartão na aba <a class="link" href="#/importar">Importar</a>.</p></div>`;
    return;
  }
  const fontes = new Map(p.fontes.map((f) => [f.id, f]));
  const saldoDoDia = new Map(p.diario.map((x) => [x.data, x.saldo]));
  const eventosDoDia = new Map();
  for (const e of p.eventos) eventosDoDia.set(e.data, [...(eventosDoDia.get(e.data) || []), e]);
  const conhecido = p.saldoConhecido;
  const menor = p.diario.reduce((a, x) => (x.saldo < a.saldo ? x : a), p.diario[0]);

  // --- avisos
  const avisos = [];
  if (!conhecido) {
    avisos.push(`Não sei o saldo de hoje${p.contasSemSaldo.length ? ` de <b>${esc(p.contasSemSaldo.join(", "))}</b>` : " das suas contas"}. Informe em <a class="link" href="#/importar">Importar → Contas importadas → Editar</a>. Enquanto isso, a previsão mostra só quanto deve entrar e sair a partir de hoje.`);
  } else if (p.contasSemSaldo.length) {
    avisos.push(`Sem saldo informado, fica fora da soma: <b>${esc(p.contasSemSaldo.join(", "))}</b>. Dá para informar em <a class="link" href="#/importar">Importar → Editar</a>.`);
  }
  if (p.alerta) {
    avisos.push(`Pelo previsto, o saldo das contas fica <b>negativo a partir de ${dataCurta(p.alerta.data)}</b> (${reais(p.alerta.saldo)}).`);
  }

  // --- tiles por mês
  const tiles = p.meses.map((m, i) => {
    const variacao = m.final - m.inicial;
    const detalhe = `${reaisSinal(variacao)} ${i === 0 ? "até o fim do mês" : "no mês"}`;
    return conhecido
      ? tile(`Fim de ${nomeMesSo(m.mes)}`, reais(m.final), detalhe, m.final < 0 ? "negativo" : "")
      : tile(`Até o fim de ${nomeMesSo(m.mes)}`, reaisSinal(m.final), detalhe, m.final < 0 ? "negativo" : "positivo");
  });
  if (conhecido) tiles.push(tile("Menor saldo previsto", reais(menor.saldo), dataLonga(menor.data), menor.saldo < 0 ? "negativo" : ""));

  // --- tabela mês a mês
  const celula = (v) => `<td class="direita num">${Math.abs(v) < 0.5 ? `<span class="mudo">—</span>` : `<span class="${v > 0 ? "positivo" : ""}">${reaisSinal(v)}</span>`}</td>`;
  const linhasMes = p.meses.map((m, i) => `<tr>
      <td title="${esc(maiuscula(nomeMes(m.mes)))}"><b>${esc(maiuscula(nomeMesCurto(m.mes)))}</b>${i === 0 ? `<div class="mudo" style="font-size:11px">de amanhã até ${diasNoMes(m.mes)}</div>` : ""}</td>
      <td class="direita num">${conhecido ? reais(m.inicial) : reaisSinal(m.inicial)}</td>
      ${celula(m.entradas)}${celula(m.faturas)}${celula(m.contas)}${celula(m.diaADia)}${celula(m.outros)}
      <td class="direita num"><b class="${m.final < 0 ? "negativo" : ""}">${conhecido ? reais(m.final) : reaisSinal(m.final)}</b></td>
      <td class="direita num"><span class="${m.menor < 0 ? "negativo" : "mudo"}">${reais(m.menor)}</span><div class="mudo" style="font-size:11px">${dataCurta(m.menorData)}</div></td>
    </tr>`).join("");

  // --- próximos lançamentos
  const icone = (f) => {
    if (f.tipo === "fatura") return avatarInstituicao(f.instituicao, true);
    if (f.tipo === "entrada") return `<span class="icone-cat">💵</span>`;
    if (f.tipo === "manual") return `<span class="icone-cat">📌</span>`;
    return `<span class="icone-cat">${iconeGrupo(b.grupoDe(f.categoriaId))}</span>`;
  };
  const detalhe = (f) => {
    if (f.tipo === "fatura") {
      if (f.fechada) return "Fatura fechada, ainda não paga";
      const partes = [`${reais(f.lancado)} já lançados`];
      if (f.assinaturas) partes.push(`${reais(f.assinaturas)} de assinaturas`);
      if (f.estimativa) partes.push(`${reais(f.estimativa)} estimados`);
      return partes.join(" + ");
    }
    if (f.tipo === "manual") return `Você adicionou · ${f.detalhe.toLowerCase()}`;
    return f.tipo === "conta" ? `${f.detalhe} · todo mês` : f.detalhe;
  };
  const visiveis = mostrarTodos ? p.eventos : p.eventos.slice(0, LIMITE_EVENTOS);
  const linhasEventos = visiveis.map((e) => {
    const f = fontes.get(e.fonte);
    const estimada = f.tipo === "fatura" && f.estimativa > 0;
    return `<li>
      <span class="data-evento"><b>${Number(e.data.slice(8, 10))}</b><small>${esc(nomeMesCurto(e.data.slice(0, 7)).split("/")[0])}</small></span>
      ${icone(f)}
      <div class="meio"><div class="titulo">${esc(f.tipo === "fatura" ? `Fatura ${f.instituicao}${f.final ? ` •••• ${f.final}` : ""}` : f.nome)}${estimada ? `<span class="marcador">estimada</span>` : ""}</div><div class="linha2">${esc(detalhe(f))}</div></div>
      <div class="direita"><div class="num"><b class="${e.valor > 0 ? "positivo" : ""}">${reaisSinal(e.valor)}</b></div>
        ${conhecido ? `<div class="linha2 num">saldo ${reais(saldoDoDia.get(e.data))}</div>` : ""}</div>
    </li>`;
  }).join("");

  // --- premissas
  const dd = p.diaADia;
  const manualConta = p.ajustes.diaADiaConta !== null && p.ajustes.diaADiaConta !== undefined;
  const manualCartao = p.ajustes.diaADiaCartao !== null && p.ajustes.diaADiaCartao !== undefined;
  const periodo = (base) => (base.length ? `${nomeMesCurto(base[0].mes)} a ${nomeMesCurto(base[base.length - 1].mes)}` : "");
  const campoDiaADia = (id, rotulo, ajuda, info, manual) => `
    <div class="premissa">
      <label class="campo">${esc(rotulo)}
        <input type="number" class="dinheiro" id="dd-${id}" min="0" step="100" inputmode="decimal" value="${manual ? info.usado : ""}" placeholder="${Math.round(info.auto)}">
        <small>${ajuda} Automático: <b>${reais(info.auto)}</b>${info.meses.length ? `, a mediana de ${esc(periodo(info.meses))}` : ""}.
          ${manual ? `<a href="#" class="link" data-automatico="${id}">Voltar ao automático</a>` : "Deixe em branco para usar o automático."}</small>
      </label>
      ${info.meses.length > 1 ? `<div id="g-dd-${id}" class="mini-colunas"></div>` : ""}
    </div>`;
  const recorrentes = p.fontes.filter((f) => f.tipo === "entrada" || f.tipo === "conta");
  const manuais = p.fontes.filter((f) => f.tipo === "manual");
  const linhaFonte = (f) => `<li class="${f.ignorado ? "esmaecida" : ""}">
      <label class="campo-check" title="${f.ignorado ? "Fora da previsão" : "Entra na previsão"}"><input type="checkbox" data-fonte="${esc(f.id)}" ${f.ignorado ? "" : "checked"} aria-label="Considerar ${esc(f.nome)} na previsão"></label>
      <div class="meio"><div class="titulo">${esc(f.nome)}</div><div class="linha2">${esc(f.detalhe)}${f.proxima ? ` · próxima ${dataCurta(f.proxima)}` : ""}</div></div>
      <div class="direita num"><b class="${f.valor > 0 ? "positivo" : ""}">${reaisSinal(f.valor)}</b></div>
    </li>`;
  const amanha = somarDias(p.hoje, 1);

  conteudo.innerHTML = `
    ${avisos.map((a) => `<div class="alerta-faixa">${a}</div>`).join("")}
    <section class="grade">
      ${cartao("c12", `
        ${topoCartao("Previsão de caixa", `<span class="mudo" style="font-size:12px">saldo das contas correntes e poupança${p.saldoData && p.saldoData < p.hoje ? ` · saldo de partida de ${dataCurta(p.saldoData)}` : ""}</span>`)}
        <div class="heroi">${conhecido ? reais(p.meses[0].final) : reaisSinal(p.meses[0].final)} <small>${conhecido ? "previsto para" : "de resultado previsto (entra − sai) até"} ${dataCurta(fimDoMes(p.meses[0].mes))}</small></div>
        <div class="sub">Hoje: ${conhecido ? `<b>${reais(p.saldoInicial)}</b> nas contas` : "saldo desconhecido"} · ${p.eventos.length} lançamentos previstos até ${dataCurta(p.fim)}</div>
        <div id="g-previsao" style="margin-top:14px"></div>
        <div class="tiles" style="margin-top:14px">${tiles.join("")}</div>`)}
    </section>

    <section class="grade">
      ${cartao("c12", `${topoCartao("Mês a mês")}
        <div class="tabela-envolve"><table class="tabela compacta"><thead><tr>
          <th>Mês</th><th class="direita">Início</th><th class="direita">Entradas</th><th class="direita">Faturas</th>
          <th class="direita">Contas fixas</th><th class="direita">Dia a dia</th><th class="direita">Adicionados</th>
          <th class="direita">Fim</th><th class="direita">Menor saldo</th>
        </tr></thead><tbody>${linhasMes}</tbody></table></div>`)}
    </section>

    <section class="grade">
      ${cartao("c7", `${topoCartao("Próximos lançamentos", `<span class="mudo" style="font-size:12px">até ${dataCurta(p.fim)}</span>`)}
        <ul class="lista">${linhasEventos || `<li class="mudo">Nada previsto. Adicione o salário e as contas ao lado.</li>`}</ul>
        ${p.eventos.length > LIMITE_EVENTOS ? `<div class="mais"><button class="botao botao-fantasma" id="ver-todos">${mostrarTodos ? "Mostrar menos" : `Mostrar todos (${p.eventos.length})`}</button></div>` : ""}
        <div class="rodape-cartao"><span>O gasto do dia a dia na conta (${reais(dd.conta.usado)}/mês) sai aos poucos, todo dia, e não aparece nesta lista.</span></div>`)}
      ${cartao("c5", `${topoCartao("Como a previsão é feita")}
        <p class="sub" style="margin:6px 0 14px">Saldo de hoje + entradas que se repetem − faturas dos cartões − contas fixas − gasto do dia a dia ± o que você adicionar.
          Aplicações, resgates, transferências entre suas contas e empréstimos a terceiros não entram.</p>
        ${campoDiaADia("conta", "Dia a dia na conta, por mês", "Pix, débito e boletos que não se repetem.", dd.conta, manualConta)}
        ${campoDiaADia("cartao", "Dia a dia no cartão, por fatura", "Compras sem contar parcelas e assinaturas, que já entram separadas.", dd.cartao, manualCartao)}
        <div class="rotulo" style="margin-top:18px">Entradas e contas que se repetem</div>
        <ul class="lista">${recorrentes.map(linhaFonte).join("") || `<li class="mudo">Não encontrei nada que se repita todo mês. Adicione o salário abaixo.</li>`}</ul>
        <div class="rotulo" style="margin-top:18px">Adicionados por você</div>
        <ul class="lista">${manuais.map((f) => `<li>
            <span class="icone-cat">📌</span>
            <div class="meio"><div class="titulo">${esc(f.nome)}</div><div class="linha2">${f.manual.mensal ? `todo mês desde ${dataCurta(f.manual.data)}` : dataLonga(f.manual.data)}${f.proxima ? "" : " · fora do período"}</div></div>
            <div class="direita num"><b class="${f.valor > 0 ? "positivo" : ""}">${reaisSinal(f.valor)}</b></div>
            <button class="botao-linha" data-remover="${esc(f.manual.id)}" title="Remover" aria-label="Remover ${esc(f.nome)}">✕</button>
          </li>`).join("") || `<li class="mudo">Bônus, 13º, IPVA, viagem, um resgate programado… o que você já sabe que vai acontecer.</li>`}</ul>
        <form id="form-manual" class="form-manual">
          <input name="descricao" placeholder="Descrição (ex.: IPVA)" maxlength="80" required aria-label="Descrição">
          <select name="sentido" aria-label="Entrada ou saída"><option value="-1">Saída</option><option value="1">Entrada</option></select>
          <input name="valor" type="number" min="0.01" step="0.01" inputmode="decimal" placeholder="Valor" required class="dinheiro" aria-label="Valor">
          <input name="data" type="date" min="${amanha}" max="${p.fim}" value="${amanha}" required aria-label="Data">
          <label class="campo-check"><input type="checkbox" name="mensal"> Todo mês</label>
          <button class="botao botao-acento" type="submit">Adicionar</button>
        </form>`)}
    </section>`;

  // --- gráfico do saldo
  const serie = p.diario.map((x) => x.saldo);
  const elGrafico = document.getElementById("g-previsao");
  const pertoDemais = Math.ceil((52 * serie.length) / Math.max(1, elGrafico.clientWidth - 70)); // "hoje" e o 1º mês não se encostam
  const marcas = [0, ...p.diario.map((x, i) => (x.data.endsWith("-01") && i >= pertoDemais ? i : -1)).filter((i) => i > 0)];
  desenharLinhas(elGrafico, {
    n: serie.length, altura: 230, marcasX: marcas,
    rotuloX: (i) => (i === 0 ? "hoje" : nomeMesCurto(p.diario[i].data.slice(0, 7))),
    series: [{ nome: "Saldo previsto", valores: serie, cor: "var(--acento)", corNegativa: "var(--negativo)" }],
    dica: (i) => {
      const dia = p.diario[i];
      const evs = eventosDoDia.get(dia.data) || [];
      return `<div class="t">${esc(i === 0 ? "Hoje" : dataLonga(dia.data))}</div>${linhaDica(null, conhecido ? "Saldo previsto" : "Acumulado", conhecido ? reais(dia.saldo) : reaisSinal(dia.saldo))}`
        + evs.slice(0, 4).map((e) => linhaDica(null, fontes.get(e.fonte).nome.slice(0, 26), reaisSinal(e.valor))).join("")
        + (evs.length > 4 ? `<div class="l">+${evs.length - 4} lançamentos</div>` : "");
    },
  });
  for (const [id, info] of [["conta", dd.conta], ["cartao", dd.cartao]]) {
    const el = document.getElementById(`g-dd-${id}`);
    if (!el) continue;
    desenharColunas(el, {
      altura: 110, rotularDestaque: false,
      itens: info.meses.map((m) => ({
        rotulo: nomeMesCurto(m.mes).split("/")[0], valor: m.valor, estilo: "normal",
        dica: `<div class="t">${esc(maiuscula(nomeMes(m.mes)))}</div>${linhaDica(null, id === "conta" ? "Dia a dia na conta" : "Fatura sem parcelas e assinaturas", reais(m.valor))}`,
      })),
    });
  }

  // --- ações
  const salvar = async (mudanca, mensagem) => {
    try {
      await ui.api("/api/previsao", { ...p.ajustes, ...mudanca });
      await ui.recarregar();
      ui.avisar(mensagem);
    } catch (e) {
      ui.avisar(`Não consegui salvar: ${e.message}`, true);
    }
  };
  conteudo.querySelector("#ver-todos")?.addEventListener("click", () => { mostrarTodos = !mostrarTodos; telaPrevisao(conteudo, estado, ui); });
  for (const id of ["conta", "cartao"]) {
    const campo = id === "conta" ? "diaADiaConta" : "diaADiaCartao";
    conteudo.querySelector(`#dd-${id}`).addEventListener("change", (e) => {
      const valor = e.target.value.trim();
      salvar({ [campo]: valor === "" ? null : Number(valor) }, valor === "" ? "Voltou ao valor automático." : "Previsão atualizada.");
    });
    conteudo.querySelector(`[data-automatico="${id}"]`)?.addEventListener("click", (e) => {
      e.preventDefault();
      salvar({ [campo]: null }, "Voltou ao valor automático.");
    });
  }
  conteudo.querySelectorAll("[data-fonte]").forEach((caixa) => caixa.addEventListener("change", () => {
    const ignorados = new Set(p.ajustes.ignorados);
    caixa.checked ? ignorados.delete(caixa.dataset.fonte) : ignorados.add(caixa.dataset.fonte);
    salvar({ ignorados: [...ignorados] }, caixa.checked ? "Voltou para a previsão." : "Ficou fora da previsão.");
  }));
  conteudo.querySelectorAll("[data-remover]").forEach((botao) => botao.addEventListener("click", () => {
    salvar({ manuais: p.ajustes.manuais.filter((m) => m.id !== botao.dataset.remover) }, "Lançamento removido.");
  }));
  conteudo.querySelector("#form-manual").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const valor = Number(f.get("valor")) * Number(f.get("sentido"));
    const novo = { descricao: f.get("descricao").trim(), valor, data: f.get("data"), mensal: f.get("mensal") === "on" };
    salvar({ manuais: [...p.ajustes.manuais, novo] }, "Lançamento adicionado à previsão.");
  });
}
