/* Adaptador del chat: POST /chat y lectura del flujo SSE como un iterador asíncrono de eventos. */
import { MENSAJE_SIN_CONEXION, comprobarSesion, errorDeRespuesta, errorHttp, fetchSeguro } from "./http.js";

/** Emite objetos `{tipo, dato, etiqueta?}` conforme llegan: delta, herramienta, aviso, grafico, operacion, fin, error. */
export async function* enviarMensaje(sessionId, mensaje) {
  const respuesta = await fetchSeguro("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, mensaje }),
  });
  comprobarSesion(respuesta);
  if (!respuesta.ok) throw await errorDeRespuesta(respuesta); // 413, 422, 429...: el servidor explica el motivo

  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder();
  let pendiente = "";

  while (true) {
    let trozo;
    try {
      trozo = await lector.read();
    } catch {
      throw errorHttp(MENSAJE_SIN_CONEXION, 0); // se cortó la conexión a mitad de la respuesta
    }
    const { value, done } = trozo;
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
