/* Panel de ajustes: claves API por proveedor, modelos, IA local (Ollama) y voz. */
import * as api from "../api/ajustes.js";
import { guardarPreferencia, leerPreferencia } from "../dispositivos/preferencias.js";
import { mostrarAviso } from "./avisos.js";
import { escaparHtml } from "./dom.js";

const ICONO_LLAVE = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/></svg>`;
const ICONO_PAPELERA = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>`;
const BADGE_ACTIVA = `<span class="badge-activa"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>Activa</span>`;

const $ = (id) => document.getElementById(id);

function rellenarSelect(select, modelos, elegido, { sinRespaldo = false } = {}) {
  const lista = [...new Set([elegido, ...modelos].filter(Boolean))].sort();
  select.innerHTML = "";
  if (sinRespaldo) select.add(new Option("Sin respaldo", ""));
  for (const m of lista) select.add(new Option(m, m));
  select.value = elegido || "";
}

function ponerMensaje(elemento, texto, tipo) {
  elemento.textContent = texto;
  elemento.className = `mensaje-estado ${tipo || ""}`;
}

/**
 * @param alCambiar  () => void  — se llama tras cada cambio de configuración (refresca la cabecera)
 * @param alCerrar   () => void
 * @returns {{abrir: () => Promise<void>}}
 */
export function iniciarPanelAjustes({ alCambiar, alCerrar }) {
  const panel = $("panel-ajustes");
  const selProveedor = $("nueva-proveedor");
  const selModelo = $("nueva-modelo");
  const selRespaldo = $("nueva-respaldo");
  const inputClave = $("nueva-clave");
  const btnGuardarClave = $("btn-guardar-clave");
  const mensajeClave = $("mensaje-clave");
  const listaClaves = $("lista-claves");
  const selOllama = $("ollama-modelo");
  const inputOllamaUrl = $("ollama-url");
  const chkOllamaFallback = $("ollama-fallback");
  const estadoOllama = $("estado-ollama");
  const selMotorVoz = $("motor-voz");

  let vista = null; // última respuesta de GET /ajustes

  const catalogo = (id) => vista.catalogo.find((c) => c.id === id);

  // ------------------------------------------------------------------ render

  function renderizar(v) {
    vista = v;
    $("bienvenida").hidden = v.configurado;

    const nombres = { ollama: "IA local", ...Object.fromEntries(v.catalogo.map((c) => [c.id, c.nombre])) };
    const cadena = v.cadena_fallback.map((eslabon) => eslabon.replace(/\((\w+)\)$/, (_, p) => `(${nombres[p] || p})`));
    $("resumen-cadena").innerHTML = cadena.length
      ? `<b>${escaparHtml(cadena[0])}</b>` +
        (cadena.length > 1 ? `<br>Si falla o agota su cuota: ${cadena.slice(1).map(escaparHtml).join(" → ")}` : "")
      : "Ningún motor configurado. Añade una clave o activa la IA local.";

    if (!selProveedor.options.length) {
      for (const c of v.catalogo) selProveedor.add(new Option(c.nombre, c.id));
      cambiarProveedorNuevo();
    }

    renderizarClaves(v);
    renderizarOllama(v);
    $("estado-voz-entrada").textContent = v.voz_entrada
      ? `activa (Whisper vía ${v.voz_entrada})`
      : "desactivada: necesita una clave de Groq u OpenAI. La app funciona igual por escrito.";
  }

  function renderizarClaves(v) {
    listaClaves.innerHTML = "";
    if (!v.claves.length) listaClaves.innerHTML = `<p class="texto-suave">Aún no hay claves. Añade una arriba.</p>`;
    for (const c of v.claves) {
      const activa = v.activo === c.proveedor;
      const fila = document.createElement("div");
      fila.className = "fila-proveedor" + (activa ? " activa" : "");
      fila.innerHTML = `
        <div class="icono-proveedor">${ICONO_LLAVE}</div>
        <div class="datos-proveedor">
          <div class="nombre-proveedor">${escaparHtml(c.nombre)} ${activa ? BADGE_ACTIVA : ""}</div>
          <div class="texto-mini mono">${escaparHtml(c.mascara)}</div>
        </div>
        <div class="controles-proveedor">
          <label class="mini">Principal<select data-campo="modelo"></select></label>
          <label class="mini">Respaldo<select data-campo="modelo_respaldo"></select></label>
          ${activa ? "" : `<button type="button" class="btn-secundario" data-accion="activar">Activar</button>`}
          <button type="button" class="btn-icono" data-accion="borrar" title="Borrar clave" aria-label="Borrar clave de ${escaparHtml(c.nombre)}">${ICONO_PAPELERA}</button>
        </div>`;
      const [selP, selR] = fila.querySelectorAll("select");
      rellenarSelect(selP, c.modelos, c.modelo);
      rellenarSelect(selR, c.modelos, c.modelo_respaldo, { sinRespaldo: true });
      for (const sel of [selP, selR]) {
        sel.addEventListener("change", () => accion(() => api.cambiarModelo(c.proveedor, { [sel.dataset.campo]: sel.value })));
      }
      fila.querySelector('[data-accion="activar"]')?.addEventListener("click", () => accion(() => api.activarProveedor(c.proveedor)));
      fila.querySelector('[data-accion="borrar"]').addEventListener("click", () => {
        if (confirm(`¿Borrar la clave de ${c.nombre}?`)) accion(() => api.borrarClave(c.proveedor));
      });
      listaClaves.appendChild(fila);
    }
  }

  function renderizarOllama(v) {
    const activa = v.activo === "ollama";
    $("badge-ollama").innerHTML = activa ? BADGE_ACTIVA : "";
    $("fila-ollama").classList.toggle("activa", activa);
    $("btn-activar-ollama").hidden = activa;
    if (document.activeElement !== inputOllamaUrl) inputOllamaUrl.value = v.ollama.url;
    chkOllamaFallback.checked = v.ollama.fallback_local;
    if (!selOllama.options.length || selOllama.value !== v.ollama.modelo) {
      rellenarSelect(selOllama, [...selOllama.options].map((o) => o.value), v.ollama.modelo);
    }
  }

  // aplica un cambio, re-renderiza y refresca la cabecera del chat
  async function accion(fn) {
    try {
      renderizar(await fn());
      alCambiar();
    } catch (e) {
      mostrarAviso(e.message);
    }
  }

  // ------------------------------------------------------------------ añadir clave

  function cambiarProveedorNuevo() {
    const c = catalogo(selProveedor.value);
    inputClave.value = "";
    inputClave.placeholder = c.prefijo || "Pega aquí tu clave";
    $("nota-proveedor").textContent = c.nota;
    $("enlace-claves").href = c.url_claves;
    // si ya hay clave para este proveedor, se parte de sus modelos actuales
    const existente = vista.claves.find((k) => k.proveedor === c.id);
    const modelos = existente ? existente.modelos : [];
    rellenarSelect(selModelo, modelos, existente?.modelo || c.modelo);
    rellenarSelect(selRespaldo, modelos, existente?.modelo_respaldo ?? c.modelo_respaldo, { sinRespaldo: true });
    btnGuardarClave.textContent = existente ? "↻ Reemplazar" : "＋ Guardar";
    ponerMensaje(mensajeClave, "");
  }

  let temporizadorPrueba = null;
  inputClave.addEventListener("input", () => {
    clearTimeout(temporizadorPrueba);
    const clave = inputClave.value.trim();
    if (clave.length < 16) return ponerMensaje(mensajeClave, "");
    // al pegar la clave se valida y se cargan los modelos reales de la cuenta
    temporizadorPrueba = setTimeout(async () => {
      ponerMensaje(mensajeClave, "Comprobando clave…");
      try {
        const r = await api.probarClave(selProveedor.value, clave);
        ponerMensaje(mensajeClave, r.mensaje, r.ok ? "ok" : "error");
        if (r.ok && r.modelos.length) {
          rellenarSelect(selModelo, r.modelos, selModelo.value);
          rellenarSelect(selRespaldo, r.modelos, selRespaldo.value, { sinRespaldo: true });
        }
      } catch (e) {
        ponerMensaje(mensajeClave, e.message, "error");
      }
    }, 600);
  });

  async function guardarClave() {
    const clave = inputClave.value.trim();
    if (!clave) {
      ponerMensaje(mensajeClave, "Pega primero la clave API.", "error");
      return inputClave.focus();
    }
    btnGuardarClave.disabled = true;
    ponerMensaje(mensajeClave, "Validando y guardando…");
    try {
      const r = await api.guardarClave({
        proveedor: selProveedor.value,
        api_key: clave,
        modelo: selModelo.value,
        modelo_respaldo: selRespaldo.value,
      });
      renderizar(r);
      cambiarProveedorNuevo();
      ponerMensaje(mensajeClave, r.mensaje, "ok");
      alCambiar();
    } catch (e) {
      ponerMensaje(mensajeClave, e.message, "error");
    } finally {
      btnGuardarClave.disabled = false;
    }
  }

  selProveedor.addEventListener("change", cambiarProveedorNuevo);
  btnGuardarClave.addEventListener("click", guardarClave);
  inputClave.addEventListener("keydown", (e) => {
    if (e.key === "Enter") guardarClave();
  });

  // ------------------------------------------------------------------ IA local

  async function comprobarOllama() {
    estadoOllama.textContent = "Comprobando…";
    estadoOllama.className = "texto-mini";
    try {
      const r = await api.estadoOllama();
      estadoOllama.textContent = r.mensaje;
      estadoOllama.className = `texto-mini ${r.ok ? "ok" : "error"}`;
      rellenarSelect(selOllama, r.modelos, vista.ollama.modelo);
    } catch {
      estadoOllama.textContent = "No se pudo comprobar Ollama.";
    }
  }

  inputOllamaUrl.addEventListener("change", async () => {
    await accion(() => api.configurarOllama({ url: inputOllamaUrl.value }));
    comprobarOllama();
  });
  selOllama.addEventListener("change", () => accion(() => api.configurarOllama({ modelo: selOllama.value })));
  chkOllamaFallback.addEventListener("change", () => accion(() => api.configurarOllama({ fallback_local: chkOllamaFallback.checked })));
  $("btn-comprobar-ollama").addEventListener("click", comprobarOllama);
  $("btn-activar-ollama").addEventListener("click", () => accion(() => api.activarProveedor("ollama")));

  // ------------------------------------------------------------------ voz

  selMotorVoz.value = leerPreferencia("motorVoz", "auto");
  selMotorVoz.addEventListener("change", () => guardarPreferencia("motorVoz", selMotorVoz.value));

  // ------------------------------------------------------------------ abrir / cerrar

  async function abrir() {
    try {
      renderizar(await api.leerAjustes());
    } catch (e) {
      mostrarAviso(e.message);
      return;
    }
    if (!panel.open) panel.showModal();
    comprobarOllama();
  }

  $("btn-ajustes").addEventListener("click", abrir);
  $("btn-cerrar-ajustes").addEventListener("click", () => panel.close());
  panel.addEventListener("close", alCerrar);

  return { abrir };
}
