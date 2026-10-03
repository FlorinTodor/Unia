/* Adaptador de operaciones con OTP y del móvil simulado. El código viaja SOLO por aquí, nunca por el chat. */
import { pedirJson } from "./http.js";

export const confirmarOperacion = (id, codigo) => pedirJson("POST", `/operaciones/${encodeURIComponent(id)}/confirmar`, { codigo });
export const aprobarOperacion = (id) => pedirJson("POST", `/operaciones/${encodeURIComponent(id)}/aprobar`);
export const cancelarOperacion = (id) => pedirJson("POST", `/operaciones/${encodeURIComponent(id)}/cancelar`);
export const mensajesDelMovil = () => pedirJson("GET", "/movil/mensajes");
