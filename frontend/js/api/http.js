/* Cliente HTTP mínimo: JSON dentro, JSON fuera, errores con el mensaje legible del servidor. */

let alExpirar = () => {};

/** Registra qué hacer cuando el servidor responde 401 (sesión caducada o inexistente). */
export function alExpirarSesion(fn) {
  alExpirar = fn;
}

/** Comprueba una respuesta `fetch`: si es 401 avisa a la app (pantalla de login) y lanza un error. */
export function comprobarSesion(respuesta) {
  if (respuesta.status === 401) {
    alExpirar();
    throw errorHttp("Tu sesión ha caducado. Inicia sesión de nuevo.", 401);
  }
}

/** Error con el código HTTP (`estado`) y, si el servidor lo indicó, los segundos de espera (`reintentarEn`). */
export function errorHttp(mensaje, estado, reintentarEn = null) {
  const error = new Error(mensaje);
  error.estado = estado;
  error.reintentarEn = reintentarEn;
  return error;
}

export const MENSAJE_SIN_CONEXION = "No se puede conectar con el servidor. Comprueba que está en marcha e inténtalo de nuevo.";

/** `fetch` que, si no hay conexión (servidor parado o reiniciándose), falla con un mensaje comprensible en vez de «Failed to fetch». */
export async function fetchSeguro(url, opciones) {
  try {
    return await fetch(url, opciones);
  } catch {
    throw errorHttp(MENSAJE_SIN_CONEXION, 0);
  }
}

/** Convierte una respuesta de error en un `Error` legible: el servidor siempre manda `{detail}`. */
export async function errorDeRespuesta(respuesta) {
  const datos = await respuesta.json().catch(() => ({}));
  const espera = Number(respuesta.headers.get("Retry-After")) || null;
  return errorHttp(datos.detail || `Error del servidor (${respuesta.status})`, respuesta.status, espera);
}

// en estas rutas un 401 es una respuesta esperada («no hay sesión» / «contraseña incorrecta»), no una caducidad
const SIN_AVISO_DE_SESION = new Set(["/auth/login", "/auth/yo"]);

export async function pedirJson(metodo, ruta, cuerpo) {
  const respuesta = await fetchSeguro(ruta, {
    method: metodo,
    headers: cuerpo ? { "Content-Type": "application/json" } : {},
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  if (!SIN_AVISO_DE_SESION.has(ruta)) comprobarSesion(respuesta);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    throw errorHttp(datos.detail || `Error del servidor (${respuesta.status})`, respuesta.status, Number(respuesta.headers.get("Retry-After")) || null);
  }
  return datos;
}
