from ...dominio.modelos import Cliente
from ...dominio.modelos import Cuenta
from ..casos_uso.banco import ConsultarSaldo
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def crear(consultar_saldo: ConsultarSaldo) -> Herramienta:
    def ejecutar(_args: dict, cliente: Cliente) -> ResultadoHerramienta:
        cuenta: Cuenta = consultar_saldo(cliente)
        return ResultadoHerramienta(
            {"iban": cuenta.iban, "titular": cuenta.titular, "saldo": round(cuenta.saldo, 2)}
        )

    return Herramienta(
        esquema=EsquemaHerramienta(
            "consultar_saldo",
            "Obtiene el saldo actual, el IBAN y el titular de la cuenta.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ejecutar=ejecutar,
        etiqueta="Consultando saldo…",
    )
