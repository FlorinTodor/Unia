/* Adaptador de la administración (solo perfil admin): tokens por cliente. */
import { pedirJson } from "./http.js";

export const usoDeClientes = () => pedirJson("GET", "/api/admin/uso");
export const reiniciarTokens = (usuario) => pedirJson("POST", `/api/admin/uso/${encodeURIComponent(usuario)}/reiniciar`);
