/* Raíz de composición del frontend: conecta vistas, casos de uso y adaptadores. */
import { alExpirarSesion } from "./api/http.js";
import { cerrarSesion, iniciarSesion, sesionActual } from "./api/auth.js";
import { obtenerEstado } from "./api/estado.js";
import { obtenerUso } from "./api/uso.js";
import { transcribir } from "./api/voz.js";
import { Conversacion } from "./aplicacion/conversacion.js";
import { leerEnVozAlta, pararVoz } from "./dispositivos/altavoz.js";
import { Microfono } from "./dispositivos/microfono.js";
import { pintarEstado } from "./ui/cabecera.js";
import { MedidorUso } from "./ui/medidor_uso.js";
import { Movil } from "./ui/movil.js";
import { iniciarPanelAjustes } from "./ui/panel_ajustes.js";
import { VistaChat } from "./ui/vista_chat.js";
import { VistaLogin } from "./ui/vista_login.js";

const $ = (id) => document.getElementById(id);
const formulario = $("formulario");
const entrada = $("entrada");
const btnMic = $("btn-mic");
const ttsCheck = $("tts-check");

const vista = new VistaChat($("chat"));
const movil = new Movil();
const medidor = new MedidorUso();
const conversacion = new Conversacion(
  vista,
  (texto) => {
    if (ttsCheck.checked) leerEnVozAlta(texto);
  },
  {
    alOperacion: () => movil.avisarMensajeNuevo(),
    alResolverOperacion: () => movil.refrescar(),
    alUso: (uso) => medidor.pintar(uso),
  }
);

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

// ------------------------------------------------------------------ ajustes

const ajustes = iniciarPanelAjustes({ alCambiar: actualizarEstado, alCerrar: () => entrada.focus() });

// ------------------------------------------------------------------ acceso

const login = new VistaLogin(async (usuario, contrasena) => {
  const cliente = await iniciarSesion(usuario, contrasena);
  await entrarComo(cliente);
});

/** Deja la interfaz lista para este cliente: saludo, estado y, la primera vez, el asistente de ajustes. */
async function entrarComo(cliente) {
  login.ocultar();
  $("usuario-actual").textContent = cliente.nombre;
  document.body.classList.add("con-sesion");
  conversacion.reiniciar();
  movil.sembrar();
  vista.saludo(cliente.nombre);
  obtenerUso()
    .then((uso) => {
      medidor.pintar(uso);
      entrada.maxLength = uso.max_caracteres_mensaje; // el servidor rechaza lo que pase de aquí (413)
    })
    .catch(() => {});
  const estado = await actualizarEstado();
  if (estado && !estado.configurado) ajustes.abrir();
  entrada.focus();
}

/** Borra todo rastro del cliente anterior (chat, móvil, usuario) y pide el acceso de nuevo. */
function salirDeLaSesion(mensaje = "") {
  pararVoz();
  vista.limpiar();
  movil.reiniciar();
  medidor.ocultar();
  conversacion.reiniciar();
  document.body.classList.remove("con-sesion");
  $("usuario-actual").textContent = "";
  login.mostrar(mensaje);
}

alExpirarSesion(() => salirDeLaSesion("Tu sesión ha caducado. Inicia sesión de nuevo."));

$("btn-salir").addEventListener("click", async () => {
  try {
    await cerrarSesion();
  } finally {
    salirDeLaSesion();
  }
});

// arranque: si ya hay una sesión válida (cookie) se entra directamente; si no, pantalla de login
sesionActual()
  .then(entrarComo)
  .catch(() => login.mostrar());
