/* Medidor del gasto diario de tokens de la IA, en la cabecera. */

const abreviar = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(".", ",")}k` : String(n));

export class MedidorUso {
  #texto = document.getElementById("uso-tokens");
  #barra = document.getElementById("uso-barra");

  /** @param uso {tokens_hoy, limite_dia} — llega del endpoint /api/uso o del evento SSE `uso` */
  pintar({ tokens_hoy, limite_dia }) {
    const porcentaje = Math.min(100, (100 * tokens_hoy) / limite_dia);
    this.#texto.textContent = `${abreviar(tokens_hoy)} / ${abreviar(limite_dia)} tokens hoy`;
    this.#texto.title = `Uso de la IA hoy: ${tokens_hoy.toLocaleString("es-ES")} de ${limite_dia.toLocaleString("es-ES")} tokens. Se renueva a medianoche.`;
    this.#barra.style.width = `${porcentaje}%`;
    this.#barra.dataset.nivel = porcentaje >= 90 ? "alto" : porcentaje >= 70 ? "medio" : "bajo";
    this.#texto.parentElement.hidden = false;
  }

  ocultar() {
    this.#texto.parentElement.hidden = true;
  }
}
