"""Adaptador del puerto ProveedorLLM sobre cualquier API compatible con OpenAI (streaming)."""
from collections.abc import Iterator, Sequence

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from ....aplicacion.puertos.llm import (
    ClaveInvalida,
    CuotaAgotada,
    DeltaTexto,
    EsquemaHerramienta,
    EventoLLM,
    GeneracionFallida,
    ModeloNoEncontrado,
    PeticionHerramientas,
    ProveedorInaccesible,
)
from ....dominio.modelos import LlamadaHerramienta, Mensaje
from ....dominio.proveedores import OLLAMA, ModeloRef
from .clientes import FabricaClientes


def _extra_params(proveedor: str, modelo: str) -> dict:
    """Parámetros específicos por modelo para minimizar latencia."""
    if proveedor == OLLAMA:
        # desactiva el modo "thinking" de qwen3: reduce la latencia a la mitad
        return {"temperature": 0.3, "extra_body": {"reasoning_effort": "none"}}
    if proveedor == "openai" and modelo.startswith(("gpt-5", "o1", "o3", "o4")):
        # los razonadores de OpenAI rechazan cualquier temperatura distinta de 1
        return {"reasoning_effort": "low"}
    if "gpt-oss" in modelo and proveedor in ("groq", "cerebras"):
        return {"temperature": 0.3, "reasoning_effort": "low"}
    return {"temperature": 0.3}


def _a_api(mensaje: Mensaje) -> dict:
    if mensaje.rol == "tool":
        return {"role": "tool", "tool_call_id": mensaje.id_llamada, "content": mensaje.contenido}
    if mensaje.rol == "assistant" and mensaje.llamadas:
        return {
            "role": "assistant",
            "content": mensaje.contenido,
            "tool_calls": [
                {"id": ll.id, "type": "function", "function": {"name": ll.nombre, "arguments": ll.argumentos}}
                for ll in mensaje.llamadas
            ],
        }
    return {"role": mensaje.rol, "content": mensaje.contenido}


def _herramienta_a_api(esquema: EsquemaHerramienta) -> dict:
    return {
        "type": "function",
        "function": {"name": esquema.nombre, "description": esquema.descripcion, "parameters": esquema.parametros},
    }


class ProveedorLLMOpenAI:
    def __init__(self, clientes: FabricaClientes):
        self._clientes = clientes

    def completar(
        self,
        modelo: ModeloRef,
        mensajes: Sequence[Mensaje],
        herramientas: Sequence[EsquemaHerramienta] | None,
    ) -> Iterator[EventoLLM]:
        peticion: dict = {
            "model": modelo.modelo,
            "messages": [_a_api(m) for m in mensajes],
            "stream": True,
            **_extra_params(modelo.proveedor, modelo.modelo),
        }
        if herramientas:
            peticion["tools"] = [_herramienta_a_api(h) for h in herramientas]
            peticion["tool_choice"] = "auto"

        acumuladas: dict[int, dict] = {}
        try:
            # el try cubre también el consumo del stream: los errores de generación
            # (p. ej. JSON de herramienta inválido) llegan en mitad del streaming
            stream = self._clientes.cliente(modelo.proveedor).chat.completions.create(**peticion)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield DeltaTexto(delta.content)
                for tc in delta.tool_calls or []:
                    acum = acumuladas.setdefault(tc.index, {"id": None, "name": "", "args": ""})
                    if tc.id:
                        acum["id"] = tc.id
                    if tc.function and tc.function.name:
                        acum["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        acum["args"] += tc.function.arguments
        except AuthenticationError as e:
            raise ClaveInvalida(str(e)) from e
        except NotFoundError as e:
            raise ModeloNoEncontrado(str(e)) from e
        except RateLimitError as e:
            raise CuotaAgotada(str(e)) from e
        except (APIConnectionError, InternalServerError) as e:
            raise ProveedorInaccesible(str(e)) from e
        except APIError as e:
            raise GeneracionFallida(str(e)) from e

        if acumuladas:
            yield PeticionHerramientas(tuple(
                LlamadaHerramienta(ll["id"] or f"call_{i}", ll["name"], ll["args"] or "{}")
                for i, ll in sorted(acumuladas.items())
            ))
