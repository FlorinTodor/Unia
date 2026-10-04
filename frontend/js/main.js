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
import { aplicarMarca } from "./marca.js";
import { MedidorUso } from "./ui/medidor_uso.js";
import { Movil } from "./ui/movil.js";
import { PanelCuenta } from "./ui/panel_cuenta.js";
import { iniciarPanelAjustes } from "./ui/panel_ajustes.js";
import { PanelAdmin } from "./ui/panel_admin.js";
import { Sugerencias } from "./ui/sugerencias.js";
import { VistaChat } from "./ui/vista_chat.js";
import { VistaLogin } from "./ui/vista_login.js";

const $ = (id) => document.getElementById(id);
const formulario = $("formulario");
const entrada = $("entrada");
const btnMic = $("btn-mic");
const ttsCheck = $("tts-check");

aplicarMarca();

// si existe frontend/assets/logo-unicaja.svg se muestra junto al nombre; si no, no pasa nada
const logo = $("logo-entidad");
logo.addEventListener("load", () => (logo.hidden = false));
logo.src = "/static/assets/logo-unicaja.svg";

const vista = new VistaChat($("chat"));
const panelCuenta = new PanelCuenta();
const movil = new Movil();
const medidor = new MedidorUso();
let esperaSms = Promise.resolve(); // el SMS del turno ya está encolado cuando esto se resuelve
const conversacion = new Conversacion(
  vista,
  (texto) => {
    // Suenan los dos, uno detrás de otro: primero el SMS con el código y después el aviso del asistente («He
    // preparado el Bizum…»). Se espera a que el SMS esté en la cola de voz para que el asistente no lo pise.
    const sms = esperaSms;
    esperaSms = Promise.resolve();
    if (ttsCheck.checked) sms.catch(() => {}).then(() => leerEnVozAlta(texto));
  },
  {
    alOperacion: () => {
      esperaSms = Promise.resolve(movil.avisarMensajeNuevo());
      return esperaSms;
    },
    alResolverOperacion: () => {
      movil.refrescar();
      panelCuenta.cargar(); // un Bizum confirmado cambia el saldo y los movimientos
    },
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

const sugerencias = new Sugerencias((texto) => enviar(texto));

async function enviar(texto) {
  pararVoz();
  esperaSms = Promise.resolve();
  entrada.value = "";
  sugerencias.deshabilitar(true);
  await conversacion.enviar(texto);
  sugerencias.deshabilitar(false);
  panelCuenta.cargar(); // el asistente puede haber cambiado datos (p. ej. tras una operación)
  entrada.focus();
}

formulario.addEventListener("submit", (e) => {
  e.preventDefault();
  enviar(entrada.value);
});

// ------------------------------------------------------------------ voz de entrada

const microfono = new Microfono();

async function alternarGrabacion() {
  pararVoz(); // si el usuario va a hablar, nada debe seguir sonando
  if (microfono.grabando) return microfono.parar();
  try {
    await microfono.empezar(async (audio) => {
      btnMic.classList.remove("grabando");
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
  } catch {
    vista.mensajeError("No se pudo acceder al micrófono. Revisa los permisos del navegador.");
  }
}

btnMic.addEventListener("click", alternarGrabacion);

// ------------------------------------------------------------------ ajustes

const panelAdmin = new PanelAdmin();
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
  $("usuario-avatar").textContent = cliente.nombre.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  document.body.classList.add("con-sesion");
  document.body.classList.toggle("es-admin", Boolean(cliente.es_admin));
  conversacion.reiniciar();
  if (cliente.es_admin) {
    // el administrador no tiene cuenta ni chat: solo configura la IA
    panelAdmin.mostrar();
    const estadoAdmin = await actualizarEstado();
    if (estadoAdmin && !estadoAdmin.configurado) ajustes.abrir();
    return;
  }
  panelCuenta.cargar();
  movil.sembrar();
  vista.saludo(cliente.nombre);
  obtenerUso()
    .then((uso) => {
      medidor.pintar(uso);
      entrada.maxLength = uso.max_caracteres_mensaje; // el servidor rechaza lo que pase de aquí (413)
    })
    .catch(() => {});
  const estado = await actualizarEstado();
  entrada.focus();
}

/** Borra todo rastro del cliente anterior (chat, móvil, usuario) y pide el acceso de nuevo. */
function salirDeLaSesion(mensaje = "") {
  pararVoz();
  vista.limpiar();
  movil.reiniciar();
  medidor.ocultar();
  panelCuenta.limpiar();
  conversacion.reiniciar();
  document.body.classList.remove("con-sesion", "es-admin");
  panelAdmin.ocultar();
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
