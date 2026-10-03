/* Avisos emergentes no bloqueantes: sustituyen a `alert()`. Se anuncian a los lectores de pantalla y se cierran solos. */

const SEGUNDOS = { error: 8, ok: 4, info: 5 };

/** @param tipo "error" | "ok" | "info" */
export function mostrarAviso(mensaje, tipo = "error") {
  const contenedor = document.getElementById("avisos");
  if (!contenedor) return;
  const aviso = document.createElement("div");
  aviso.className = `aviso aviso-${tipo}`;
  aviso.setAttribute("role", tipo === "error" ? "alert" : "status");

  const texto = document.createElement("span");
  texto.textContent = mensaje;
  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.className = "aviso-cerrar";
  cerrar.setAttribute("aria-label", "Cerrar el aviso");
  cerrar.textContent = "✕";
  cerrar.addEventListener("click", () => aviso.remove());

  aviso.append(texto, cerrar);
  contenedor.appendChild(aviso);
  setTimeout(() => aviso.remove(), (SEGUNDOS[tipo] ?? 5) * 1000);
}
