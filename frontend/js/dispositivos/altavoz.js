/* Salida de voz: voces del navegador si existen y, si no, la voz neuronal del servidor (Piper). */
import { sintetizar } from "../api/voz.js";
import { leerPreferencia } from "./preferencias.js";

/* UNA sola cola de locuciones: nunca suenan dos a la vez (antes el SMS del código y la respuesta del asistente se pisaban).
 * Prioridad: un SMS (alta) corta lo que esté sonando y pasa por delante; las locuciones normales esperan su turno.
 * Cualquier acción del usuario (hablar, enviar) llama a pararVoz(), que corta y vacía la cola. */
const PRIORIDAD_ALTA = 1;
let cola = []; // locuciones pendientes: { texto, prioridad }
let sonando = false;
let cortarActual = null; // corta la locución en curso y resuelve su promesa
let generacion = 0; // invalida bucles y síntesis en vuelo tras pararVoz()

export function pararVoz() {
  generacion++;
  cola = [];
  cortarActual?.();
}

async function vaciarCola() {
  if (sonando) return;
  sonando = true;
  const miGeneracion = generacion;
  try {
    while (cola.length && miGeneracion === generacion) await reproducir(cola.shift().texto, miGeneracion);
  } finally {
    // si hubo pararVoz() entre medias, el bucle nuevo (si lo hay) lo arrancó otro llamante
    sonando = false;
    if (cola.length && miGeneracion !== generacion) vaciarCola();
  }
}

/** Reproduce una locución y resuelve cuando termina o se corta. */
function reproducir(limpio, miGeneracion) {
  return new Promise(async (resolver) => {
    let audio = null;
    let cortada = false;
    const terminar = () => {
      cortarActual = null;
      resolver();
    };
    cortarActual = () => {
      cortada = true;
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      audio?.pause();
      terminar();
    };
    const motor = leerPreferencia("motorVoz", "auto"); // auto | navegador | servidor
    const vozEs =
      motor !== "servidor" && "speechSynthesis" in window && speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
    if (vozEs) {
      const locucion = new SpeechSynthesisUtterance(limpio);
      locucion.lang = "es-ES";
      locucion.rate = 1.05;
      locucion.voice = vozEs;
      locucion.onend = locucion.onerror = terminar;
      speechSynthesis.speak(locucion);
      return;
    }
    if (motor === "navegador") return terminar();
    // Brave/Chromium en Linux no trae voces: se usa el TTS del servidor
    let blob = null;
    try {
      blob = await sintetizar(limpio);
    } catch {}
    if (!blob || cortada || miGeneracion !== generacion) return terminar(); // cortado mientras se sintetizaba
    audio = new Audio(URL.createObjectURL(blob));
    audio.onended = audio.onerror = terminar;
    audio.play().catch(terminar);
  });
}

// la voz no lee tablas ni código: solo el texto natural (la conclusión)
function textoHablable(texto) {
  return texto
    .split("\n")
    .filter((linea) => !linea.trim().startsWith("|") && !linea.trim().startsWith("```"))
    .join(" ")
    .replace(/[*`#_|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Encola una locución. Con prioridad alta corta la que suena y pasa por delante (lo normal espera). */
export function leerEnVozAlta(texto, { prioridad = 0 } = {}) {
  const limpio = textoHablable(texto);
  if (!limpio) return;
  if (prioridad >= PRIORIDAD_ALTA) {
    cola.unshift({ texto: limpio, prioridad });
    cortarActual?.();
  } else {
    cola.push({ texto: limpio, prioridad });
  }
  vaciarCola();
}

// algunos navegadores cargan las voces en diferido
if ("speechSynthesis" in window) speechSynthesis.getVoices();

/** Lee un SMS en voz alta; los códigos de 6 dígitos se dicen cifra a cifra («5, 8, 5, 9, 2, 1») para poder anotarlos. */
export function leerSms(texto) {
  const conCifras = texto.replace(/\b\d{6}\b/g, (codigo) => codigo.split("").join(", "));
  return leerEnVozAlta(conCifras, { prioridad: PRIORIDAD_ALTA });
}
