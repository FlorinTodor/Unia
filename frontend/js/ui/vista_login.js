/* Pantalla de acceso: modal que no se puede cerrar hasta iniciar sesión. */

const CUENTAS_DEMO = [
  { usuario: "alex", nombre: "Alex García", perfil: "Trabajador joven" },
  { usuario: "ana", nombre: "Ana Ruiz", perfil: "Estudiante" },
  { usuario: "marta", nombre: "Marta Moreno", perfil: "Familia con hijos" },
  { usuario: "jose", nombre: "José Luis Romero", perfil: "Jubilado" },
];

export class VistaLogin {
  #dialogo = document.getElementById("panel-login");
  #formulario = document.getElementById("formulario-login");
  #usuario = document.getElementById("login-usuario");
  #contrasena = document.getElementById("login-contrasena");
  #error = document.getElementById("login-error");
  #boton = document.getElementById("btn-login");

  /** @param entrar  async (usuario, contrasena) => void — lanza Error con el motivo si falla */
  constructor(entrar) {
    // sin sesión no hay app: ni Escape ni clic fuera cierran el modal
    this.#dialogo.addEventListener("cancel", (e) => e.preventDefault());

    const lista = document.getElementById("cuentas-demo");
    for (const cuenta of CUENTAS_DEMO) {
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "cuenta-demo";
      const nombre = document.createElement("b");
      nombre.textContent = cuenta.nombre;
      const perfil = document.createElement("span");
      perfil.textContent = cuenta.perfil;
      boton.append(nombre, perfil);
      boton.addEventListener("click", () => {
        this.#usuario.value = cuenta.usuario;
        this.#contrasena.value = "";
        this.#contrasena.focus();
      });
      lista.appendChild(boton);
    }

    this.#formulario.addEventListener("submit", async (e) => {
      e.preventDefault();
      this.#boton.disabled = true;
      this.#error.textContent = "";
      try {
        await entrar(this.#usuario.value, this.#contrasena.value);
        this.#contrasena.value = "";
      } catch (err) {
        this.#error.textContent = err.message;
        this.#contrasena.select();
      } finally {
        this.#boton.disabled = false;
      }
    });
  }

  mostrar(mensaje = "") {
    this.#error.textContent = mensaje;
    this.#contrasena.value = "";
    if (!this.#dialogo.open) this.#dialogo.showModal();
    this.#usuario.focus();
  }

  ocultar() {
    if (this.#dialogo.open) this.#dialogo.close();
  }
}
