// Modo privado: borra todo valor em reais da tela sem mexer no layout.
// Cada "R$ ..." encontrado vira <span class="dinheiro">; o CSS só borra quando <body> tem a classe "privado".

const CHAVE = "openbalance.privado";
const RE_DINHEIRO = /[−+-]?\s?R\$\s?[\d.,]+(?:\s?(?:k|mi)\b)?/g;

function marcar(raiz) {
  const caminhante = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, {
    acceptNode: (no) => (no.nodeValue.includes("R$") && !no.parentElement?.closest(".dinheiro, script, style, option, textarea")
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const nos = [];
  while (caminhante.nextNode()) nos.push(caminhante.currentNode);
  for (const no of nos) {
    const pai = no.parentElement;
    // Dentro de SVG não dá para criar <span>: marca o próprio <text>.
    if (pai.namespaceURI === "http://www.w3.org/2000/svg") { pai.classList.add("dinheiro"); continue; }
    const texto = no.nodeValue;
    const fragmento = document.createDocumentFragment();
    let ultimo = 0;
    for (const m of texto.matchAll(RE_DINHEIRO)) {
      fragmento.append(texto.slice(ultimo, m.index));
      const span = document.createElement("span");
      span.className = "dinheiro";
      span.textContent = m[0];
      fragmento.append(span);
      ultimo = m.index + m[0].length;
    }
    if (ultimo === 0) continue;
    fragmento.append(texto.slice(ultimo));
    no.replaceWith(fragmento);
  }
}

function ler() {
  try { return localStorage.getItem(CHAVE) === "1"; } catch { return false; }
}

function gravar(valor) {
  try { localStorage.setItem(CHAVE, valor ? "1" : "0"); } catch { /* sem armazenamento: vale só nesta aba */ }
}

function aplicar(ativo, botao) {
  document.body.classList.toggle("privado", ativo);
  botao.setAttribute("aria-pressed", String(ativo));
  botao.title = ativo ? "Mostrar valores" : "Ocultar valores";
  botao.setAttribute("aria-label", botao.title);
}

export function iniciarPrivacidade(botao) {
  aplicar(ler(), botao);
  botao.addEventListener("click", () => {
    const ativo = !document.body.classList.contains("privado");
    aplicar(ativo, botao);
    gravar(ativo);
  });
  marcar(document.body);
  // Marca tudo que for desenhado depois (telas, gráficos, dica do mouse, modal).
  new MutationObserver((mudancas) => {
    for (const m of mudancas) for (const no of m.addedNodes) {
      if (no.nodeType === Node.ELEMENT_NODE) marcar(no);
      else if (no.nodeType === Node.TEXT_NODE && no.parentElement) marcar(no.parentElement);
    }
  }).observe(document.body, { childList: true, subtree: true });
}
