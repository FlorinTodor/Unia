/* Iconos de trazo (24×24) dibujados a mano con formas simples. Una categoría de gasto = un icono. */

const TRAZOS = {
  casa: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  carrito: '<path d="M3 4h2l2.4 11h10.2L20 7H6.2"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
  cubiertos: '<path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10"/><path d="M17 3c-2 2-2 6 0 8v10"/>',
  coche: '<path d="M5 17h14M6 17l1.5-6h9L18 17"/><circle cx="8" cy="19" r="1.5"/><circle cx="16" cy="19" r="1.5"/>',
  ocio: '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5.5 3.5-5.5 3.5z"/>',
  corazon: '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/>',
  camiseta: '<path d="M8 4L3 7l2 4 3-1v10h8V10l3 1 2-4-5-3a4 4 0 0 1-8 0z"/>',
  repetir: '<path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12"/><path d="M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/>',
  billete: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 10v.01M18 14v.01"/>',
  movil: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  birrete: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11.5V16c0 1.5 3 3 6 3s6-1.5 6-3v-4.5"/>',
  pesa: '<path d="M6 8v8M18 8v8M3 10v4M21 10v4M6 12h12"/>',
  paquete: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  grafico: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
  lista: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  envio: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
  cartera: '<path d="M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7l12-4v4"/><circle cx="17" cy="13.5" r="1"/>',
  huella: '<path d="M12 11v3a3 3 0 0 1-3 3"/><path d="M8 11a4 4 0 0 1 8 0v2a7 7 0 0 1-2 5"/><path d="M5 11a7 7 0 0 1 14 0v1"/><path d="M12 14v2a9 9 0 0 1-1 4"/>',
  punto: '<circle cx="12" cy="12" r="4"/>',
};

const POR_CATEGORIA = {
  "Vivienda": "casa", "Supermercado": "carrito", "Restaurantes": "cubiertos", "Transporte": "coche", "Ocio": "ocio",
  "Salud": "corazon", "Ropa": "camiseta", "Suscripciones": "repetir", "Nómina": "billete", "Bizum": "movil",
  "Educación": "birrete", "Deporte": "pesa", "Compras online": "paquete",
};

/** SVG del icono `nombre` (o el de la categoría de gasto si se pasa `{categoria}`). */
export function icono(nombre, tamano = 20) {
  const trazos = TRAZOS[POR_CATEGORIA[nombre] ?? nombre] ?? TRAZOS.punto;
  const plantilla = document.createElement("template");
  plantilla.innerHTML =
    `<svg viewBox="0 0 24 24" width="${tamano}" height="${tamano}" fill="none" stroke="currentColor" stroke-width="2" ` +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${trazos}</svg>`;
  return plantilla.content.firstElementChild;
}
