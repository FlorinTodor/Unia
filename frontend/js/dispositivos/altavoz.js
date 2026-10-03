/* Salida de voz: voces del navegador si existen y, si no, la voz neuronal del servidor (Piper). */
import { sintetizar } from "../api/voz.js";
import { leerPreferencia } from "./preferencias.js";

let audioServidor = null;

export function pararVoz() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (audioServidor) {
    audioServidor.pause();
    audioServidor = null;
  }
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

export async function leerEnVozAlta(texto) {
  pararVoz();
  const limpio = textoHablable(texto);
  if (!limpio) return;

  const motor = leerPreferencia("motorVoz", "auto"); // auto | navegador | servidor
  const vozEs =
    motor !== "servidor" && "speechSynthesis" in window && speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
  if (vozEs) {
    const locucion = new SpeechSynthesisUtterance(limpio);
    locucion.lang = "es-ES";
    locucion.rate = 1.05;
    locucion.voice = vozEs;
    speechSynthesis.speak(locucion);
    return;
  }
  if (motor === "navegador") return;

  // Brave/Chromium en Linux no trae voces: se usa el TTS del servidor
  const audio = await sintetizar(limpio);
  if (audio) {
    audioServidor = new Audio(URL.createObjectURL(audio));
    audioServidor.play();
  }
}

// algunos navegadores cargan las voces en diferido
if ("speechSynthesis" in window) speechSynthesis.getVoices();

/** Lee un SMS en voz alta; los códigos de 6 dígitos se dicen cifra a cifra («5, 8, 5, 9, 2, 1») para poder anotarlos. */
export function leerSms(texto) {
  const conCifras = texto.replace(/\b\d{6}\b/g, (codigo) => codigo.split("").join(", "));
  return leerEnVozAlta(conCifras);
}
