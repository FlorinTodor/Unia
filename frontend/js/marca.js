/* Marca del asistente. Para cambiar el nombre o el lema basta con editar este fichero.
 *
 * Nombre: «Unia» = Unicaja + IA. Corto, se pronuncia fácil («oye, Unia») y funciona bien por voz.
 * Colores: los de la web de Unicaja (unicajabanco.es). Ver docs/MARCA.md. */
export const MARCA = {
  nombre: "Unia",
  entidad: "Unicaja",
  descriptor: "asistente de Unicaja",
  lema: "Tu banca, en una conversación",
  // paleta de los gráficos, en orden de uso: petróleo, verde, ámbar, lima, azul verdoso, rojo, marrón, azul, verde claro, tinta
  paleta: ["#005265", "#278600", "#edaf21", "#95e891", "#026169", "#cc2830", "#825300", "#1d697c", "#a0d7a0", "#14232b"],
  // la misma idea sobre fondo oscuro: tonos claros del petróleo y del verde de Unicaja para que se distingan bien
  paletaOscura: ["#7fd0dc", "#95e891", "#f2c24c", "#5fb3c4", "#ff8a8f", "#a0d7a0", "#e6a15c", "#9fb6bd", "#cfe8ee", "#c4a3e8"],
};

/** Rellena todo lo que lleve `data-marca="nombre|descriptor|lema|entidad"` y el título de la página. */
export function aplicarMarca() {
  for (const el of document.querySelectorAll("[data-marca]")) el.textContent = MARCA[el.dataset.marca] ?? "";
  document.title = `${MARCA.nombre} · ${MARCA.descriptor}`;
}
