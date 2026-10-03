/* Entrada de voz: graba con el micrófono del navegador. */

export class Microfono {
  #grabadora = null;

  get grabando() {
    return this.#grabadora?.state === "recording";
  }

  /** Empieza a grabar. `alTerminar(blob)` se llama al parar. Lanza si no hay permiso. */
  async empezar(alTerminar) {
    const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
    const trozos = [];
    this.#grabadora = new MediaRecorder(flujo, { mimeType: "audio/webm" });
    this.#grabadora.ondataavailable = (e) => trozos.push(e.data);
    this.#grabadora.onstop = () => {
      flujo.getTracks().forEach((pista) => pista.stop());
      alTerminar(new Blob(trozos, { type: "audio/webm" }));
    };
    this.#grabadora.start();
  }

  parar() {
    if (this.grabando) this.#grabadora.stop();
  }
}
