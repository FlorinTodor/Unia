/* Adaptador del panel de ajustes: un método por endpoint de /ajustes. */
import { pedirJson } from "./http.js";

export const leerAjustes = () => pedirJson("GET", "/ajustes");
export const probarClave = (proveedor, api_key) => pedirJson("POST", "/ajustes/probar", { proveedor, api_key });
export const guardarClave = (datos) => pedirJson("POST", "/ajustes/claves", datos);
export const cambiarModelo = (proveedor, campos) => pedirJson("PATCH", `/ajustes/claves/${proveedor}`, campos);
export const borrarClave = (proveedor) => pedirJson("DELETE", `/ajustes/claves/${proveedor}`);
export const activarProveedor = (proveedor) => pedirJson("POST", "/ajustes/activar", { proveedor });
export const configurarOllama = (campos) => pedirJson("PUT", "/ajustes/ollama", campos);
export const estadoOllama = (url) => pedirJson("GET", `/ajustes/ollama/estado?url=${encodeURIComponent(url)}`);
