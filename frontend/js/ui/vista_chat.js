/* Vista del chat: burbujas, estados de herramienta, avisos y tarjetas de gráfico. */
import { escaparHtml, renderizarMarkdown } from "./dom.js";
import { crearTarjetaOperacion } from "./tarjeta_operacion.js";

export class VistaChat {
  #chat;

  constructor(contenedor) {
    this.#chat = contenedor;
  }

  #scrollAlFinal() {
    this.#chat.scrollTop = this.#chat.scrollHeight;
  }

  /** Crea una burbuja vacía (`usuario` | `asistente`) y devuelve su elemento. */
  crearBurbuja(rol) {
    const contenedor = document.createElement("div");
    contenedor.className = `mensaje ${rol}`;
    const burbuja = document.createElement("div");
    burbuja.className = "burbuja";
    contenedor.appendChild(burbuja);
    this.#chat.appendChild(contenedor);
    this.#scrollAlFinal();
    return burbuja;
  }

  mensajeUsuario(texto) {
    this.crearBurbuja("usuario").textContent = texto;
  }

  /** Burbuja del asistente que se va rellenando con el streaming. */
  burbujaEnStreaming() {
    const burbuja = this.crearBurbuja("asistente");
    burbuja.classList.add("cursor-escribiendo");
    return burbuja;
  }

  pintarTexto(burbuja, markdown, { error = false } = {}) {
    burbuja.innerHTML = (error ? "⚠️ " : "") + renderizarMarkdown(markdown);
    this.#scrollAlFinal();
  }

  mensajeError(texto) {
    this.crearBurbuja("asistente").innerHTML = "⚠️ " + escaparHtml(texto);
  }

  /** Estado efímero «⚙️ Consultando saldo…». Devuelve el elemento para poder quitarlo. */
  estadoHerramienta(etiqueta) {
    return this.#nota(`⚙️ ${etiqueta}`);
  }

  aviso(texto) {
    this.#nota(`ℹ️ ${texto}`);
  }

  #nota(texto) {
    const div = document.createElement("div");
    div.className = "estado-herramienta";
    div.textContent = texto;
    this.#chat.appendChild(div);
    this.#scrollAlFinal();
    return div;
  }

  grafico({ titulo, config }) {
    const tarjeta = document.createElement("div");
    tarjeta.className = "tarjeta-grafico";
    const h3 = document.createElement("h3");
    h3.textContent = `📊 ${titulo}`;
    const lienzo = document.createElement("div");
    lienzo.className = "lienzo";
    const canvas = document.createElement("canvas");
    lienzo.appendChild(canvas);
    tarjeta.append(h3, lienzo);
    this.#chat.appendChild(tarjeta);

    try {
      config.options = Object.assign({ responsive: true, maintainAspectRatio: false }, config.options);
      new Chart(canvas, config);
    } catch (e) {
      lienzo.textContent = "No se pudo renderizar el gráfico: " + e.message;
    }
    this.#scrollAlFinal();
  }

  /** Tarjeta para confirmar una operación con el código del móvil (o con la huella). */
  operacion(datos, alTerminar) {
    const tarjeta = crearTarjetaOperacion(datos, alTerminar);
    this.#chat.appendChild(tarjeta);
    this.#scrollAlFinal();
    // el foco va al campo del código: con lector de pantalla se oye el resumen y se puede teclear sin buscar nada
    requestAnimationFrame(() => tarjeta.querySelector("input")?.focus());
  }

  /** Texto para lectores de pantalla (región `aria-live`): se anuncia la respuesta ya terminada, no cada fragmento. */
  anunciar(texto) {
    const region = document.getElementById("anuncios");
    if (!region) return;
    region.textContent = "";
    // el cambio de contenido en dos pasos asegura que se vuelva a leer aunque el texto se repita
    setTimeout(() => (region.textContent = texto.replace(/[*`#_|]/g, " ").replace(/\s+/g, " ").trim()), 50);
  }

  saludo(nombre) {
    this.#chat.replaceChildren();
    this.crearBurbuja("asistente").innerHTML =
      `¡Hola, ${escaparHtml(nombre.split(' ')[0])}! 👋 Soy tu asistente financiero. Puedes <b>escribirme o hablarme</b>: ` +
      "consulta tu saldo, tus gastos («¿cuánto gasté en restaurantes en junio?»), " +
      "envía un Bizum o pídeme un gráfico de tus finanzas.";
  }

  limpiar() {
    this.#chat.replaceChildren();
  }

  alFinal() {
    this.#scrollAlFinal();
  }
}
