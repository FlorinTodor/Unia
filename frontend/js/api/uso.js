/* Adaptador del gasto de tokens de la IA. */
import { pedirJson } from "./http.js";

export const obtenerUso = () => pedirJson("GET", "/api/uso");
