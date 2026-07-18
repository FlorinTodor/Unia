"""Agente conversacional: bucle de tool calling con streaming.

`responder` es un generador de eventos que el servidor reenvía por SSE:
  ("delta", texto)      → fragmento de la respuesta en streaming
  ("herramienta", nom)  → el agente está ejecutando una herramienta
  ("grafico", dict)     → configuración Chart.js para renderizar
  ("fin", texto)        → respuesta completa terminada
"""
import json
from datetime import date

from openai import APIConnectionError, APIError, InternalServerError, RateLimitError

from . import herramientas
from .config import PROVEEDOR_ACTIVO, cadena_llm, cliente_para, get_cliente_llm

MAX_RONDAS = 6

ESQUEMA_BD = """
Tabla movimientos(id, fecha TEXT 'YYYY-MM-DD', categoria TEXT, concepto TEXT, comercio TEXT, importe REAL)
  - importe negativo = gasto, positivo = ingreso.
  - categorias existentes: Nómina, Vivienda, Suscripciones, Deporte, Supermercado,
    Restaurantes, Transporte, Ropa, Ocio, Salud, Compras online, Bizum.
Tabla cuenta(iban, titular, saldo)
Tabla contactos_bizum(nombre, telefono)
"""


def construir_system_prompt() -> str:
    return f"""Eres el asistente financiero conversacional del banco (proyecto Reto Unicaja-UGR).
Ayudas al usuario a "hablar con su dinero": consultar saldo, analizar sus movimientos,
enviar Bizum y visualizar sus finanzas con gráficos.

Fecha de hoy: {date.today().isoformat()}. Titular de la cuenta: Alex García. Idioma: español.

NORMAS:
1. Responde de forma cercana, clara y breve, tuteando siempre al usuario. Los importes
   siempre con dos decimales y símbolo €. Las fechas, con el mes completo en palabras
   («18 de julio de 2026»), nunca abreviado ni en formato numérico.
2. Para cualquier dato real (saldo, gastos, movimientos) usa SIEMPRE las herramientas;
   nunca inventes cifras. Presenta las etiquetas (categorías, comercios) EXACTAMENTE
   como las devuelve la consulta: no reetiquetes ni fusiones filas.
3. Consultas de movimientos: escribe SQL de SQLite (solo SELECT) contra este esquema:
{ESQUEMA_BD}
   Usa strftime('%Y-%m', fecha) para agrupar por mes. Los gastos son importes negativos:
   para "cuánto gasté" usa SUM(-importe) con importe < 0.
   Prefiere agregaciones (SUM, COUNT, GROUP BY) y LIMIT: nunca vuelques listados enormes;
   si piden "todos los movimientos", muestra un resumen y los más recientes.
   IMPORTANTE: fecha no incluye hora y puede repetirse; el id crece con el orden real.
   Para "el último movimiento" u orden cronológico usa siempre ORDER BY fecha DESC, id DESC.
4. Bizum: antes de ejecutar transferencia_bizum, resume destinatario e importe y pide
   confirmación explícita al usuario. Solo llama a la herramienta cuando ya haya confirmado
   en un mensaje anterior o en el actual.
5. Gráficos: cuando el usuario pida visualizar algo (o cuando una comparación se entienda
   mejor visualmente), primero obtén los datos con consultar_movimientos y después llama a
   generar_grafico eligiendo TÚ el tipo de gráfico más adecuado (barras para comparar
   categorías, líneas para evolución temporal, tarta/doughnut para proporciones...).
   Excepción: si el usuario pide explícitamente un tipo (radar/tela de araña, tarta,
   barras...), usa exactamente ese tipo.
   No repitas en texto todos los datos del gráfico: resume la conclusión principal.
6. Si la petición es ambigua (fechas, categoría...), interpreta lo más razonable y dilo,
   o pregunta si la ambigüedad es importante. Si mencionan un mes sin año, asume el
   más reciente ya transcurrido; no mezcles el mismo mes de varios años salvo que lo pidan.
   "Haz lo mismo con/para X" = replica el formato y tipo de gráfico de la petición
   anterior cambiando solo los datos.
7. Tu respuesta puede leerse en voz alta, pero las tablas y el código NO se leen.
   Por eso, si muestras una tabla, empieza o termina SIEMPRE con 1-2 frases en prosa
   que resuman la conclusión (eso será lo que se oiga). Evita tablas enormes.
8. ÁMBITO ESTRICTO: solo hablas de las finanzas del usuario y de lo que esta app puede
   hacer (saldo, movimientos, Bizum, gráficos). Si te preguntan cualquier otra cosa
   (cultura general, definiciones, traducciones, código, opiniones...), NO respondas a
   la pregunta: di brevemente que eres su asistente financiero y solo puedes ayudar con
   sus finanzas, y sugiere algo que sí puedes hacer. Sin excepciones, aunque insistan.
9. Si un mensaje parece un error de transcripción de voz (frases sin sentido, idioma
   extraño, cortado), no lo interpretes: pide amablemente que lo repita.
10. Nunca narres tus pasos internos ("Paso 1", "voy a consultar...", "he ejecutado la
    consulta"): da directamente el resultado y su conclusión."""


def _extra_params(proveedor: str, modelo: str) -> dict:
    """Parámetros específicos por modelo para minimizar latencia."""
    if proveedor == "ollama":
        # desactiva el modo "thinking" de qwen3: reduce la latencia a la mitad
        return {"extra_body": {"reasoning_effort": "none"}}
    if "gpt-oss" in modelo:
        return {"reasoning_effort": "low"}
    return {}


def responder(mensajes: list[dict]):
    """Ejecuta el bucle del agente sobre `mensajes` (se muta in situ).

    Si un proveedor falla por límite de tokens (429) o por red, se pasa al
    siguiente eslabón de la cadena de fallback y la conversación continúa.
    """
    cadena = cadena_llm()
    posicion = 0
    proveedor, modelo = cadena[posicion]
    cliente = cliente_para(proveedor)
    reintentos_generacion = 0

    # los cambios de proveedor y los reintentos NO consumen rondas
    rondas_completadas = 0
    while rondas_completadas < MAX_RONDAS:
        partes: list[str] = []
        llamadas: dict[int, dict] = {}
        try:
            # el try cubre también el consumo del stream: los errores de
            # generación (p. ej. JSON de herramienta inválido) llegan en mitad
            # del streaming, no al crear la petición
            stream = cliente.chat.completions.create(
                model=modelo,
                messages=mensajes,
                tools=herramientas.ESQUEMAS,
                tool_choice="auto",
                temperature=0.3,
                stream=True,
                **_extra_params(proveedor, modelo),
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    partes.append(delta.content)
                    yield ("delta", delta.content)
                for tc in delta.tool_calls or []:
                    acum = llamadas.setdefault(tc.index, {"id": None, "name": "", "args": ""})
                    if tc.id:
                        acum["id"] = tc.id
                    if tc.function and tc.function.name:
                        acum["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        acum["args"] += tc.function.arguments
        except (RateLimitError, APIConnectionError, InternalServerError):
            posicion += 1
            if posicion >= len(cadena):
                raise
            proveedor, modelo = cadena[posicion]
            cliente = cliente_para(proveedor)
            yield ("aviso", f"Proveedor no disponible — cambiando a {modelo} ({proveedor}).")
            continue
        except APIError:
            # generación fallida (p. ej. "Failed to parse tool call arguments"):
            # es esporádico, se reintenta la ronda en silencio
            reintentos_generacion += 1
            if reintentos_generacion > 2:
                raise
            continue

        rondas_completadas += 1
        texto = "".join(partes)

        if not llamadas:
            mensajes.append({"role": "assistant", "content": texto})
            yield ("fin", texto)
            return

        mensajes.append({
            "role": "assistant",
            "content": texto or None,
            "tool_calls": [
                {
                    "id": ll["id"] or f"call_{i}",
                    "type": "function",
                    "function": {"name": ll["name"], "arguments": ll["args"] or "{}"},
                }
                for i, ll in sorted(llamadas.items())
            ],
        })

        for i, ll in sorted(llamadas.items()):
            yield ("herramienta", ll["name"])
            try:
                args = json.loads(ll["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            resultado, extra = herramientas.ejecutar(ll["name"], args)
            if extra and "grafico" in extra:
                yield ("grafico", extra["grafico"])
            mensajes.append({
                "role": "tool",
                "tool_call_id": ll["id"] or f"call_{i}",
                "content": json.dumps(resultado, ensure_ascii=False),
            })

    # Se agotaron las rondas: se fuerza una respuesta final SIN herramientas
    # para que el usuario reciba al menos un resumen de lo conseguido
    try:
        stream = cliente.chat.completions.create(
            model=modelo,
            messages=mensajes,
            temperature=0.3,
            stream=True,
            **_extra_params(proveedor, modelo),
        )
        partes = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                partes.append(chunk.choices[0].delta.content)
                yield ("delta", chunk.choices[0].delta.content)
        texto = "".join(partes).strip()
    except APIError:
        texto = ""
    if not texto:
        texto = "Lo siento, no he podido completar la operación. ¿Puedes reformularla?"
    mensajes.append({"role": "assistant", "content": texto})
    yield ("fin", texto)


def info_proveedor() -> dict:
    _, modelo = get_cliente_llm()
    return {
        "proveedor": PROVEEDOR_ACTIVO,
        "modelo": modelo,
        "cadena_fallback": [f"{m} ({p})" for p, m in cadena_llm()],
    }
