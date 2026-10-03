/* Vista del administrador: gasto de tokens de cada cliente y reinicio del día (pruebas y demos). */
import { reiniciarTokens, usoDeClientes } from "../api/admin.js";
import { mostrarAviso } from "./avisos.js";

const miles = (n) => new Intl.NumberFormat("es-ES", { useGrouping: "always" }).format(n);

export class PanelAdmin {
  #raiz = document.getElementById("panel-admin");
  #cuerpo = document.getElementById("admin-clientes");

  async mostrar() {
    this.#raiz.hidden = false;
    await this.cargar();
  }

  ocultar() {
    this.#raiz.hidden = true;
    this.#cuerpo.replaceChildren();
  }

  async cargar() {
    try {
      this.#pintar(await usoDeClientes());
    } catch (e) {
      mostrarAviso(e.message);
    }
  }

  #pintar(clientes) {
    this.#cuerpo.replaceChildren(
      ...clientes.map((c) => {
        const fila = document.createElement("tr");
        const celdas = [c.nombre, c.usuario, `${miles(c.tokens_hoy)} / ${miles(c.limite_dia)}`].map((t) => {
          const td = document.createElement("td");
          td.textContent = t;
          return td;
        });
        const accion = document.createElement("td");
        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = "btn-secundario";
        boton.textContent = "Reiniciar tokens";
        boton.setAttribute("aria-label", `Reiniciar los tokens de hoy de ${c.nombre}`);
        boton.disabled = c.tokens_hoy === 0;
        boton.addEventListener("click", async () => {
          boton.disabled = true;
          try {
            await reiniciarTokens(c.usuario);
            mostrarAviso(`Tokens de ${c.nombre} reiniciados.`, "ok");
          } catch (e) {
            mostrarAviso(e.message);
          }
          await this.cargar();
        });
        accion.append(boton);
        fila.append(...celdas, accion);
        return fila;
      }),
    );
  }
}
