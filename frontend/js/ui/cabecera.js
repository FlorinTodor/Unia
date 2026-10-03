/* Cabecera: modelo en uso y disponibilidad de la voz. */

export function pintarEstado(estado, { infoProveedor, botonMicrofono }) {
  const modelo = estado.modelo ? estado.modelo.split("/").at(-1) : null;
  infoProveedor.textContent = modelo
    ? `IA · ${modelo}` + (estado.voz_disponible ? " · voz" : " · solo texto")
    : "Sin motor de IA: abre Ajustes";
  infoProveedor.title = estado.modelo ? `Modelo: ${estado.modelo} (${estado.proveedor})` : "";
  botonMicrofono.disabled = !estado.voz_disponible;
  botonMicrofono.title = estado.voz_disponible
    ? "Hablar (pulsa para grabar, pulsa de nuevo para enviar)"
    : "La voz necesita una clave de Groq u OpenAI (Ajustes)";
}
