"""Dobles de prueba en memoria: implementan los puertos sin red ni base de datos."""
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta

from backend.aplicacion.puertos.infraestructura import EstadoOllama
from backend.aplicacion.agente import Agente
from backend.aplicacion.puertos.llm import DeltaTexto, EsquemaHerramienta, PeticionHerramientas, UsoTokens
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.dominio.modelos import (
    Cliente,
    Contacto,
    Cuenta,
    LlamadaHerramienta,
    Mensaje,
    Movimiento,
    ResultadoConsulta,
)
from backend.dominio.proveedores import ModeloRef
from backend.dominio.uso import PresupuestoUso, Uso

ALEX = Cliente(1, "alex", "Alex García", "611000111")
ANA = Cliente(2, "ana", "Ana Ruiz", "622000222")


class RelojFijo:
    """Reloj controlable: `avanzar(minutos=6)` para probar caducidades y bloqueos."""

    def __init__(self, ahora: datetime = datetime(2026, 10, 3, 12, 0)):
        self._ahora = ahora

    def hoy(self) -> date:
        return self._ahora.date()

    def ahora(self) -> datetime:
        return self._ahora

    def avanzar(self, minutos: int) -> None:
        self._ahora += timedelta(minutes=minutos)


class CuentaEnMemoria:
    """Cuentas por cliente; sirve para comprobar que cada llamada usa el cliente correcto."""

    def __init__(self, saldo: float = 500.0):
        self.cuentas = {c.id: Cuenta(f"ES0{c.id}", c.nombre, saldo) for c in (ALEX, ANA)}
        self.movimientos: dict[int, list[Movimiento]] = {ALEX.id: [], ANA.id: []}

    def obtener(self, cliente_id: int) -> Cuenta:
        return self.cuentas[cliente_id]

    def registrar_movimiento(self, cliente_id: int, movimiento: Movimiento) -> Cuenta:
        self.movimientos[cliente_id].append(movimiento)
        c = self.cuentas[cliente_id]
        self.cuentas[cliente_id] = replace(c, saldo=round(c.saldo + movimiento.importe, 2))
        return self.cuentas[cliente_id]

    def bizum_enviado_el(self, cliente_id: int, dia: date) -> float:
        return round(sum(-m.importe for m in self.movimientos[cliente_id] if m.categoria == "Bizum" and m.fecha == dia and m.importe < 0), 2)

    def envios_bizum_a(self, cliente_id: int, nombre: str) -> int:
        return sum(1 for m in self.movimientos[cliente_id] if nombre in m.concepto)


class ContactosEnMemoria:
    def __init__(self):
        self.contactos = {
            ALEX.id: [Contacto("María López", "600111222"), Contacto("Pablo Ruiz", "611333444")],
            ANA.id: [Contacto("Mamá", "655040404")],
        }

    def listar(self, cliente_id: int) -> list[Contacto]:
        return list(self.contactos[cliente_id])

    def buscar(self, cliente_id: int, nombre_o_telefono: str) -> Contacto | None:
        return next(
            (c for c in self.contactos[cliente_id] if nombre_o_telefono.lower() in c.nombre.lower() or c.telefono == nombre_o_telefono),
            None,
        )


class ConsultorFalso:
    def __init__(self):
        self.consultas: list[tuple[int, str, int]] = []

    def ejecutar_select(self, cliente_id: int, sql: str, limite: int) -> ResultadoConsulta:
        self.consultas.append((cliente_id, sql, limite))
        return ResultadoConsulta(["total"], [[42.0]], truncado=False)


class AuditoriaEnMemoria:
    def __init__(self):
        self.eventos: list[tuple[int | None, str, str, str]] = []

    def registrar(self, cliente_id, accion, detalle, resultado) -> None:
        self.eventos.append((cliente_id, accion, detalle, resultado))

    def ultimos(self, cliente_id: int, limite: int = 20) -> list[dict]:
        return [{"accion": e[1]} for e in self.eventos if e[0] == cliente_id][-limite:]

    def acciones(self) -> list[str]:
        return [e[1] for e in self.eventos]


class MovilFalso:
    """Canal OTP y bandeja del móvil en uno. `ultimo_codigo()` lee el SMS como lo haría el cliente."""

    def __init__(self):
        self.sms: dict[int, list[str]] = {}

    def enviar(self, cliente_id: int, texto: str) -> None:
        self.sms.setdefault(cliente_id, []).append(texto)

    def mensajes(self, cliente_id: int) -> list[dict]:
        return [{"remitente": "Unicaja", "texto": t, "hora": "12:00"} for t in reversed(self.sms.get(cliente_id, []))]

    def ultimo_codigo(self, cliente_id: int) -> str:
        return self.sms[cliente_id][-1].split("Código de confirmación: ")[1][:6]


class CodigosFijos:
    """Códigos predecibles para los tests (el real usa `secrets`)."""

    def __init__(self, codigo: str = "123456"):
        self.codigo = codigo
        self._n = 0

    def nuevo_id(self) -> str:
        self._n += 1
        return f"op{self._n}"

    def nuevo_codigo(self) -> str:
        return self.codigo


class AjustesEnMemoria:
    def __init__(self, ajustes: Ajustes | None = None):
        self.ajustes = ajustes or Ajustes(
            activo="groq", claves={"groq": ConfigClave("clave-falsa-groq", "modelo-a", "modelo-b", ["modelo-a", "modelo-b"])},
            fallback_local=False,
        )

    def cargar(self) -> Ajustes:
        return self.ajustes

    def guardar(self, ajustes: Ajustes) -> None:
        self.ajustes = ajustes


class SondaFalsa:
    def __init__(self, modelos: list[str] | None = None, error: Exception | None = None):
        self.modelos = modelos if modelos is not None else ["m1", "m2"]
        self.error = error

    def listar_modelos(self, proveedor: str, api_key: str | None = None) -> list[str]:
        if self.error:
            raise self.error
        return self.modelos

    def estado_ollama(self, url: str) -> EstadoOllama:
        return EstadoOllama(True, "ok", [])


class UsoEnMemoria:
    def __init__(self):
        self.registros: list[tuple[int, str, str, Uso, datetime]] = []

    def registrar(self, cliente_id, proveedor, modelo, uso, momento) -> None:
        self.registros.append((cliente_id, proveedor, modelo, uso, momento))

    def tokens_del_dia(self, cliente_id: int, dia: date) -> int:
        return sum(r[3].total for r in self.registros if r[0] == cliente_id and r[1] != "ollama" and r[4].date() == dia)

    def ultimos(self, cliente_id: int, limite: int = 10) -> list[dict]:
        return [
            {"momento": r[4].isoformat(), "modelo": r[2], "entrada": r[3].entrada, "salida": r[3].salida, "estimado": r[3].estimado}
            for r in reversed(self.registros) if r[0] == cliente_id
        ][:limite]


class LLMGuionizado:
    """LLM de mentira: cada llamada a `completar` consume un paso del guion.

    Un paso es una lista de eventos, o una excepción que se lanza al empezar. Cada llamada informa
    de `uso` tokens al terminar (por defecto, 100 de entrada y 50 de salida).
    """

    def __init__(self, *pasos, uso: Uso = Uso(100, 50)):
        self.pasos = list(pasos)
        self.uso = uso
        self.llamadas: list[tuple[ModeloRef, list[Mensaje], Sequence[EsquemaHerramienta] | None]] = []
        self.max_tokens: list[int | None] = []

    def completar(self, modelo, mensajes, herramientas, max_tokens=None) -> Iterator:
        self.llamadas.append((modelo, list(mensajes), herramientas))
        self.max_tokens.append(max_tokens)
        paso = self.pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        yield from paso
        yield UsoTokens(self.uso)


def crear_agente(llm, herramientas, ajustes=None, uso=None, presupuesto=None, reloj=None, esperar=None) -> Agente:
    """Agente con dobles por defecto. `uso` y `reloj` se pueden pasar para inspeccionarlos."""
    kwargs = {"esperar": esperar} if esperar else {}
    return Agente(
        llm, herramientas, ajustes or AjustesEnMemoria(), uso if uso is not None else UsoEnMemoria(),
        presupuesto or PresupuestoUso(), reloj or RelojFijo(), **kwargs,
    )


def texto(*trozos: str) -> list:
    return [DeltaTexto(t) for t in trozos]


def llamada(nombre: str, argumentos: str = "{}", id: str = "c1") -> list:
    return [PeticionHerramientas((LlamadaHerramienta(id, nombre, argumentos),))]
