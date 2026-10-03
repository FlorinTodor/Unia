/* Utilidades de DOM y de renderizado de texto. */

export function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto;
  return div.innerHTML;
}

// Markdown completo (tablas, listas...) saneado; con fallback mínimo si no cargaron las CDN.
export function renderizarMarkdown(texto) {
  if (window.marked && window.DOMPurify) {
    return DOMPurify.sanitize(marked.parse(texto, { breaks: true }));
  }
  return escaparHtml(texto)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}
