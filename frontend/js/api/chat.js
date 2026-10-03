/* Adaptador del chat: POST /chat y lectura del flujo SSE como un iterador asíncrono de eventos. */

/** Emite objetos `{tipo, dato, etiqueta?}` conforme llegan: delta, herramienta, aviso, grafico, fin, error. */
export async function* enviarMensaje(sessionId, mensaje) {
  const respuesta = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, mensaje }),
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
      if (linea.startsWith("data: ")) yield JSON.parse(linea.slice(6));
    }
  }
}
