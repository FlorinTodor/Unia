/* Cliente HTTP mínimo: JSON dentro, JSON fuera, errores con el mensaje legible del servidor. */

export async function pedirJson(metodo, ruta, cuerpo) {
  const respuesta = await fetch(ruta, {
    method: metodo,
    headers: cuerpo ? { "Content-Type": "application/json" } : {},
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.detail || `Error del servidor (${respuesta.status})`);
  return datos;
}
