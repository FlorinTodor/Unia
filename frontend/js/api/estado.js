import { pedirJson } from "./http.js";

export const obtenerEstado = () => pedirJson("GET", "/estado");
