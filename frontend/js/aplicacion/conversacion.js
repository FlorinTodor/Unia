/* Caso de uso del chat: envía un mensaje y traduce cada evento del servidor en cambios de la vista. */
import { enviarMensaje } from "../api/chat.js";

export class Conversacion {
  #sessionId = crypto.randomUUID();
  #ocupada = false;

  /**
   * @param vista          VistaChat
   * @param hablar         (texto) => void — lee la respuesta en voz alta si el usuario lo activó
   * @param alOperacion    (datos) => void — llega una operación por confirmar (se abre el móvil con el código)
   * @param alResolverOperacion () => void — la operación terminó (confirmada, cancelada...): refresca el saldo, etc.
   * @param alUso          ({tokens_turno, tokens_hoy, limite_dia}) => void — gasto de tokens al terminar la consulta
   */
  constructor(vista, hablar, { alOperacion = () => {}, alResolverOperacion = () => {}, alUso = () => {} } = {}) {
    this.vista = vista;
    this.hablar = hablar;
    this.alOperacion = alOperacion;
    this.alResolverOperacion = alResolverOperacion;
    this.alUso = alUso;
  }

  /** Nueva sesión de chat (al cambiar de usuario no se arrastra nada de la anterior). */
  reiniciar() {
    this.#sessionId = crypto.randomUUID();
    this.#ocupada = false;
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
        } else if (tipo === "uso") {
          this.alUso(dato);
        } else if (tipo === "operacion") {
          vista.operacion(dato, this.alResolverOperacion);
          this.alOperacion(dato);
        } else if (tipo === "fin") {
          quitarEstados();
          const contenido = dato || acumulado;
          if (burbuja || contenido) {
            burbuja ??= vista.burbujaEnStreaming();
            burbuja.classList.remove("cursor-escribiendo");
            vista.pintarTexto(burbuja, contenido);
          }
          if (contenido) {
            vista.anunciar(contenido);
            this.hablar(contenido);
          }
        } else if (tipo === "error") {
          quitarEstados();
          burbuja ??= vista.burbujaEnStreaming();
          burbuja.classList.remove("cursor-escribiendo");
          vista.pintarTexto(burbuja, dato, { error: true });
          vista.anunciar(`Error. ${dato}`);
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
