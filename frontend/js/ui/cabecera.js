/* Cabecera: modelo en uso y disponibilidad de la voz. */

export function pintarEstado(estado, { infoProveedor, botonMicrofono }) {
  infoProveedor.textContent = estado.modelo
    ? `IA: ${estado.modelo} (${estado.proveedor})` + (estado.voz_disponible ? " · 🎤 voz activa" : " · 🎤 solo texto")
    : "⚠️ Sin motor de IA: abre ⚙️ Ajustes";
  botonMicrofono.disabled = !estado.voz_disponible;
  botonMicrofono.title = estado.voz_disponible
    ? "Hablar (pulsa para grabar, pulsa de nuevo para enviar)"
    : "La voz necesita una clave de Groq u OpenAI (⚙️ Ajustes)";
}
