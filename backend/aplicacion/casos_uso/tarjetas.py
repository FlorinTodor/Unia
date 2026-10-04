"""Bloqueo y desbloqueo de tarjetas.

Bloquear es la dirección SEGURA y urgente («he perdido la tarjeta»): lo puede ejecutar el asistente sin OTP, pero queda
auditado. Desbloquear reabre el uso de la tarjeta: exige el mismo OTP que un Bizum (operación pendiente + código al móvil
+ confirmación fuera del LLM, en `ConfirmarOperacion`). La tarjeta la elige el servidor (`reglas.elegir_tarjeta`).
"""
from ...dominio import reglas
from ...dominio.errores import ERRORES_DE_REGLA, TarjetaNoEncontrada, TarjetaYaBloqueada
from ...dominio.modelos import Cliente, Tarjeta
from ...dominio.operaciones import OperacionPendiente, TipoOperacion
from ..puertos.banco import RepositorioTarjetas
from ..puertos.infraestructura import Reloj
from ..puertos.seguridad import Auditoria, CanalOTP, GeneradorCodigos, RepositorioOperaciones
from ..texto import enmascarar_numeros_largos
from .cerrojos import CerrojosPorCliente


class ConsultarTarjetas:
    def __init__(self, tarjetas: RepositorioTarjetas):
        self._tarjetas = tarjetas

    def __call__(self, cliente: Cliente) -> list[Tarjeta]:
        return self._tarjetas.listar(cliente.id)


class BloquearTarjeta:
    """Bloquea la tarjeta y, con ella, cancela los desbloqueos que el cliente tuviera pendientes: quien la bloquea porque
    «me han robado la cartera y el móvil» no debe poder reactivarla con un código que ya está en un móvil robado."""

    def __init__(
        self, tarjetas: RepositorioTarjetas, reloj: Reloj, auditoria: Auditoria,
        operaciones: RepositorioOperaciones, cerrojos: CerrojosPorCliente,
    ):
        self._tarjetas = tarjetas
        self._reloj = reloj
        self._auditoria = auditoria
        self._operaciones = operaciones
        self._cerrojos = cerrojos  # el mismo que usa ConfirmarOperacion: bloquear y confirmar un desbloqueo no se pisan

    def __call__(self, cliente: Cliente, consulta: str = "") -> Tarjeta:
        visto = enmascarar_numeros_largos(consulta)[:60]  # un número de tarjeta completo no debe quedar en la auditoría
        with self._cerrojos.de(cliente.id):
            try:
                tarjeta = reglas.elegir_tarjeta(self._tarjetas.listar(cliente.id), consulta, para_bloquear=True)
                bloqueada = reglas.bloquear_tarjeta(tarjeta, self._reloj.ahora())
                self._tarjetas.guardar_estado(cliente.id, bloqueada)
            except TarjetaYaBloqueada as e:
                self._cancelar_desbloqueos(cliente, {t.id for t in e.tarjetas})  # ya estaba bloqueada, pero el desbloqueo sigue vivo
                self._auditoria.registrar(cliente.id, "tarjeta_bloqueo_rechazado", visto, e.mensaje)
                raise
            except (*ERRORES_DE_REGLA, TarjetaNoEncontrada) as e:
                self._auditoria.registrar(cliente.id, "tarjeta_bloqueo_rechazado", visto, e.mensaje)
                raise
            self._cancelar_desbloqueos(cliente, {bloqueada.id})
        self._auditoria.registrar(cliente.id, "tarjeta_bloqueada", bloqueada.etiqueta, f"tarjeta {bloqueada.id}")
        return bloqueada

    def _cancelar_desbloqueos(self, cliente: Cliente, ids_tarjeta: set[int]) -> None:
        for op in self._operaciones.pendientes_de(cliente.id):
            if op.tipo is TipoOperacion.DESBLOQUEO_TARJETA and op.referencia.isdigit() and int(op.referencia) in ids_tarjeta:
                op.cancelar()
                self._operaciones.guardar(op)
                self._auditoria.registrar(cliente.id, "desbloqueo_cancelado", f"op {op.id}", "la tarjeta se ha bloqueado")


class SolicitarDesbloqueoTarjeta:
    """Crea la operación pendiente de OTP. NO desbloquea nada: es lo único que puede disparar el LLM."""

    def __init__(
        self,
        tarjetas: RepositorioTarjetas,
        operaciones: RepositorioOperaciones,
        codigos: GeneradorCodigos,
        canal: CanalOTP,
        reloj: Reloj,
        auditoria: Auditoria,
    ):
        self._tarjetas = tarjetas
        self._operaciones = operaciones
        self._codigos = codigos
        self._canal = canal
        self._reloj = reloj
        self._auditoria = auditoria

    def __call__(self, cliente: Cliente, consulta: str = "") -> OperacionPendiente:
        try:
            tarjeta = reglas.elegir_tarjeta(self._tarjetas.listar(cliente.id), consulta, para_bloquear=False)
        except (*ERRORES_DE_REGLA, TarjetaNoEncontrada) as e:
            self._auditoria.registrar(cliente.id, "desbloqueo_rechazado", enmascarar_numeros_largos(consulta)[:60], e.mensaje)
            raise
        codigo = self._codigos.nuevo_codigo()
        operacion = OperacionPendiente.nueva(
            self._codigos.nuevo_id(), cliente.id, tarjeta.etiqueta, cliente.telefono, 0.0, "Desbloqueo de tarjeta",
            codigo, self._reloj.ahora(), tipo=TipoOperacion.DESBLOQUEO_TARJETA, referencia=str(tarjeta.id),
        )
        self._operaciones.guardar(operacion)
        self._canal.enviar(
            cliente.id,
            f"Código de confirmación: {codigo}. Desbloqueo de la tarjeta {tarjeta.etiqueta}. "
            "Caduca en 5 minutos. No lo compartas con nadie.",
        )
        self._auditoria.registrar(cliente.id, "desbloqueo_solicitado", tarjeta.etiqueta, f"op {operacion.id}")
        return operacion


class DesbloquearTarjeta:
    """El paso final: solo lo llama `ConfirmarOperacion` cuando el cliente ya demostró con su código que es él."""

    def __init__(self, tarjetas: RepositorioTarjetas, auditoria: Auditoria):
        self._tarjetas = tarjetas
        self._auditoria = auditoria

    def __call__(self, cliente: Cliente, id_tarjeta: int) -> Tarjeta:
        # se busca entre las del cliente: el id de una tarjeta ajena es «no encontrada»
        tarjeta = next((t for t in self._tarjetas.listar(cliente.id) if t.id == id_tarjeta), None)
        if tarjeta is None:
            raise TarjetaNoEncontrada("No encuentro esa tarjeta.")
        activa = reglas.desbloquear_tarjeta(tarjeta)
        self._tarjetas.guardar_estado(cliente.id, activa)
        self._auditoria.registrar(cliente.id, "tarjeta_desbloqueada", activa.etiqueta, f"tarjeta {activa.id}")
        return activa
