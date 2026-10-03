from ..casos_uso.banco import ListarContactos
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def crear(listar_contactos: ListarContactos) -> Herramienta:
    def ejecutar(_args: dict) -> ResultadoHerramienta:
        return ResultadoHerramienta(
            {"contactos": [{"nombre": c.nombre, "telefono": c.telefono} for c in listar_contactos()]}
        )

    return Herramienta(
        esquema=EsquemaHerramienta(
            "listar_contactos_bizum",
            "Lista los contactos disponibles para enviar Bizum (nombre y teléfono).",
            {"type": "object", "properties": {}, "required": []},
        ),
        ejecutar=ejecutar,
        etiqueta="Buscando contactos…",
    )
