/* Móvil simulado: donde llegan los SMS con el código OTP. Es un canal aparte del chat, como en la vida real.
 *
 * Accesibilidad: cada SMS NUEVO se anuncia una sola vez a los lectores de pantalla, puede leerse en voz alta
 * (cifra a cifra) y hace vibrar el dispositivo y parpadear el icono para quien no oye. */
import { mensajesDelMovil } from "../api/operaciones.js";
import { leerSms } from "../dispositivos/altavoz.js";
import { guardarPreferencia, leerPreferencia } from "../dispositivos/preferencias.js";

const REFRESCO_MS = 3000;
const clave = (m) => `${m.hora}|${m.texto}`;

export class Movil {
  #panel = document.getElementById("movil");
  #lista = document.getElementById("movil-mensajes");
  #boton = document.getElementById("btn-movil");
  #anuncio = document.getElementById("movil-anuncio");
  #leer = document.getElementById("movil-leer");
  #temporizador = null;
  #vistos = new Set(); // SMS que el cliente ya conoce: no se vuelven a anunciar

  constructor() {
    this.#boton.addEventListener("click", () => (this.#panel.hidden ? this.abrir() : this.cerrar()));
    document.getElementById("btn-cerrar-movil").addEventListener("click", () => this.cerrar());
    this.#leer.checked = leerPreferencia("leerSms", "0") === "1";
    this.#leer.addEventListener("change", () => guardarPreferencia("leerSms", this.#leer.checked ? "1" : "0"));
  }

  get leeSmsEnVozAlta() {
    return this.#leer.checked;
  }

  /** Al iniciar sesión: los SMS que ya hubiera no se anuncian como si acabaran de llegar. */
  async sembrar() {
    try {
      this.#vistos = new Set((await mensajesDelMovil()).map(clave));
    } catch {
      this.#vistos = new Set();
    }
  }

  async abrir() {
    this.#panel.hidden = false;
    this.#boton.classList.remove("nuevo");
    await this.refrescar();
    clearInterval(this.#temporizador);
    this.#temporizador = setInterval(() => this.refrescar(), REFRESCO_MS);
  }

  cerrar() {
    this.#panel.hidden = true;
    clearInterval(this.#temporizador);
  }

  /** Al cerrar sesión se vacía todo: el siguiente cliente no debe ver los SMS del anterior. */
  reiniciar() {
    this.cerrar();
    this.#lista.replaceChildren();
    this.#vistos = new Set();
    this.#anuncio.textContent = "";
    this.#boton.classList.remove("nuevo");
  }

  async refrescar() {
    let mensajes;
    try {
      mensajes = await mensajesDelMovil();
    } catch {
      return;
    }
    const nuevos = mensajes.filter((m) => !this.#vistos.has(clave(m)));
    if (!nuevos.length && this.#lista.childElementCount) return; // nada cambió: no se toca el DOM (evita re-lecturas)
    this.#pintar(mensajes);
    // llegan del más reciente al más antiguo: se anuncia primero el último SMS
    for (const m of nuevos.reverse()) this.#avisar(m);
    this.#vistos = new Set(mensajes.map(clave));
  }

  #pintar(mensajes) {
    this.#lista.replaceChildren();
    if (!mensajes.length) {
      const vacio = document.createElement("p");
      vacio.className = "texto-mini";
      vacio.textContent = "Sin mensajes.";
      this.#lista.appendChild(vacio);
    }
    for (const m of mensajes) {
      const sms = document.createElement("div");
      sms.className = "sms";
      const cabecera = document.createElement("div");
      cabecera.className = "sms-cabecera";
      cabecera.textContent = `${m.remitente} · ${m.hora}`;
      const cuerpo = document.createElement("div");
      cuerpo.textContent = m.texto;
      sms.append(cabecera, cuerpo);
      this.#lista.appendChild(sms);
    }
  }

  #avisar(mensaje) {
    this.#anuncio.textContent = ""; // para lectores de pantalla: un único anuncio por SMS
    setTimeout(() => (this.#anuncio.textContent = `Nuevo SMS de ${mensaje.remitente}. ${mensaje.texto}`), 50);
    navigator.vibrate?.([200, 100, 200]); // quien no oye lo nota en la mano (móviles)
    if (this.#leer.checked) leerSms(`Nuevo mensaje de ${mensaje.remitente}. ${mensaje.texto}`);
  }

  /** Llega un SMS nuevo: se abre el móvil para que el cliente lea el código. */
  avisarMensajeNuevo() {
    if (this.#panel.hidden) this.#boton.classList.add("nuevo");
    return this.abrir();
  }
}
