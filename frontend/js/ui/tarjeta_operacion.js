/* Tarjeta «Confirma tu Bizum»: el cliente confirma con el código que le llegó al móvil o con su huella.
 * Nada de esto pasa por el chat ni por el modelo: va directo a los endpoints de confirmación.
 *
 * Accesibilidad: el foco salta al campo del código (quien usa lector de pantalla cae justo ahí y oye el
 * resumen de la operación), los errores se anuncian como alertas y hay una alternativa a teclear los 6 dígitos. */
import { aprobarOperacion, cancelarOperacion, confirmarOperacion } from "../api/operaciones.js";
import { formatearEuros } from "./formato.js";
import { icono } from "./iconos.js";

function fila(etiqueta, valor) {
  const dt = document.createElement("dt");
  dt.textContent = etiqueta;
  const dd = document.createElement("dd");
  dd.textContent = valor;
  return [dt, dd];
}

function boton(tipo, clase, texto, etiquetaAccesible) {
  const b = document.createElement("button");
  b.type = tipo;
  b.className = clase;
  b.textContent = texto;
  if (etiquetaAccesible) b.setAttribute("aria-label", etiquetaAccesible);
  return b;
}

/**
 * @param operacion  {id, destinatario, importe, concepto, alertas, caduca}
 * @param alTerminar ({estado, mensaje}) => void — estado: confirmada | cancelada | caducada | error
 * @returns HTMLElement
 */
export function crearTarjetaOperacion(operacion, alTerminar = () => {}) {
  const importe = formatearEuros(operacion.importe);
  const tarjeta = document.createElement("div");
  tarjeta.className = "tarjeta-operacion";
  tarjeta.setAttribute("role", "group");
  tarjeta.setAttribute("aria-labelledby", `op-titulo-${operacion.id}`);

  const titulo = document.createElement("h3");
  titulo.id = `op-titulo-${operacion.id}`;
  titulo.textContent = "Confirma tu Bizum";

  const datos = document.createElement("dl");
  datos.append(...fila("Para", operacion.destinatario), ...fila("Importe", importe));
  if (operacion.concepto) datos.append(...fila("Concepto", operacion.concepto));

  const alertas = document.createElement("ul");
  alertas.className = "alertas";
  for (const texto of operacion.alertas || []) {
    const li = document.createElement("li");
    li.textContent = texto;
    alertas.appendChild(li);
  }

  // lo que oye quien usa lector de pantalla al caer en el campo del código
  const resumen = document.createElement("p");
  resumen.id = `op-resumen-${operacion.id}`;
  resumen.className = "solo-lector";
  resumen.textContent =
    `Confirma el Bizum de ${importe} a ${operacion.destinatario}. ` +
    "Te hemos enviado un código de 6 dígitos por SMS al móvil. Escríbelo aquí, o pulsa Aprobar con huella para no teclearlo.";

  const ayuda = document.createElement("p");
  ayuda.className = "texto-mini";
  const cuentaAtras = document.createElement("b");
  cuentaAtras.setAttribute("aria-hidden", "true"); // un contador que cambia cada segundo no se lee
  ayuda.append("Te hemos enviado un código de 6 dígitos al móvil. Caduca en ", cuentaAtras, ".");

  const formulario = document.createElement("form");
  formulario.className = "fila-codigo";
  const codigo = document.createElement("input");
  codigo.type = "text";
  codigo.inputMode = "numeric";
  codigo.maxLength = 6;
  codigo.pattern = "[0-9]{6}";
  codigo.autocomplete = "one-time-code";
  codigo.placeholder = "000000";
  codigo.setAttribute("aria-label", "Código de confirmación de 6 dígitos");
  codigo.setAttribute("aria-describedby", resumen.id);
  const confirmar = boton("submit", "btn-primario", "Confirmar", "Confirmar el Bizum con el código");
  const cancelar = boton("button", "btn-secundario", "Cancelar", "Cancelar el Bizum");
  formulario.append(codigo, confirmar, cancelar);

  // alternativa a teclear: aprobar con un gesto desde el móvil, como en las apps bancarias reales
  const huella = boton(
    "button", "btn-huella", "",
    `Aprobar el Bizum de ${importe} con la huella o Face ID. Alternativa a escribir el código.`
  );
  huella.append(icono("huella", 18), document.createTextNode(" Aprobar con huella"));
  const nota = document.createElement("p");
  nota.className = "texto-mini";
  nota.textContent = "Huella o Face ID simulados: sirve si no puedes leer o teclear el código.";

  const estado = document.createElement("p");
  estado.className = "mensaje-estado";
  estado.setAttribute("role", "status");

  tarjeta.append(titulo, datos, alertas, resumen, ayuda, formulario, huella, nota, estado);

  const controles = [codigo, confirmar, cancelar, huella];
  const caduca = new Date(operacion.caduca).getTime();
  const reloj = setInterval(() => {
    const restante = Math.max(0, Math.round((caduca - Date.now()) / 1000));
    cuentaAtras.textContent = `${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, "0")}`;
    if (restante === 0) cerrar("caducada", "El código ha caducado. Pide el Bizum de nuevo.");
  }, 1000);

  function cerrar(resultado, mensaje) {
    clearInterval(reloj);
    for (const el of controles) el.disabled = true;
    estado.className = `mensaje-estado ${resultado === "confirmada" ? "ok" : "error"}`;
    estado.setAttribute("role", resultado === "confirmada" ? "status" : "alert"); // los fallos se anuncian al instante
    estado.textContent = mensaje;
    alTerminar({ estado: resultado, mensaje });
  }

  /** Lanza la confirmación (por código o por huella) y refleja el resultado. */
  async function resolver(peticion) {
    for (const el of [confirmar, huella]) el.disabled = true;
    estado.className = "mensaje-estado";
    estado.setAttribute("role", "status");
    estado.textContent = "Comprobando…";
    try {
      const r = await peticion();
      cerrar("confirmada", `Bizum enviado: ${formatearEuros(r.importe)} a ${r.destinatario}. Nuevo saldo: ${formatearEuros(r.nuevo_saldo)}.`);
    } catch (err) {
      // 404 no existe · 409 ya procesada o sin saldo · 410 caducada · 423 intentos agotados: no se puede reintentar
      if ([404, 409, 410, 423].includes(err.estado)) return cerrar("error", err.message);
      estado.className = "mensaje-estado error";
      estado.setAttribute("role", "alert");
      estado.textContent = err.message;
      for (const el of [confirmar, huella]) el.disabled = false;
      codigo.select();
    }
  }

  formulario.addEventListener("submit", (e) => {
    e.preventDefault();
    resolver(() => confirmarOperacion(operacion.id, codigo.value.trim()));
  });
  huella.addEventListener("click", () => resolver(() => aprobarOperacion(operacion.id)));

  cancelar.addEventListener("click", async () => {
    try {
      await cancelarOperacion(operacion.id);
      cerrar("cancelada", "Operación cancelada. No se ha enviado nada.");
    } catch (err) {
      estado.className = "mensaje-estado error";
      estado.setAttribute("role", "alert");
      estado.textContent = err.message;
    }
  });

  return tarjeta;
}
