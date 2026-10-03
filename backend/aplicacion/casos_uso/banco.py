"""Casos de uso bancarios. Orquestan reglas del dominio y puertos; no saben de SQL ni de HTTP."""
from ...dominio import reglas
from ...dominio.errores import ContactoNoEncontrado
from ...dominio.modelos import ComprobanteBizum, Contacto, Cuenta, Movimiento, ResultadoConsulta
from ..puertos.banco import ConsultorMovimientos, RepositorioContactos, RepositorioCuenta
from ..puertos.infraestructura import Reloj


class ConsultarSaldo:
    def __init__(self, cuentas: RepositorioCuenta):
        self._cuentas = cuentas

    def __call__(self) -> Cuenta:
        return self._cuentas.obtener()


class ListarContactos:
    def __init__(self, contactos: RepositorioContactos):
        self._contactos = contactos

    def __call__(self) -> list[Contacto]:
        return self._contactos.listar()


class EnviarBizum:
    def __init__(self, cuentas: RepositorioCuenta, contactos: RepositorioContactos, reloj: Reloj):
        self._cuentas = cuentas
        self._contactos = contactos
        self._reloj = reloj

    def __call__(self, destinatario: str, importe: float, concepto: str = "") -> ComprobanteBizum:
        importe = reglas.validar_importe_bizum(importe)
        contacto = self._contactos.buscar(destinatario)
        if contacto is None:
            disponibles = [c.nombre for c in self._contactos.listar()]
            raise ContactoNoEncontrado(
                f"No encuentro el contacto '{destinatario}'.", contactos_disponibles=disponibles
            )
        reglas.validar_saldo_suficiente(self._cuentas.obtener().saldo, importe)

        detalle = f"Bizum enviado a {contacto.nombre}" + (f" — {concepto}" if concepto else "")
        cuenta = self._cuentas.registrar_movimiento(
            Movimiento(self._reloj.hoy(), "Bizum", detalle, "Bizum", -importe)
        )
        return ComprobanteBizum(contacto.nombre, contacto.telefono, importe, concepto, cuenta.saldo)


class ConsultarMovimientos:
    """NL→SQL: el LLM escribe el SELECT; aquí se valida antes de llegar a la base de datos."""

    def __init__(self, consultor: ConsultorMovimientos):
        self._consultor = consultor

    def __call__(self, sql: str) -> ResultadoConsulta:
        limpia = reglas.validar_consulta_solo_lectura(sql)
        return self._consultor.ejecutar_select(limpia, reglas.LIMITE_FILAS_CONSULTA)

    def ultimos(self, limite: int = 50) -> ResultadoConsulta:
        sql = f"SELECT fecha, categoria, concepto, comercio, importe FROM movimientos ORDER BY fecha DESC, id DESC LIMIT {int(limite)}"
        return self._consultor.ejecutar_select(sql, reglas.LIMITE_FILAS_CONSULTA)
