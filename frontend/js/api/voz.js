/* Adaptador de voz del servidor: transcripción (Whisper) y síntesis (Piper). */
import { comprobarSesion, errorDeRespuesta } from "./http.js";

export async function transcribir(audio) {
  const datos = new FormData();
  datos.append("audio", audio, "grabacion.webm");
  const respuesta = await fetch("/stt", { method: "POST", body: datos });
  comprobarSesion(respuesta);
  if (!respuesta.ok) throw await errorDeRespuesta(respuesta);
  return (await respuesta.json()).texto;
}

/** Devuelve el audio WAV, o null si el servidor no puede sintetizar. */
export async function sintetizar(texto) {
  try {
    const respuesta = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto }),
    });
    return respuesta.ok ? await respuesta.blob() : null;
  } catch {
    return null;
  }
}
