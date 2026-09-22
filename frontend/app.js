/* Frontend del asistente: chat SSE, voz (grabación → Whisper) y gráficos Chart.js. */

const chat = document.getElementById("chat");
const formulario = document.getElementById("formulario");
const entrada = document.getElementById("entrada");
const btnMic = document.getElementById("btn-mic");
const ttsCheck = document.getElementById("tts-check");
const infoProveedor = document.getElementById("info-proveedor");

const sessionId = crypto.randomUUID();
let ocupado = false;

// ------------------------------------------------------------------ utilidades

function scrollAlFinal() {
  chat.scrollTop = chat.scrollHeight;
}

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto;
  return div.innerHTML;
}

// Markdown completo (tablas, listas...) saneado; con fallback mínimo.
function renderizarTexto(texto) {
  if (window.marked && window.DOMPurify) {
    return DOMPurify.sanitize(marked.parse(texto, { breaks: true }));
  }
  return escaparHtml(texto)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function crearBurbuja(rol) {
  const contenedor = document.createElement("div");
  contenedor.className = `mensaje ${rol}`;
  const burbuja = document.createElement("div");
  burbuja.className = "burbuja";
  contenedor.appendChild(burbuja);
  chat.appendChild(contenedor);
  scrollAlFinal();
  return burbuja;
}

function mostrarEstadoHerramienta(nombre) {
  const etiquetas = {
    consultar_saldo: "Consultando saldo…",
    listar_contactos_bizum: "Buscando contactos…",
    transferencia_bizum: "Procesando Bizum…",
    consultar_movimientos: "Analizando tus movimientos…",
    generar_grafico: "Generando gráfico…",
  };
  const div = document.createElement("div");
  div.className = "estado-herramienta";
  div.textContent = `⚙️ ${etiquetas[nombre] || nombre}`;
  chat.appendChild(div);
  scrollAlFinal();
  return div;
}

function renderizarGrafico({ titulo, config }) {
  const tarjeta = document.createElement("div");
  tarjeta.className = "tarjeta-grafico";
  const h3 = document.createElement("h3");
  h3.textContent = `📊 ${titulo}`;
  const lienzo = document.createElement("div");
  lienzo.className = "lienzo";
  const canvas = document.createElement("canvas");
  lienzo.appendChild(canvas);
  tarjeta.append(h3, lienzo);
  chat.appendChild(tarjeta);

  try {
    config.options = Object.assign({ responsive: true, maintainAspectRatio: false }, config.options);
    new Chart(canvas, config);
  } catch (e) {
    lienzo.textContent = "No se pudo renderizar el gráfico: " + e.message;
  }
  scrollAlFinal();
}

let audioTTS = null;

function pararVoz() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (audioTTS) {
    audioTTS.pause();
    audioTTS = null;
  }
}

async function leerEnVozAlta(texto) {
  if (!ttsCheck.checked) return;
  pararVoz();
  // la voz no lee tablas ni código: solo el texto natural (la conclusión)
  const limpio = texto
    .split("\n")
    .filter((linea) => !linea.trim().startsWith("|") && !linea.trim().startsWith("```"))
    .join(" ")
    .replace(/[*`#_|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!limpio) return;

  // motor elegido en ⚙️ Ajustes: auto | navegador | servidor
  let motor = "auto";
  try {
    motor = localStorage.getItem("motorVoz") || "auto";
  } catch {}

  // 1º voces del propio navegador (Windows/Mac/Android las traen de serie)
  const vozEs =
    motor !== "servidor" &&
    "speechSynthesis" in window &&
    speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
  if (vozEs) {
    const locucion = new SpeechSynthesisUtterance(limpio);
    locucion.lang = "es-ES";
    locucion.rate = 1.05;
    locucion.voice = vozEs;
    speechSynthesis.speak(locucion);
    return;
  }
  if (motor === "navegador") return;

  // 2º TTS del servidor (Piper) — Brave/Chromium en Linux no trae voces
  try {
    const r = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto: limpio }),
    });
    if (!r.ok) return;
    audioTTS = new Audio(URL.createObjectURL(await r.blob()));
    audioTTS.play();
  } catch {
    /* sin voz disponible: la respuesta ya está en pantalla */
  }
}

// ------------------------------------------------------------------ chat SSE

async function enviarMensaje(texto) {
  if (!texto.trim() || ocupado) return;
  ocupado = true;
  pararVoz();

  crearBurbuja("usuario").textContent = texto;
  entrada.value = "";

  let burbuja = null;
  let acumulado = "";
  const estados = [];

  try {
    const respuesta = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, mensaje: texto }),
    });
    if (!respuesta.ok) throw new Error(`Error del servidor (${respuesta.status})`);

    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let pendiente = "";

    while (true) {
      const { value, done } = await lector.read();
      if (done) break;
      pendiente += decodificador.decode(value, { stream: true });

      const bloques = pendiente.split("\n\n");
      pendiente = bloques.pop();

      for (const bloque of bloques) {
        const linea = bloque.trim();
        if (!linea.startsWith("data: ")) continue;
        const { tipo, dato } = JSON.parse(linea.slice(6));

        if (tipo === "delta") {
          if (!burbuja) {
            burbuja = crearBurbuja("asistente");
            burbuja.classList.add("cursor-escribiendo");
          }
          acumulado += dato;
          burbuja.innerHTML = renderizarTexto(acumulado);
          scrollAlFinal();
        } else if (tipo === "herramienta") {
          estados.push(mostrarEstadoHerramienta(dato));
        } else if (tipo === "aviso") {
          const aviso = document.createElement("div");
          aviso.className = "estado-herramienta";
          aviso.textContent = `ℹ️ ${dato}`;
          chat.appendChild(aviso);
          scrollAlFinal();
        } else if (tipo === "grafico") {
          renderizarGrafico(dato);
        } else if (tipo === "fin") {
          estados.forEach((e) => e.remove());
          const contenido = dato || acumulado;
          if (burbuja || contenido) {
            if (!burbuja) burbuja = crearBurbuja("asistente");
            burbuja.classList.remove("cursor-escribiendo");
            burbuja.innerHTML = renderizarTexto(contenido);
          }
          if (contenido) leerEnVozAlta(contenido);
        } else if (tipo === "error") {
          estados.forEach((e) => e.remove());
          if (!burbuja) burbuja = crearBurbuja("asistente");
          burbuja.classList.remove("cursor-escribiendo");
          burbuja.innerHTML = "⚠️ " + renderizarTexto(dato);
        }
      }
    }
  } catch (e) {
    (burbuja || crearBurbuja("asistente")).innerHTML = "⚠️ " + escaparHtml(e.message);
  } finally {
    burbuja?.classList.remove("cursor-escribiendo");
    ocupado = false;
    scrollAlFinal();
    entrada.focus();
  }
}

formulario.addEventListener("submit", (e) => {
  e.preventDefault();
  enviarMensaje(entrada.value);
});

// ------------------------------------------------------------------ voz (STT)

let grabadora = null;

async function alternarGrabacion() {
  if (grabadora && grabadora.state === "recording") {
    grabadora.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const trozos = [];
    grabadora = new MediaRecorder(stream, { mimeType: "audio/webm" });
    grabadora.ondataavailable = (e) => trozos.push(e.data);
    grabadora.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      btnMic.classList.remove("grabando");
      btnMic.textContent = "🎤";
      entrada.placeholder = "Transcribiendo…";
      try {
        const audio = new Blob(trozos, { type: "audio/webm" });
        const datos = new FormData();
        datos.append("audio", audio, "grabacion.webm");
        const respuesta = await fetch("/stt", { method: "POST", body: datos });
        if (!respuesta.ok) {
          const err = await respuesta.json().catch(() => ({}));
          throw new Error(err.detail || "No se pudo transcribir el audio");
        }
        const { texto } = await respuesta.json();
        if (texto) {
          entrada.value = texto;
          enviarMensaje(texto);
        }
      } catch (e) {
        crearBurbuja("asistente").innerHTML = "⚠️ " + escaparHtml(e.message);
      } finally {
        entrada.placeholder = "Escribe o pulsa el micrófono…";
      }
    };
    grabadora.start();
    btnMic.classList.add("grabando");
    btnMic.textContent = "⏹";
  } catch {
    crearBurbuja("asistente").textContent = "⚠️ No se pudo acceder al micrófono. Revisa los permisos del navegador.";
  }
}

btnMic.addEventListener("click", alternarGrabacion);

// ------------------------------------------------------------------ estado inicial

// se llama también desde ajustes.js tras cada cambio de configuración
async function actualizarEstado() {
  try {
    const e = await (await fetch("/estado")).json();
    infoProveedor.textContent = e.modelo
      ? `IA: ${e.modelo} (${e.proveedor})` + (e.voz_disponible ? " · 🎤 voz activa" : " · 🎤 solo texto")
      : "⚠️ Sin motor de IA: abre ⚙️ Ajustes";
    btnMic.disabled = !e.voz_disponible;
    btnMic.title = e.voz_disponible
      ? "Hablar (pulsa para grabar, pulsa de nuevo para enviar)"
      : "La voz necesita una clave de Groq u OpenAI (⚙️ Ajustes)";
    return e;
  } catch {
    return null;
  }
}

// Cargar voces de síntesis (algunos navegadores las cargan en diferido)
if ("speechSynthesis" in window) speechSynthesis.getVoices();
