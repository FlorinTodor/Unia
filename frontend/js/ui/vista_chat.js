/* Vista del chat: burbujas, estados de herramienta, avisos y tarjetas de gráfico. */
import { MARCA } from "../marca.js";
import { escaparHtml, renderizarMarkdown } from "./dom.js";
import { actualizarTarjetaBancaria, claveTarjeta, crearTarjetaBancaria, describirTarjeta } from "./tarjeta_bancaria.js";
import { crearTarjetaOperacion } from "./tarjeta_operacion.js";

export class VistaChat {
  #chat;
  /** (texto) => void — lo fija main.js: enviar al chat lo que pulsa el usuario en una tarjeta bancaria. */
  alPedirTexto = null;

  constructor(contenedor) {
    this.#chat = contenedor;
  }

  #scrollAlFinal() {
    this.#chat.scrollTop = this.#chat.scrollHeight;
  }

  /** Crea una burbuja vacía (`usuario` | `asistente`) y devuelve su elemento. */
  crearBurbuja(rol) {
    const contenedor = document.createElement("div");
    contenedor.className = `mensaje ${rol}`;
    if (rol === "asistente") {
      const avatar = document.createElement("span");
      avatar.className = "avatar-ia";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = MARCA.nombre[0].toLowerCase();
      contenedor.appendChild(avatar);
    }
    const burbuja = document.createElement("div");
    burbuja.className = "burbuja";
    contenedor.appendChild(burbuja);
    this.#chat.appendChild(contenedor);
    this.#scrollAlFinal();
    return burbuja;
  }

  mensajeUsuario(texto) {
    this.crearBurbuja("usuario").textContent = texto;
  }

  /** Burbuja del asistente que se va rellenando con el streaming. */
  burbujaEnStreaming() {
    const burbuja = this.crearBurbuja("asistente");
    burbuja.classList.add("cursor-escribiendo");
    return burbuja;
  }

  pintarTexto(burbuja, markdown, { error = false } = {}) {
    burbuja.classList.toggle("error", error);
    burbuja.innerHTML = renderizarMarkdown(markdown);
    this.#fijarUltimosCuatro(burbuja);
    this.#scrollAlFinal();
  }

  /** «••4821»: la tipografía de texto separa los puntos («• •4821»); se pintan en monoespaciada, como en la tarjeta. */
  #fijarUltimosCuatro(raiz) {
    const hojas = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    const nodos = [];
    for (let n = hojas.nextNode(); n; n = hojas.nextNode()) if (/[•·]{2,}\s?\d{4}/.test(n.nodeValue)) nodos.push(n);
    for (const nodo of nodos) {
      const trozos = document.createDocumentFragment();
      for (const parte of nodo.nodeValue.split(/([•·]{2,}\s?\d{4})/)) {
        if (/^[•·]{2,}\s?\d{4}$/.test(parte)) {
          const span = document.createElement("span");
          span.className = "ult4";
          span.textContent = parte;
          trozos.appendChild(span);
        } else if (parte) trozos.appendChild(document.createTextNode(parte));
      }
      nodo.replaceWith(trozos);
    }
  }

  mensajeError(texto) {
    const burbuja = this.crearBurbuja("asistente");
    burbuja.classList.add("error");
    burbuja.textContent = texto;
  }

  /** Estado efímero «Consultando saldo…» con un indicador de actividad. Devuelve el elemento para quitarlo. */
  estadoHerramienta(etiqueta) {
    return this.#nota(etiqueta, "estado-herramienta trabajando");
  }

  aviso(texto) {
    this.#nota(texto, "estado-herramienta aviso");
  }

  #nota(texto, clase) {
    const div = document.createElement("div");
    div.className = clase;
    div.textContent = texto;
    this.#chat.appendChild(div);
    this.#scrollAlFinal();
    return div;
  }

  grafico({ titulo, config }) {
    const tarjeta = document.createElement("div");
    tarjeta.className = "tarjeta-grafico";
    const h3 = document.createElement("h3");
    h3.textContent = titulo;
    const lienzo = document.createElement("div");
    lienzo.className = "lienzo";
    const canvas = document.createElement("canvas");
    lienzo.appendChild(canvas);
    tarjeta.append(h3, lienzo);
    this.#chat.appendChild(tarjeta);

    try {
      aplicarEstiloCorporativo(config);
      new Chart(canvas, config);
    } catch (e) {
      lienzo.textContent = "No se pudo renderizar el gráfico: " + e.message;
    }
    this.#scrollAlFinal();
  }

  /** Tarjeta bancaria. Las que llegan seguidas en un mismo turno se agrupan en una sola fila desplazable. */
  tarjeta(datos) {
    let fila = this.#chat.lastElementChild;
    if (!fila?.classList.contains("fila-tarjetas")) {
      fila = document.createElement("div");
      fila.className = "fila-tarjetas";
      fila.setAttribute("role", "group");
      fila.setAttribute("aria-label", "Tus tarjetas");
      this.#chat.appendChild(fila);
    }
    this.#actualizarLasYaPintadas(datos); // las antiguas del historial reflejan el estado nuevo
    const alPedir = this.alPedirTexto ? (texto) => this.alPedirTexto(texto) : null;
    fila.appendChild(crearTarjetaBancaria(datos, alPedir));
    this.#scrollAlFinal();
  }

  /** Repinta las tarjetas ya en pantalla que sean esta (p. ej. tras confirmar un desbloqueo) y anuncia el cambio. */
  actualizarTarjeta(datos) {
    this.#actualizarLasYaPintadas(datos);
  }

  /** Repinta las tarjetas con los mismos últimos 4 y, solo si cambia su estado, lo anuncia a los lectores de pantalla. */
  #actualizarLasYaPintadas(datos) {
    const clave = claveTarjeta(datos);
    const nuevo = datos.estado === "bloqueada" ? "bloqueada" : "activa";
    const vistas = [...this.#chat.querySelectorAll(".tarjeta-banco")].filter((el) => el.dataset.clave === clave);
    const cambia = vistas.some((el) => el.dataset.estado !== nuevo);
    for (const el of vistas) actualizarTarjetaBancaria(el, datos);
    if (cambia) this.anunciar(describirTarjeta(datos));
  }

  /** Durante un turno los botones de las tarjetas no hacen nada (aria-disabled + estilo apagado). */
  ocupado(si) {
    this.#chat.classList.toggle("ocupado", si);
    for (const b of this.#chat.querySelectorAll(".tb-accion")) {
      if (si) b.setAttribute("aria-disabled", "true");
      else b.removeAttribute("aria-disabled");
    }
  }

  /** Tarjeta para confirmar una operación con el código del móvil (o con la huella). */
  operacion(datos, alTerminar) {
    const tarjeta = crearTarjetaOperacion(datos, (r) => {
      if (r.tarjeta) this.actualizarTarjeta(r.tarjeta);
      alTerminar(r);
    });
    this.#chat.appendChild(tarjeta);
    this.#scrollAlFinal();
    // el foco va al campo del código: con lector de pantalla se oye el resumen y se puede teclear sin buscar nada
    requestAnimationFrame(() => tarjeta.querySelector("input")?.focus());
  }

  /** Texto para lectores de pantalla (región `aria-live`): se anuncia la respuesta ya terminada, no cada fragmento. */
  anunciar(texto) {
    const region = document.getElementById("anuncios");
    if (!region) return;
    region.textContent = "";
    // el cambio de contenido en dos pasos asegura que se vuelva a leer aunque el texto se repita
    setTimeout(() => (region.textContent = texto.replace(/[*`#_|]/g, " ").replace(/\s+/g, " ").trim()), 50);
  }

  saludo(nombre) {
    this.#chat.replaceChildren();
    this.crearBurbuja("asistente").innerHTML =
      `Hola, ${escaparHtml(nombre.split(" ")[0])}. Soy <b>${escaparHtml(MARCA.nombre)}</b>, tu ${escaparHtml(MARCA.descriptor)}. ` +
      "Puedes <b>escribirme o hablarme</b>: pregúntame por tu saldo o tus gastos " +
      "(«¿cuánto gasté en restaurantes en junio?»), envía un Bizum o pídeme un gráfico. " +
      "Elige una pregunta de abajo para empezar.";
  }

  limpiar() {
    this.#chat.replaceChildren();
  }

  alFinal() {
    this.#scrollAlFinal();
  }
}


const TIPOS_DE_REPARTO = new Set(["pie", "doughnut", "polarArea"]);

/** Colores y tipografía de Unicaja en cualquier gráfico, elija lo que elija el modelo. Los datos no se tocan. */
function aplicarEstiloCorporativo(config) {
  const estilo = getComputedStyle(document.documentElement);
  const texto = estilo.getPropertyValue("--texto-suave").trim() || "#4b5a60";
  const rejilla = estilo.getPropertyValue("--borde-suave").trim() || "#e5eef0";
  Chart.defaults.font.family = '"Manrope", system-ui, sans-serif';
  Chart.defaults.color = texto;
  // con «Texto grande» la raíz pasa de 16 px a ~19 px: el lienzo no lo hereda, se escala a mano (12 px por defecto)
  Chart.defaults.font.size = Math.round((12 * parseFloat(estilo.fontSize)) / 16) || 12;

  const oscuro = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const paleta = oscuro ? MARCA.paletaOscura : MARCA.paleta;
  const reparto = TIPOS_DE_REPARTO.has(config.type);
  (config.data?.datasets ?? []).forEach((conjunto, i) => {
    const color = paleta[i % paleta.length];
    if (reparto) {
      conjunto.backgroundColor = (conjunto.data ?? []).map((_, j) => paleta[j % paleta.length]);
      conjunto.borderColor = estilo.getPropertyValue("--superficie").trim() || "#fff";
    } else if (config.type === "line" || config.type === "radar") {
      conjunto.borderColor = color;
      conjunto.backgroundColor = `${color}33`; // el mismo color con transparencia para el área
      conjunto.tension ??= 0.3;
      conjunto.pointBackgroundColor = color;
    } else {
      conjunto.backgroundColor = color;
      conjunto.borderRadius ??= 6;
    }
  });

  config.options = {
    responsive: true,
    maintainAspectRatio: false,
    ...config.options,
    plugins: {
      ...config.options?.plugins,
      legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, ...config.options?.plugins?.legend?.labels } },
    },
  };
  if (!reparto && config.type !== "radar") {
    const eje = (e) => ({ ...e, grid: { color: rejilla, ...e?.grid }, border: { display: false } });
    config.options.scales = { ...config.options.scales, x: eje(config.options.scales?.x), y: eje(config.options.scales?.y) };
  }
}
