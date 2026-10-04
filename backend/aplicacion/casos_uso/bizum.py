"""Bizum con confirmación OTP en dos pasos.

1. `SolicitarBizum`: valida, crea una operación pendiente y envía un código al móvil del cliente.
   NO mueve dinero. Es lo único que puede disparar el LLM.
2. `ConfirmarOperacion`: el cliente teclea el código en la interfaz (nunca pasa por el LLM) y,
   solo si es correcto, se ejecuta el movimiento.
"""
import threading

from ...dominio import reglas
from ...dominio.errores import ERRORES_DE_REGLA, ContactoAmbiguo, ContactoNoEncontrado, OperacionNoEncontrada
from ...dominio.modelos import ComprobanteBizum, Cliente, Movimiento
from ...dominio.operaciones import EstadoOperacion, OperacionPendiente
from ..puertos.banco import RepositorioContactos, RepositorioCuenta
from ..puertos.infraestructura import Reloj
from ..puertos.seguridad import Auditoria, CanalOTP, GeneradorCodigos, RepositorioOperaciones


class SolicitarBizum:
    def __init__(
        self,
        cuentas: RepositorioCuenta,
        contactos: RepositorioContactos,
        operaciones: RepositorioOperaciones,
        codigos: GeneradorCodigos,
        canal: CanalOTP,
        reloj: Reloj,
        auditoria: Auditoria,
    ):
        self._cuentas = cuentas
        self._contactos = contactos
        self._operaciones = operaciones
        self._codigos = codigos
        self._canal = canal
        self._reloj = reloj
        self._auditoria = auditoria

    def __call__(self, cliente: Cliente, destinatario: str, importe: float, concepto: str = "") -> OperacionPendiente:
        try:
            operacion = self._crear(cliente, destinatario, importe, concepto)
        except ERRORES_DE_REGLA as e:
            self._auditoria.registrar(cliente.id, "bizum_rechazado", f"{destinatario} {importe}", e.mensaje)
            raise
        self._auditoria.registrar(
            cliente.id, "bizum_solicitado", f"{operacion.importe:.2f} € a {operacion.destinatario}", f"op {operacion.id}"
        )
        return operacion

    def _crear(self, cliente: Cliente, destinatario: str, importe: float, concepto: str) -> OperacionPendiente:
        importe = reglas.validar_importe_bizum(importe)
        concepto = reglas.validar_concepto(concepto) or reglas.CONCEPTO_POR_DEFECTO
        agenda = self._contactos.listar(cliente.id)
        candidatos = reglas.buscar_contactos(agenda, destinatario)
        if not candidatos:
            raise ContactoNoEncontrado(
                f"No encuentro el contacto '{destinatario}'.", contactos_disponibles=[c.nombre for c in agenda]
            )
        if len(candidatos) > 1:
            raise ContactoAmbiguo(
                f"'{destinatario}' coincide con varios contactos: pregunta a cuál se refiere.",
                contactos_disponibles=[c.nombre for c in candidatos],
            )
        contacto = candidatos[0]
        reglas.validar_saldo_suficiente(self._cuentas.obtener(cliente.id).saldo, importe)
        reglas.validar_tope_diario(self._cuentas.bizum_enviado_el(cliente.id, self._reloj.hoy()), importe)

        codigo = self._codigos.nuevo_codigo()
        operacion = OperacionPendiente.nueva(
            self._codigos.nuevo_id(), cliente.id, contacto.nombre, contacto.telefono, importe, concepto,
            codigo, self._reloj.ahora(),
            alertas=reglas.alertas_bizum(importe, self._cuentas.envios_bizum_a(cliente.id, contacto.nombre)),
        )
        self._operaciones.guardar(operacion)
        self._canal.enviar(
            cliente.id,
            f"Código de confirmación: {codigo}. Bizum de {reglas.euros(importe)} a {contacto.nombre}. "
            "Caduca en 5 minutos. No lo compartas con nadie.",
        )
        return operacion


class CerrojosPorCliente:
    """Un cerrojo por cliente para serializar las operaciones que cambian el estado de sus Bizum.

    Confirmar y cancelar DEBEN compartir la MISMA instancia (si no, una cancelación pisaba una confirmación en curso y el
    dinero salía con la operación marcada como cancelada): por eso es un parámetro obligatorio y lo crea
    `composicion.py` una sola vez, sin instancia global escondida.
    """

    def __init__(self):
        self._cerrojos: dict[int, threading.Lock] = {}
        self._guarda = threading.Lock()

    def de(self, cliente_id: int) -> threading.Lock:
        with self._guarda:
            return self._cerrojos.setdefault(cliente_id, threading.Lock())


class _OperacionesDelCliente:
    """Obtiene una operación solo si pertenece al cliente: una ajena es 'no encontrada'."""

    def __init__(self, operaciones: RepositorioOperaciones):
        self._operaciones = operaciones

    def obtener(self, cliente: Cliente, id_operacion: str) -> OperacionPendiente:
        operacion = self._operaciones.obtener(id_operacion)
        if operacion is None or operacion.cliente_id != cliente.id:
            raise OperacionNoEncontrada("No encuentro esa operación.")
        return operacion


class ConfirmarOperacion(_OperacionesDelCliente):
    """Ejecuta el Bizum cuando el cliente demuestra que es él: con el código OTP o aprobando con su huella."""

    def __init__(
        self,
        cuentas: RepositorioCuenta,
        operaciones: RepositorioOperaciones,
        reloj: Reloj,
        auditoria: Auditoria,
        cerrojos: CerrojosPorCliente,
    ):
        super().__init__(operaciones)
        self._cuentas = cuentas
        self._reloj = reloj
        self._auditoria = auditoria
        # Leer, comprobar y guardar la operación no es atómico: con peticiones paralelas (hilos) un mismo Bizum se
        # ejecutaba varias veces y el OTP admitía más de 3 intentos. Se serializa por cliente, que además protege
        # el tope diario entre operaciones distintas. Con varios procesos haría falta la transición atómica en SQL.
        self._cerrojos = cerrojos

    def _cerrojo(self, cliente_id: int) -> threading.Lock:
        return self._cerrojos.de(cliente_id)

    def __call__(self, cliente: Cliente, id_operacion: str, codigo: str) -> ComprobanteBizum:
        """Confirma con el código de 6 dígitos que llegó por SMS."""
        with self._cerrojo(cliente.id):
            operacion = self.obtener(cliente, id_operacion)
            return self._ejecutar(cliente, operacion, lambda: operacion.verificar(codigo, self._reloj.ahora()), "otp_rechazado")

    def aprobar(self, cliente: Cliente, id_operacion: str) -> ComprobanteBizum:
        """Confirma aprobándola desde el móvil (huella / Face ID simulados), sin teclear nada."""
        with self._cerrojo(cliente.id):
            operacion = self.obtener(cliente, id_operacion)
            return self._ejecutar(cliente, operacion, lambda: operacion.aprobar(self._reloj.ahora()), "aprobacion_rechazada")

    def _ejecutar(self, cliente: Cliente, operacion, comprobar, accion_si_falla: str) -> ComprobanteBizum:
        try:
            comprobar()
        except ERRORES_DE_REGLA as e:
            self._operaciones.guardar(operacion)  # los intentos y el estado cambian aunque falle
            self._auditoria.registrar(cliente.id, accion_si_falla, f"op {operacion.id}", e.mensaje)
            raise

        try:
            # el saldo o el tope diario pueden haber cambiado desde la solicitud
            reglas.validar_saldo_suficiente(self._cuentas.obtener(cliente.id).saldo, operacion.importe)
            reglas.validar_tope_diario(
                self._cuentas.bizum_enviado_el(cliente.id, self._reloj.hoy()), operacion.importe
            )
        except ERRORES_DE_REGLA as e:
            operacion.estado = EstadoOperacion.CANCELADA
            self._operaciones.guardar(operacion)
            self._auditoria.registrar(cliente.id, "bizum_cancelado", f"op {operacion.id}", e.mensaje)
            raise

        detalle = f"Bizum enviado a {operacion.destinatario}" + (f" — {operacion.concepto}" if operacion.concepto else "")
        cuenta = self._cuentas.registrar_movimiento(
            cliente.id, Movimiento(self._reloj.hoy(), "Bizum", detalle, "Bizum", -operacion.importe)
        )
        self._operaciones.guardar(operacion)
        self._auditoria.registrar(
            cliente.id, "bizum_ejecutado", f"{operacion.importe:.2f} € a {operacion.destinatario}", f"op {operacion.id}"
        )
        return ComprobanteBizum(
            operacion.destinatario, operacion.telefono, operacion.importe, operacion.concepto, cuenta.saldo
        )


class CancelarOperacion(_OperacionesDelCliente):
    def __init__(self, operaciones: RepositorioOperaciones, auditoria: Auditoria, cerrojos: CerrojosPorCliente):
        super().__init__(operaciones)
        self._auditoria = auditoria
        self._cerrojos = cerrojos

    def __call__(self, cliente: Cliente, id_operacion: str) -> None:
        with self._cerrojos.de(cliente.id):
            operacion = self.obtener(cliente, id_operacion)
            operacion.cancelar()
            self._operaciones.guardar(operacion)
        self._auditoria.registrar(cliente.id, "bizum_cancelado", f"op {operacion.id}", "cancelado por el cliente")
