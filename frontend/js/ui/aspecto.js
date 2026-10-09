/* Aspecto de la interfaz: «Texto grande» y «Alto contraste».
 *
 * Cada opción es una clase en <html> (las reglas están en styles.css) y se recuerda como el interruptor de voz.
 * Hay interruptores en la cabecera y en el login (marcados con data-aspecto) y van sincronizados.
 * js/aspecto_previo.js aplica lo mismo antes de pintar: si cambias una clave aquí, cámbiala también allí. */
import { guardarPreferencia, leerPreferencia } from "../dispositivos/preferencias.js";

const OPCIONES = { "texto-grande": "textoGrande", "alto-contraste": "altoContraste" };

/** Sin elección guardada, el alto contraste sigue al sistema (prefers-contrast: more). */
function porDefecto(clase) {
  const masContraste = window.matchMedia?.("(prefers-contrast: more)").matches;
  return clase === "alto-contraste" && masContraste ? "1" : "0";
}

export function iniciarAspecto() {
  const html = document.documentElement;
  for (const [clase, clave] of Object.entries(OPCIONES)) {
    const interruptores = document.querySelectorAll(`input[data-aspecto="${clase}"]`);
    const aplicar = (activo) => {
      html.classList.toggle(clase, activo);
      for (const interruptor of interruptores) interruptor.checked = activo;
    };
    aplicar(leerPreferencia(clave, porDefecto(clase)) === "1");
    for (const interruptor of interruptores) {
      interruptor.addEventListener("change", () => {
        aplicar(interruptor.checked);
        guardarPreferencia(clave, interruptor.checked ? "1" : "0");
      });
    }
  }
}
