"""Casos de uso bancarios. Orquestan reglas del dominio y puertos; no saben de SQL ni de HTTP.
Todos actúan en nombre de un cliente concreto."""
from ...dominio import reglas
from ...dominio.errores import ConsultaNoPermitida
from ...dominio.modelos import Cliente, Contacto, Cuenta, ResultadoConsulta
from ..puertos.banco import ConsultorMovimientos, RepositorioContactos, RepositorioCuenta
from ..puertos.seguridad import Auditoria


class ConsultarSaldo:
    def __init__(self, cuentas: RepositorioCuenta):
        self._cuentas = cuentas

    def __call__(self, cliente: Cliente) -> Cuenta:
        return self._cuentas.obtener(cliente.id)


class ListarContactos:
    def __init__(self, contactos: RepositorioContactos):
        self._contactos = contactos

    def __call__(self, cliente: Cliente) -> list[Contacto]:
        return self._contactos.listar(cliente.id)


class ConsultarMovimientos:
    """NL→SQL: el LLM escribe el SELECT; aquí se valida y el adaptador lo ejecuta aislado en el cliente."""

    def __init__(self, consultor: ConsultorMovimientos, auditoria: Auditoria):
        self._consultor = consultor
        self._auditoria = auditoria

    def __call__(self, cliente: Cliente, sql: str) -> ResultadoConsulta:
        try:
            limpia = reglas.validar_consulta_solo_lectura(sql)
            resultado = self._consultor.ejecutar_select(cliente.id, limpia, reglas.LIMITE_FILAS_CONSULTA)
        except ConsultaNoPermitida as e:
            self._auditoria.registrar(cliente.id, "consulta_rechazada", sql[:300], e.mensaje)
            raise
        self._auditoria.registrar(cliente.id, "consulta_sql", limpia[:300], f"{len(resultado.filas)} filas")  # también las correctas
        return resultado

    def ultimos(self, cliente: Cliente, limite: int = 50) -> ResultadoConsulta:
        sql = (
            "SELECT fecha, categoria, concepto, comercio, importe FROM movimientos "
            f"ORDER BY fecha DESC, id DESC LIMIT {int(limite)}"
        )
        return self._consultor.ejecutar_select(cliente.id, sql, reglas.LIMITE_FILAS_CONSULTA)
