"""Adaptador del puerto ProveedorLLM sobre cualquier API compatible con OpenAI (streaming)."""
import json
import re
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
    LimitePorMinuto,
    ModeloNoEncontrado,
    PeticionHerramientas,
    ProveedorInaccesible,
    UsoTokens,
)
from ....dominio.modelos import LlamadaHerramienta, Mensaje
from ....dominio.proveedores import OLLAMA, ModeloRef
from ....dominio.uso import Uso, estimar_tokens
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


# proveedores que aceptan `stream_options.include_usage` (el resto se estima a partir del texto)
_INFORMAN_USO = {"groq", "openai", "ollama", "openrouter", "mistral", "cerebras"}


def _uso_informado(chunk) -> Uso | None:
    """Tokens reales que informa el proveedor en el último fragmento (`usage`, o `x_groq.usage` en Groq)."""
    uso = getattr(chunk, "usage", None)
    if uso is None:
        extra = getattr(chunk, "model_extra", None) or {}
        uso = (extra.get("x_groq") or {}).get("usage")
        if isinstance(uso, dict):
            return Uso(int(uso.get("prompt_tokens", 0)), int(uso.get("completion_tokens", 0)))
        return None
    return Uso(int(uso.prompt_tokens or 0), int(uso.completion_tokens or 0))


_RE_ESPERA = re.compile(r"try again in (\d+(?:\.\d+)?)\s*(ms|s)\b", re.IGNORECASE)


def _segundos_de_espera(texto_error: str) -> float | None:
    """Groq dice «Please try again in 4.2s»: se aprovecha para esperar justo lo necesario."""
    m = _RE_ESPERA.search(texto_error)
    if not m:
        return None
    return float(m.group(1)) / (1000 if m.group(2).lower() == "ms" else 1)


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
        max_tokens: int | None = None,
    ) -> Iterator[EventoLLM]:
        peticion: dict = {
            "model": modelo.modelo,
            "messages": [_a_api(m) for m in mensajes],
            "stream": True,
            **_extra_params(modelo.proveedor, modelo.modelo),
        }
        if modelo.proveedor in _INFORMAN_USO:
            peticion["stream_options"] = {"include_usage": True}
        if max_tokens:
            # los razonadores de OpenAI exigen max_completion_tokens; el resto, max_tokens
            razonador = modelo.proveedor == "openai" and modelo.modelo.startswith(("gpt-5", "o1", "o3", "o4"))
            peticion["max_completion_tokens" if razonador else "max_tokens"] = max_tokens
        if herramientas:
            peticion["tools"] = [_herramienta_a_api(h) for h in herramientas]
            peticion["tool_choice"] = "auto"

        acumuladas: dict[int, dict] = {}
        generado: list[str] = []
        informado: Uso | None = None
        try:
            # el try cubre también el consumo del stream: los errores de generación
            # (p. ej. JSON de herramienta inválido) llegan en mitad del streaming
            stream = self._clientes.cliente(modelo.proveedor).chat.completions.create(**peticion)
            for chunk in stream:
                informado = _uso_informado(chunk) or informado
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    generado.append(delta.content)
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
            texto_error = str(e).lower()
            if "per minute" in texto_error or "tpm" in texto_error or "rpm" in texto_error:
                raise LimitePorMinuto(str(e), _segundos_de_espera(str(e))) from e
            raise CuotaAgotada(str(e)) from e
        except (APIConnectionError, InternalServerError) as e:
            raise ProveedorInaccesible(str(e)) from e
        except APIError as e:
            raise GeneracionFallida(str(e)) from e

        if informado is None:  # el proveedor no informa: se estima a partir de lo enviado y lo recibido
            enviado = json.dumps(peticion["messages"] + peticion.get("tools", []), ensure_ascii=False)
            recibido = "".join(generado) + "".join(ll["args"] for ll in acumuladas.values())
            informado = Uso(estimar_tokens(enviado), estimar_tokens(recibido), estimado=True)
        yield UsoTokens(informado)
        if acumuladas:
            yield PeticionHerramientas(tuple(
                LlamadaHerramienta(ll["id"] or f"call_{i}", ll["name"], ll["args"] or "{}")
                for i, ll in sorted(acumuladas.items())
            ))
