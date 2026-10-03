/* Adaptador de los datos bancarios del cliente: saldo y movimientos. */
import { pedirJson } from "./http.js";

export const obtenerSaldo = () => pedirJson("GET", "/api/banco/saldo");
export const obtenerMovimientos = (limite = 6) => pedirJson("GET", `/api/banco/movimientos?limite=${limite}`);
