/* Preferencias del navegador (localStorage puede estar bloqueado: nunca debe romper la app). */

export function leerPreferencia(clave, porDefecto) {
  try {
    return localStorage.getItem(clave) || porDefecto;
  } catch {
    return porDefecto;
  }
}

export function guardarPreferencia(clave, valor) {
  try {
    localStorage.setItem(clave, valor);
  } catch {}
}
