/* Panel de la cuenta: saldo y últimos movimientos. Refuerzo visual permanente junto a la conversación. */
import { obtenerMovimientos, obtenerSaldo } from "../api/banco.js";
import { formatearEuros } from "./formato.js";
import { icono } from "./iconos.js";

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function fechaCorta(iso) {
  const [, mes, dia] = iso.split("-").map(Number);
  return `${dia} ${MESES[mes - 1]}`;
}

/** «ES21 2103 0000 1122 3344 5566» → «ES21 •••• •••• •••• 5566» */
function iban(texto) {
  const partes = texto.split(" ");
  return partes.length > 2 ? `${partes[0]} •••• •••• •••• ${partes.at(-1)}` : texto;
}

export class PanelCuenta {
  #importe = document.getElementById("saldo-importe");
  #iban = document.getElementById("saldo-iban");
  #titular = document.getElementById("saldo-titular");
  #lista = document.getElementById("lista-movimientos");

  async cargar() {
    try {
      const [saldo, movimientos] = await Promise.all([obtenerSaldo(), obtenerMovimientos(7)]);
      this.#importe.textContent = formatearEuros(saldo.saldo);
      this.#iban.textContent = iban(saldo.iban);
      this.#titular.textContent = saldo.titular;
      this.#pintar(movimientos);
    } catch {
      /* si falla, el panel conserva lo anterior: la conversación sigue funcionando */
    }
  }

  limpiar() {
    this.#importe.textContent = "—";
    this.#iban.textContent = "";
    this.#titular.textContent = "";
    this.#lista.replaceChildren();
  }

  #pintar({ columnas, filas }) {
    const col = Object.fromEntries(columnas.map((c, i) => [c, i]));
    this.#lista.replaceChildren();
    for (const fila of filas) {
      const importe = fila[col.importe];
      const li = document.createElement("li");
      li.className = `movimiento ${importe > 0 ? "ingreso" : "gasto"}`;

      const ic = document.createElement("span");
      ic.className = "mov-icono";
      ic.appendChild(icono(fila[col.categoria], 18));

      const datos = document.createElement("div");
      const concepto = document.createElement("div");
      concepto.className = "mov-concepto";
      concepto.textContent = fila[col.concepto];
      concepto.title = fila[col.concepto];
      const meta = document.createElement("div");
      meta.className = "mov-meta";
      meta.textContent = `${fechaCorta(fila[col.fecha])} · ${fila[col.categoria]}`;
      datos.append(concepto, meta);

      const valor = document.createElement("span");
      valor.className = "mov-importe";
      // el signo se escribe además del color: no se depende solo del color para distinguir ingresos y gastos
      valor.textContent = (importe > 0 ? "+" : "") + formatearEuros(importe);

      li.append(ic, datos, valor);
      this.#lista.appendChild(li);
    }
  }
}
