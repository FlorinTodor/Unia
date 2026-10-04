/* Tarjeta bancaria visual: marca, tipo, «•••• 4821» y estado (ACTIVA / BLOQUEADA) con icono y texto, no solo color.
 *
 * El botón Bloquear/Desbloquear NO ejecuta nada: pide al chat la frase «bloquea mi tarjeta terminada en 4821»
 * como si la hubiera escrito el usuario, así que pasa por el flujo normal (agente, auditoría, OTP en el desbloqueo). */
import { icono } from "./iconos.js";

const FORMATO_FECHA = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

// quién atiende el botón de cada tarjeta ya pintada (para repintarla sin perderlo)
const peticiones = new WeakMap();

/** Clave estable para localizar la tarjeta en pantalla al refrescarla. */
export const claveTarjeta = (t) => `${t.marca}|${t.tipo}|${t.ultimos4}`;

function fechaLegible(iso) {
  const fecha = new Date(iso);
  return Number.isNaN(fecha.getTime()) ? "" : FORMATO_FECHA.format(fecha);
}

/** Texto para lectores de pantalla (también el del anuncio al cambiar de estado). */
export function describirTarjeta(t) {
  const bloqueo = t.estado === "bloqueada" && t.bloqueada_el && fechaLegible(t.bloqueada_el) ? `, desde el ${fechaLegible(t.bloqueada_el)}` : "";
  return `Tarjeta ${t.marca} de ${t.tipo} terminada en ${t.ultimos4}, ${t.estado === "bloqueada" ? "bloqueada" : "activa"}${bloqueo}`;
}

function pintar(el, t, alPedir) {
  const bloqueada = t.estado === "bloqueada";
  el.className = `tarjeta-banco ${bloqueada ? "bloqueada" : "activa"}`;
  el.dataset.clave = claveTarjeta(t);
  el.dataset.estado = bloqueada ? "bloqueada" : "activa";
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", describirTarjeta(t));

  const cabecera = document.createElement("div");
  cabecera.className = "tb-cabecera";
  const marca = document.createElement("span");
  marca.className = "tb-marca";
  marca.textContent = t.marca;
  const tipo = document.createElement("span");
  tipo.className = "tb-tipo";
  tipo.textContent = t.tipo;
  cabecera.append(marca, tipo);

  const numero = document.createElement("div");
  numero.className = "tb-numero";
  numero.setAttribute("aria-hidden", "true"); // el aria-label del grupo ya lo dice con palabras
  numero.textContent = `•••• ${t.ultimos4}`;

  const estado = document.createElement("span");
  estado.className = "tb-estado";
  estado.append(icono(bloqueada ? "candado" : "check", 16), document.createTextNode(bloqueada ? "BLOQUEADA" : "ACTIVA"));
  const situacion = document.createElement("div"); // la píldora y, debajo, desde cuándo
  situacion.className = "tb-situacion";
  situacion.appendChild(estado);
  if (bloqueada && t.bloqueada_el && fechaLegible(t.bloqueada_el)) {
    const desde = document.createElement("span");
    desde.className = "tb-desde";
    desde.textContent = `Bloqueada el ${fechaLegible(t.bloqueada_el)}`;
    situacion.appendChild(desde);
  }
  const pie = document.createElement("div");
  pie.className = "tb-pie";
  pie.appendChild(situacion);

  el.replaceChildren(cabecera, numero, pie);

  if (alPedir) {
    const accion = document.createElement("button");
    accion.type = "button";
    accion.className = "tb-accion";
    accion.textContent = bloqueada ? "Desbloquear" : "Bloquear";
    if (el.closest(".chat.ocupado")) accion.setAttribute("aria-disabled", "true"); // repintada en pleno turno
    accion.setAttribute("aria-label", `${bloqueada ? "Desbloquear" : "Bloquear"} la tarjeta ${t.marca} ${t.tipo} terminada en ${t.ultimos4}. Se lo pide al asistente.`);
    accion.addEventListener("click", () => accion.getAttribute("aria-disabled") !== "true" && alPedir(`${bloqueada ? "desbloquea" : "bloquea"} mi tarjeta terminada en ${t.ultimos4}`));
    pie.appendChild(accion);
  }
}

/**
 * @param t       {marca, tipo, ultimos4, estado, bloqueada_el}
 * @param alPedir (texto) => void — manda el texto al chat como si lo escribiera el usuario
 */
export function crearTarjetaBancaria(t, alPedir) {
  const el = document.createElement("div");
  peticiones.set(el, alPedir);
  pintar(el, t, alPedir);
  return el;
}

/** Repinta una tarjeta ya en pantalla con su nuevo estado. */
export function actualizarTarjetaBancaria(el, t) {
  pintar(el, t, peticiones.get(el));
}
