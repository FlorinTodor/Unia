/* Caso de uso del chat: envía un mensaje y traduce cada evento del servidor en cambios de la vista. */
import { enviarMensaje } from "../api/chat.js";

export class Conversacion {
  #sessionId = crypto.randomUUID();
  #ocupada = false;

  /**
   * @param vista    VistaChat
   * @param hablar   (texto) => void — lee la respuesta en voz alta si el usuario lo activó
   */
  constructor(vista, hablar) {
    this.vista = vista;
    this.hablar = hablar;
  }

  get ocupada() {
    return this.#ocupada;
  }

  async enviar(texto) {
    if (!texto.trim() || this.#ocupada) return;
    this.#ocupada = true;
    const { vista } = this;
    vista.mensajeUsuario(texto);

    let burbuja = null;
    let acumulado = "";
    const estados = [];
    const quitarEstados = () => estados.splice(0).forEach((e) => e.remove());

    try {
      for await (const { tipo, dato, etiqueta } of enviarMensaje(this.#sessionId, texto)) {
        if (tipo === "delta") {
          burbuja ??= vista.burbujaEnStreaming();
          acumulado += dato;
          vista.pintarTexto(burbuja, acumulado);
        } else if (tipo === "herramienta") {
          estados.push(vista.estadoHerramienta(etiqueta || dato));
        } else if (tipo === "aviso") {
          vista.aviso(dato);
        } else if (tipo === "grafico") {
          vista.grafico(dato);
        } else if (tipo === "fin") {
          quitarEstados();
          const contenido = dato || acumulado;
          if (burbuja || contenido) {
            burbuja ??= vista.burbujaEnStreaming();
            burbuja.classList.remove("cursor-escribiendo");
            vista.pintarTexto(burbuja, contenido);
          }
          if (contenido) this.hablar(contenido);
        } else if (tipo === "error") {
          quitarEstados();
          burbuja ??= vista.burbujaEnStreaming();
          burbuja.classList.remove("cursor-escribiendo");
          vista.pintarTexto(burbuja, dato, { error: true });
        }
      }
    } catch (e) {
      if (burbuja) vista.pintarTexto(burbuja, e.message, { error: true });
      else vista.mensajeError(e.message);
    } finally {
      burbuja?.classList.remove("cursor-escribiendo");
      this.#ocupada = false;
      vista.alFinal();
    }
  }
}
