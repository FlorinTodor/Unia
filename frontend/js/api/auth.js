/* Adaptador de acceso: login, sesión actual y logout (la cookie la gestiona el navegador, HttpOnly). */
import { pedirJson } from "./http.js";

export const iniciarSesion = (usuario, contrasena) => pedirJson("POST", "/auth/login", { usuario, contrasena });
export const sesionActual = () => pedirJson("GET", "/auth/yo");
export const cerrarSesion = () => pedirJson("POST", "/auth/logout");
