/* Panel ⚙️ Ajustes: claves API por proveedor, modelos, IA local (Ollama) y voz. */

const panel = document.getElementById("panel-ajustes");
const selProveedor = document.getElementById("nueva-proveedor");
const selModelo = document.getElementById("nueva-modelo");
const selRespaldo = document.getElementById("nueva-respaldo");
const inputClave = document.getElementById("nueva-clave");
const btnGuardarClave = document.getElementById("btn-guardar-clave");
const mensajeClave = document.getElementById("mensaje-clave");
const listaClaves = document.getElementById("lista-claves");
const selOllama = document.getElementById("ollama-modelo");
const inputOllamaUrl = document.getElementById("ollama-url");
const chkOllamaFallback = document.getElementById("ollama-fallback");
const estadoOllama = document.getElementById("estado-ollama");
const selMotorVoz = document.getElementById("motor-voz");

const ICONO_LLAVE = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/></svg>`;
const ICONO_PAPELERA = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>`;
const BADGE_ACTIVA = `<span class="badge-activa"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>Activa</span>`;

let vista = null; // última respuesta de GET /ajustes

// ------------------------------------------------------------------ utilidades

async function api(metodo, ruta, cuerpo) {
  const r = await fetch(ruta, {
    method: metodo,
    headers: cuerpo ? { "Content-Type": "application/json" } : {},
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || `Error del servidor (${r.status})`);
  return datos;
}

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

function catalogo(id) {
  return vista.catalogo.find((c) => c.id === id);
}

// ------------------------------------------------------------------ render

function renderizar(v) {
  vista = v;
  document.getElementById("bienvenida").hidden = v.configurado;

  const nombres = { ollama: "IA local", ...Object.fromEntries(v.catalogo.map((c) => [c.id, c.nombre])) };
  const cadena = v.cadena_fallback.map((eslabon) => eslabon.replace(/\((\w+)\)$/, (_, p) => `(${nombres[p] || p})`));
  document.getElementById("resumen-cadena").innerHTML = cadena.length
    ? `<b>${escaparHtml(cadena[0])}</b>` +
      (cadena.length > 1 ? `<br>Si falla o agota su cuota: ${cadena.slice(1).map(escaparHtml).join(" → ")}` : "")
    : "⚠️ Ningún motor configurado. Añade una clave o activa la IA local.";

  if (!selProveedor.options.length) {
    for (const c of v.catalogo) selProveedor.add(new Option(c.nombre, c.id));
    cambiarProveedorNuevo();
  }

  // claves configuradas
  listaClaves.innerHTML = "";
  if (!v.claves.length) {
    listaClaves.innerHTML = `<p class="texto-suave">Aún no hay claves. Añade una arriba.</p>`;
  }
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
      sel.addEventListener("change", () =>
        accion(() => api("PATCH", `/ajustes/claves/${c.proveedor}`, { [sel.dataset.campo]: sel.value }))
      );
    }
    fila.querySelector('[data-accion="activar"]')?.addEventListener("click", () =>
      accion(() => api("POST", "/ajustes/activar", { proveedor: c.proveedor }))
    );
    fila.querySelector('[data-accion="borrar"]').addEventListener("click", () => {
      if (confirm(`¿Borrar la clave de ${c.nombre}?`)) {
        accion(() => api("DELETE", `/ajustes/claves/${c.proveedor}`));
      }
    });
    listaClaves.appendChild(fila);
  }

  // IA local
  const ollamaActiva = v.activo === "ollama";
  document.getElementById("badge-ollama").innerHTML = ollamaActiva ? BADGE_ACTIVA : "";
  document.getElementById("fila-ollama").classList.toggle("activa", ollamaActiva);
  document.getElementById("btn-activar-ollama").hidden = ollamaActiva;
  if (document.activeElement !== inputOllamaUrl) inputOllamaUrl.value = v.ollama.url;
  chkOllamaFallback.checked = v.ollama.fallback_local;
  if (!selOllama.options.length || selOllama.value !== v.ollama.modelo) {
    rellenarSelect(selOllama, [...selOllama.options].map((o) => o.value), v.ollama.modelo);
  }

  document.getElementById("estado-voz-entrada").textContent = v.voz_entrada
    ? `activa (Whisper vía ${v.voz_entrada})`
    : "desactivada: necesita una clave de Groq u OpenAI. La app funciona igual por escrito.";
}

// aplica un cambio, re-renderiza y refresca la cabecera del chat
async function accion(fn) {
  try {
    renderizar(await fn());
    actualizarEstado();
  } catch (e) {
    alert(e.message);
  }
}

// ------------------------------------------------------------------ añadir clave

function cambiarProveedorNuevo() {
  const c = catalogo(selProveedor.value);
  inputClave.value = "";
  inputClave.placeholder = c.prefijo || "Pega aquí tu clave";
  document.getElementById("nota-proveedor").textContent = c.nota;
  document.getElementById("enlace-claves").href = c.url_claves;
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
      const r = await api("POST", "/ajustes/probar", { proveedor: selProveedor.value, api_key: clave });
      ponerMensaje(mensajeClave, (r.ok ? "✅ " : "❌ ") + r.mensaje, r.ok ? "ok" : "error");
      if (r.ok && r.modelos.length) {
        rellenarSelect(selModelo, r.modelos, selModelo.value);
        rellenarSelect(selRespaldo, r.modelos, selRespaldo.value, { sinRespaldo: true });
      }
    } catch (e) {
      ponerMensaje(mensajeClave, "❌ " + e.message, "error");
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
    const r = await api("POST", "/ajustes/claves", {
      proveedor: selProveedor.value,
      api_key: clave,
      modelo: selModelo.value,
      modelo_respaldo: selRespaldo.value,
    });
    renderizar(r);
    cambiarProveedorNuevo();
    ponerMensaje(mensajeClave, "✅ " + r.mensaje, "ok");
    actualizarEstado();
  } catch (e) {
    ponerMensaje(mensajeClave, "❌ " + e.message, "error");
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
    const r = await api("GET", `/ajustes/ollama/estado?url=${encodeURIComponent(inputOllamaUrl.value)}`);
    estadoOllama.textContent = (r.ok ? "🟢 " : "🔴 ") + r.mensaje;
    estadoOllama.className = `texto-mini ${r.ok ? "ok" : "error"}`;
    rellenarSelect(selOllama, r.modelos, vista.ollama.modelo);
  } catch {
    estadoOllama.textContent = "🔴 No se pudo comprobar Ollama.";
  }
}

inputOllamaUrl.addEventListener("change", async () => {
  await accion(() => api("PUT", "/ajustes/ollama", { url: inputOllamaUrl.value }));
  comprobarOllama();
});
selOllama.addEventListener("change", () => accion(() => api("PUT", "/ajustes/ollama", { modelo: selOllama.value })));
chkOllamaFallback.addEventListener("change", () =>
  accion(() => api("PUT", "/ajustes/ollama", { fallback_local: chkOllamaFallback.checked }))
);
document.getElementById("btn-comprobar-ollama").addEventListener("click", comprobarOllama);
document.getElementById("btn-activar-ollama").addEventListener("click", () =>
  accion(() => api("POST", "/ajustes/activar", { proveedor: "ollama" }))
);

// ------------------------------------------------------------------ voz

try {
  selMotorVoz.value = localStorage.getItem("motorVoz") || "auto";
} catch {}
selMotorVoz.addEventListener("change", () => {
  try {
    localStorage.setItem("motorVoz", selMotorVoz.value);
  } catch {}
});

// ------------------------------------------------------------------ abrir / cerrar

async function abrirAjustes() {
  try {
    renderizar(await api("GET", "/ajustes"));
  } catch (e) {
    alert(e.message);
    return;
  }
  if (!panel.open) panel.showModal();
  comprobarOllama();
}

document.getElementById("btn-ajustes").addEventListener("click", abrirAjustes);
document.getElementById("btn-cerrar-ajustes").addEventListener("click", () => panel.close());
panel.addEventListener("close", () => entrada.focus());

// primer arranque sin motor configurado → se abre el asistente de bienvenida
actualizarEstado().then((e) => {
  if (e && !e.configurado) abrirAjustes();
});
