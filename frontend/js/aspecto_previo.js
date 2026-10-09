/* Aplica «Texto grande» y «Alto contraste» antes de que se pinte la página, para que no parpadee.
 * Es un script clásico (no módulo) cargado en <head>: los módulos se ejecutan después de pintar y la CSP no
 * admite código en línea. Las claves y el valor por defecto deben coincidir con js/ui/aspecto.js. */
(function () {
  try {
    var html = document.documentElement;
    var masContraste = window.matchMedia && window.matchMedia("(prefers-contrast: more)").matches;
    if (localStorage.getItem("textoGrande") === "1") html.classList.add("texto-grande");
    var contraste = localStorage.getItem("altoContraste");
    if (contraste === "1" || (contraste === null && masContraste)) html.classList.add("alto-contraste");
  } catch (e) {
    // localStorage bloqueado: se queda el aspecto normal; js/ui/aspecto.js lo vuelve a intentar
  }
})();
