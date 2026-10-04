/* Preguntas rápidas sobre el cuadro de texto: ayudan a empezar y sirven a quien no quiere escribir. */
import { icono } from "./iconos.js";

const SUGERENCIAS = [
  { icono: "cartera", texto: "¿Cuánto tengo?" },
  { icono: "lista", texto: "Mis últimos movimientos" },
  { icono: "grafico", texto: "Gráfico de mis gastos por categoría" },
  { icono: "carrito", texto: "¿Cuánto gasté en supermercados este mes?" },
  { icono: "envio", texto: "Quiero enviar un Bizum" },
  { icono: "tarjeta", texto: "Mis tarjetas" },
];

export class Sugerencias {
  #contenedor = document.getElementById("sugerencias");
  #botones = [];

  /** @param alElegir (texto) => void */
  constructor(alElegir) {
    for (const s of SUGERENCIAS) {
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "sugerencia";
      boton.append(icono(s.icono, 16), document.createTextNode(s.texto));
      boton.addEventListener("click", () => alElegir(s.texto));
      this.#contenedor.appendChild(boton);
      this.#botones.push(boton);
    }
  }

  /** Mientras el asistente responde no se pueden lanzar más preguntas. */
  deshabilitar(si) {
    for (const b of this.#botones) b.disabled = si;
  }
}
