// Cálculos sobre as transações já classificadas pelo backend.
import { diasNoMes, mesDe, somarMeses } from "./util.js";

export const INTERNAS = new Set(["investimento", "transferencia_propria", "pagamento_fatura", "emprestimo"]);

// Valor com sinal "de negócio": despesa positiva (estorno negativo), receita positiva.
export function impacto(t) {
  if (t.natureza === "despesa") return t.entrada ? -t.valor : t.valor;
  if (t.natureza === "receita" || t.natureza === "rendimento") return t.entrada ? t.valor : -t.valor;
  return 0;
}

export class Base {
  constructor(d) {
    this.d = d;
    this.hoje = d.hoje;
    this.mesAtual = mesDe(d.hoje);
    this.contas = new Map(d.contas.map((c) => [c.id, c]));
    this.categorias = d.categorias;
    this.visiveis = d.transacoes.filter((t) => !t.oculto);
    const meses = d.transacoes.map((t) => mesDe(t.data)).filter((m) => m <= this.mesAtual);
    this.primeiroMes = meses.length ? meses.reduce((a, b) => (a < b ? a : b)) : this.mesAtual;
  }

  categoria(id) { return this.categorias[id] || { nome: "Outros", grupo: "99999999" }; }
  grupoDe(id) { return this.categoria(id).grupo; }
  nomeGrupo(grupoId) { return (this.categorias[grupoId] || { nome: "Outros" }).nome; }
  conta(id) { return this.contas.get(id) || { nome: "?", instituicao: "?" }; }

  /** Transações do mês. Por padrão só as já realizadas (data até hoje). */
  doMes(mes, { futuras = false, ocultas = false } = {}) {
    const base = ocultas ? this.d.transacoes : this.visiveis;
    return base.filter((t) => mesDe(t.data) === mes && (futuras || t.data <= this.hoje));
  }

  totais(lista) {
    const r = { despesas: 0, receitas: 0, rendimentos: 0, aplicado: 0, resgatado: 0, emprestado: 0, devolvido: 0 };
    for (const t of lista) {
      if (t.natureza === "despesa") r.despesas += impacto(t);
      else if (t.natureza === "receita") r.receitas += impacto(t);
      else if (t.natureza === "rendimento") r.rendimentos += impacto(t);
      else if (t.natureza === "investimento") t.entrada ? (r.resgatado += t.valor) : (r.aplicado += t.valor);
      else if (t.natureza === "emprestimo") t.entrada ? (r.devolvido += t.valor) : (r.emprestado += t.valor);
    }
    r.resultado = r.receitas + r.rendimentos - r.despesas;
    r.investidoLiquido = r.aplicado - r.resgatado;
    return r;
  }

  /** Despesa acumulada por dia (índice 0 = dia 1). Para o mês corrente, para no dia de hoje. */
  acumulado(mes) {
    const n = diasNoMes(mes);
    const porDia = new Array(n).fill(0);
    for (const t of this.doMes(mes)) if (t.natureza === "despesa") porDia[Number(t.data.slice(8, 10)) - 1] += impacto(t);
    const limite = mes === this.mesAtual ? Number(this.hoje.slice(8, 10)) : n;
    let soma = 0;
    return porDia.slice(0, limite).map((v) => (soma += v));
  }

  /** Despesa por dia do mês: [{dia, total, txs}] */
  porDia(mes) {
    const n = diasNoMes(mes);
    const dias = Array.from({ length: n }, (_, i) => ({ dia: i + 1, total: 0, txs: [] }));
    for (const t of this.doMes(mes)) {
      if (t.natureza !== "despesa") continue;
      const d = dias[Number(t.data.slice(8, 10)) - 1];
      d.total += impacto(t);
      d.txs.push(t);
    }
    return dias;
  }

  /** Despesas por categoria e por grupo num mês. */
  porCategoria(mes) {
    const cats = new Map();
    const grupos = new Map();
    for (const t of this.doMes(mes)) {
      if (t.natureza !== "despesa") continue;
      const v = impacto(t);
      cats.set(t.categoriaId, (cats.get(t.categoriaId) || 0) + v);
      const g = this.grupoDe(t.categoriaId);
      grupos.set(g, (grupos.get(g) || 0) + v);
    }
    return { cats, grupos };
  }

  /** Média mensal de despesa por categoria nos N meses fechados anteriores a `mes`. */
  mediaCategorias(mes, n = 6) {
    const soma = new Map();
    const meses = Array.from({ length: n }, (_, i) => somarMeses(mes, -(i + 1))).filter((m) => m >= this.primeiroMes);
    for (const m of meses) for (const [c, v] of this.porCategoria(m).cats) soma.set(c, (soma.get(c) || 0) + v);
    const media = new Map();
    for (const [c, v] of soma) media.set(c, v / (meses.length || 1));
    return { media, meses: meses.length };
  }

  /** Mesmo período do mês anterior (até o mesmo dia), para comparar o mês corrente de forma justa. */
  mesmoPeriodoAnterior(mes) {
    const anterior = somarMeses(mes, -1);
    if (mes !== this.mesAtual) return { mes: anterior, despesas: this.totais(this.doMes(anterior)).despesas, completo: true };
    const dia = Number(this.hoje.slice(8, 10));
    const lista = this.doMes(anterior).filter((t) => Number(t.data.slice(8, 10)) <= dia);
    return { mes: anterior, despesas: this.totais(lista).despesas, completo: false, dia };
  }
}
