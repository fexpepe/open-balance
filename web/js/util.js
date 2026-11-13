// Formatação, escape de HTML e identidade visual (cores/ícones).

const formatoBRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const formatoNumero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
  "outubro", "novembro", "dezembro"];
const MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const DIAS_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

export const brl = (v) => formatoBRL.format(v || 0);
export const brlSinal = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + formatoBRL.format(Math.abs(v || 0));

export function compacto(v) {
  const a = Math.abs(v);
  const sinal = v < 0 && Math.round(a) ? "−" : "";
  if (a >= 1e6) return `${sinal}R$ ${formatoNumero.format(a / 1e6)} mi`;
  if (a >= 1e3) return `${sinal}R$ ${formatoNumero.format(a / 1e3)}k`;
  return `${sinal}R$ ${Math.round(a)}`;
}

export const pct = (v) => `${v > 0 ? "+" : ""}${formatoNumero.format(v)}%`;

export function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- datas (sempre strings ISO "AAAA-MM-DD", sem fuso) ----
export const mesDe = (iso) => iso.slice(0, 7);
export function somarMeses(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const total = a * 12 + (m - 1) + n;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}
export const diasNoMes = (mes) => { const [a, m] = mes.split("-").map(Number); return new Date(a, m, 0).getDate(); };
export const nomeMes = (mes) => { const [a, m] = mes.split("-").map(Number); return `${MESES[m - 1]} de ${a}`; };
export const nomeMesCurto = (mes) => { const [a, m] = mes.split("-").map(Number); return `${MESES_CURTOS[m - 1]}/${String(a).slice(2)}`; };
export const nomeMesSo = (mes) => MESES[Number(mes.slice(5, 7)) - 1];
export const dataBR = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "—");
export const dataCurta = (iso) => (iso ? `${Number(iso.slice(8, 10))} ${MESES_CURTOS[Number(iso.slice(5, 7)) - 1]}` : "—");
export function diaSemana(iso) { const [a, m, d] = iso.split("-").map(Number); return new Date(a, m - 1, d).getDay(); }
export const dataLonga = (iso) => `${DIAS_SEMANA[diaSemana(iso)]}, ${dataCurta(iso)}`;
export function diasEntre(a, b) {
  const [y1, m1, d1] = a.split("-").map(Number); const [y2, m2, d2] = b.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86400000);
}
export function horaRelativa(isoComHora) {
  if (!isoComHora) return "nunca";
  const d = new Date(isoComHora);
  const hoje = new Date();
  const hh = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === hoje.toDateString()) return `hoje às ${hh}`;
  const ontem = new Date(hoje); ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === ontem.toDateString()) return `ontem às ${hh}`;
  return `${d.toLocaleDateString("pt-BR")} às ${hh}`;
}

// ---- identidade visual ----
// Cor segue o grupo (entidade), nunca a posição no ranking. Grupos fora desta lista ficam neutros.
const COR_GRUPO = {
  "05000000": "var(--s1)", // Transferências
  "08000000": "var(--s2)", // Compras
  "07000000": "var(--s3)", // Serviços
  "17000000": "var(--s4)", // Moradia
  "11000000": "var(--s5)", // Alimentos e bebidas
  "19000000": "var(--s6)", // Transporte
  "02000000": "var(--s7)", // Empréstimos e financiamento
  "18000000": "var(--s8)", // Saúde
};
export const corGrupo = (grupoId) => COR_GRUPO[grupoId] || "var(--s-outros)";
export const grupoTemCor = (grupoId) => grupoId in COR_GRUPO;

const ICONE_GRUPO = {
  "01000000": "💵", "02000000": "🏦", "03000000": "📈", "04000000": "🔁", "05000000": "💸", "06000000": "⚖️",
  "07000000": "🧰", "08000000": "🛍️", "09000000": "📺", "10000000": "🛒", "11000000": "🍽️", "12000000": "✈️",
  "13000000": "🤝", "14000000": "🎲", "15000000": "🧾", "16000000": "🏧", "17000000": "🏠", "18000000": "🩺",
  "19000000": "🚗", "20000000": "🛡️", "21000000": "🎉", "99999999": "📦",
};
export const iconeGrupo = (grupoId) => ICONE_GRUPO[grupoId] || (String(grupoId).startsWith("P") ? "🏷️" : "📦");

const COR_INSTITUICAO = {
  "Itaú": ["#ec7000", "#fff", "itaú"], "Nubank": ["#820ad1", "#fff", "nu"], "Bradesco": ["#cc092f", "#fff", "B"],
  "Santander": ["#ec0000", "#fff", "S"], "Banco do Brasil": ["#fcea16", "#1a1a1a", "BB"], "Inter": ["#ff7a00", "#fff", "in"],
  "C6 Bank": ["#2b2b2b", "#fff", "C6"], "XP": ["#111", "#fff", "XP"], "BTG Pactual": ["#0a2240", "#fff", "btg"],
  "Caixa": ["#005ca9", "#fff", "CX"], "Mercado Pago": ["#00b1ea", "#fff", "MP"], "PicPay": ["#21c25e", "#fff", "P"],
};
export function avatarInstituicao(nome, pequeno = false) {
  const [fundo, cor, sigla] = COR_INSTITUICAO[nome] || ["var(--superficie-3)", "var(--texto)", (nome || "?").slice(0, 2)];
  return `<span class="avatar${pequeno ? " pequeno" : ""}" style="background:${fundo};color:${cor}">${esc(sigla)}</span>`;
}

const COR_MARCA = {
  "Claude": "#d97757", "OpenAI": "#10a37f", "Netflix": "#e50914", "Google One": "#4285f4", "AWS": "#ff9900",
  "Amazon Prime": "#00a8e1", "Wellhub": "#e8345a", "YouTube Premium": "#ff0000", "Spotify": "#1db954", "Max": "#002be7",
  "Crunchyroll": "#f47521", "Meli+": "#ffe600", "Disney+": "#113ccf", "Apple": "#a2aaad", "Globoplay": "#fb0234",
};
export function avatarMarca(nome) {
  const cor = COR_MARCA[nome];
  const sigla = (nome || "?").replace(/[^A-Za-zÀ-ú0-9 ]/g, "").trim().slice(0, 1).toUpperCase() || "?";
  if (!cor) return `<span class="avatar">${esc(sigla)}</span>`;
  const texto = ["#ffe600", "#a2aaad", "#ff9900"].includes(cor) ? "#1a1a1a" : "#fff";
  return `<span class="avatar" style="background:${cor};color:${texto}">${esc(sigla)}</span>`;
}

export const NATUREZAS = {
  despesa: "Despesa",
  receita: "Receita",
  rendimento: "Rendimento (juros, dividendos)",
  investimento: "Investimento (aplicação/resgate)",
  transferencia_propria: "Transferência entre minhas contas",
  pagamento_fatura: "Pagamento de fatura do cartão",
  emprestimo: "Empréstimo a terceiros (emprestei / recebi de volta)",
};
export const NATUREZAS_CURTAS = {
  despesa: "Despesa", receita: "Receita", rendimento: "Rendimento", investimento: "Investimento",
  transferencia_propria: "Entre contas", pagamento_fatura: "Pag. fatura", emprestimo: "Empréstimo",
};
