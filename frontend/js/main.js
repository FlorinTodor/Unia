/* Raíz de composición del frontend: conecta vistas, casos de uso y adaptadores. */
import { obtenerEstado } from "./api/estado.js";
import { transcribir } from "./api/voz.js";
import { Conversacion } from "./aplicacion/conversacion.js";
import { leerEnVozAlta, pararVoz } from "./dispositivos/altavoz.js";
import { Microfono } from "./dispositivos/microfono.js";
import { pintarEstado } from "./ui/cabecera.js";
import { iniciarPanelAjustes } from "./ui/panel_ajustes.js";
import { VistaChat } from "./ui/vista_chat.js";

const $ = (id) => document.getElementById(id);
const formulario = $("formulario");
const entrada = $("entrada");
const btnMic = $("btn-mic");
const ttsCheck = $("tts-check");

const vista = new VistaChat($("chat"));
const conversacion = new Conversacion(vista, (texto) => {
  if (ttsCheck.checked) leerEnVozAlta(texto);
});

async function actualizarEstado() {
  try {
    const estado = await obtenerEstado();
    pintarEstado(estado, { infoProveedor: $("info-proveedor"), botonMicrofono: btnMic });
    return estado;
  } catch {
    return null;
  }
}

async function enviar(texto) {
  pararVoz();
  entrada.value = "";
  await conversacion.enviar(texto);
  entrada.focus();
}

formulario.addEventListener("submit", (e) => {
  e.preventDefault();
  enviar(entrada.value);
});

// ------------------------------------------------------------------ voz de entrada

const microfono = new Microfono();

async function alternarGrabacion() {
  if (microfono.grabando) return microfono.parar();
  try {
    await microfono.empezar(async (audio) => {
      btnMic.classList.remove("grabando");
      btnMic.textContent = "🎤";
      entrada.placeholder = "Transcribiendo…";
      try {
        const texto = await transcribir(audio);
        if (texto) {
          entrada.value = texto;
          enviar(texto);
        }
      } catch (e) {
        vista.mensajeError(e.message);
      } finally {
        entrada.placeholder = "Escribe o pulsa el micrófono…";
      }
    });
    btnMic.classList.add("grabando");
    btnMic.textContent = "⏹";
  } catch {
    vista.mensajeError("No se pudo acceder al micrófono. Revisa los permisos del navegador.");
  }
}

btnMic.addEventListener("click", alternarGrabacion);

// ------------------------------------------------------------------ ajustes y arranque

const ajustes = iniciarPanelAjustes({ alCambiar: actualizarEstado, alCerrar: () => entrada.focus() });

// primer arranque sin motor configurado → se abre el asistente de bienvenida
actualizarEstado().then((estado) => {
  if (estado && !estado.configurado) ajustes.abrir();
});
