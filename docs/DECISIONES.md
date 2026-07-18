# Registro de decisiones técnicas

Formato: contexto → decisión → motivo. Fechas de julio de 2026. Este registro es la
base del apartado de diseño de la memoria del reto.

## 1. Estrategia de IA generativa: híbrido API gratuita + local (18-jul)

**Contexto.** El reto puntúa precisión de consultas NL (30 pts), latencia (15) y
calidad conversacional (15). Hardware disponible: RTX 3060 Laptop 6 GB VRAM.
Se analizaron: Ollama local, Groq, Cerebras, Google AI Studio, OpenRouter
(fuente: repo *free-llm-api-resources*).

**Decisión.** Groq como principal (Llama 3.3 70B) + Ollama local como fallback,
con capa de abstracción de proveedor (todos exponen API OpenAI-compatible: cambiar
proveedor = cambiar `base_url` + modelo).

**Motivo.** Un 70B es muy superior a los 7-8B locales en function calling y NL→SQL
(donde están los 30 pts); Groq es la inferencia más rápida disponible (~300-800 tok/s,
clave para latencia) y su tier gratuito basta. Local de respaldo: demo sin internet.
Descartados: AI Studio (20 req/día en modelos top, usa datos para entrenar),
OpenRouter (50 req/día).

## 2. Cadena de fallback de 3 eslabones (18-jul)

**Contexto.** El tier gratuito de Groq resultó tener límites POR MODELO:
70B = 12k tokens/min y 100k tokens/DÍA (se agotó el primer día de pruebas).
La clave de Cerebras del usuario devuelve `payment_required` en todos los modelos
(eliminaron el free tier de API).

**Decisión.** Cadena automática: 70B (Groq) → `openai/gpt-oss-120b` (Groq, cuota
diaria independiente) → `qwen3:8b` (local). El salto ocurre en el mismo mensaje,
sin reintentos con espera (`max_retries=0`), avisando al usuario («ℹ️»). Cerebras
queda configurado pero fuera de la cadena.

**Motivo.** Un segundo modelo del mismo proveedor es un fallback real (cuotas
independientes) sin necesitar otra clave. Esperar los backoffs del cliente producía
latencias de 15-30 s; saltar de eslabón tarda milisegundos.

## 3. Voz de entrada: Whisper vía Groq (no Web Speech API) (18-jul)

**Decisión del usuario.** STT con `whisper-large-v3-turbo` (misma API key de Groq);
TTS del navegador para la salida. Requisito propio: la app debe funcionar 100 % por
escrito (accesibilidad: personas mudas o que no quieran hablar en público).

**Motivo.** Whisper transcribe mejor que el SpeechRecognition del navegador
(que además depende de Google y no funciona en todos los navegadores).

**Endurecimiento posterior:** `temperature=0`, prompt de dominio bancario y rechazo
de audios <0,5 s — Whisper alucina frases con silencio (caso real: «¿Hvað er misal,
doctor?»).

## 4. Voz de salida dual: navegador + Piper en servidor (18-jul)

**Contexto.** En el equipo del usuario (Ubuntu + Chrome) no sonaba nada:
Chrome en Linux no trae voces de `speechSynthesis` (falla en silencio).

**Decisión.** Doble vía: voces del navegador si existen; si no, `POST /tts` con
**Piper** (`es_ES-sharvard-medium`, local, ~0,3 s/frase). Números convertidos a
palabras con num2words antes de sintetizar (Piper los lee dígito a dígito);
velocidad por `TTS_LENGTH_SCALE=0.78`; las tablas no se leen en voz alta, solo la
prosa (norma de prompt: toda tabla lleva conclusión en prosa).

**Motivo.** Piper es local y gratuito (coherente con el enfoque offline del fallback),
con calidad neuronal decente. Alternativas descartadas: PlayAI TTS de Groq (sin
español), edge-tts (endpoint no oficial de Microsoft, riesgo el día de la demo).

## 5. NL→SQL directo con validación (no consultas predefinidas) (18-jul)

**Decisión.** El LLM escribe SQL de SQLite libremente contra el esquema (que va en el
system prompt); el servidor valida: solo SELECT/WITH, una sentencia, lista negra de
palabras clave, conexión de solo lectura y tope de 60 filas.

**Motivo.** Los 30 pts de «consultas precisas en lenguaje natural» exigen flexibilidad
total (cualquier combinación de fechas/categorías/agregaciones). Consultas predefinidas
no escalan a preguntas libres. El riesgo de SQL se neutraliza con la validación +
read-only (los datos además son ficticios).

## 6. Gráficos: el LLM emite la config Chart.js completa — sin plantillas (18-jul)

**Decisión.** La herramienta `generar_grafico` recibe del LLM la configuración
Chart.js entera (tipo, datos, colores, opciones). El backend solo valida que exista
`type` y `data`; el frontend la renderiza tal cual.

**Motivo.** El reto puntúa «razonamiento autónomo» (10) y «generación sin plantillas»
(10). No hay catálogo de gráficos en el código: la evidencia es que cada gráfico sale
con estructura distinta (bar/line/pie/radar/doughnut, con o sin opciones). El prompt
solo da criterio («el tipo más adecuado a los datos»); si el usuario pide un tipo
explícito, se respeta.

## 7. Streaming SSE + economía de contexto (18-jul)

**Decisión.** Respuestas en streaming token a token (SSE). Historial por sesión con
**compactación**: los resultados de herramientas (filas SQL, configs de gráficos) se
eliminan de los turnos anteriores al último; solo se conserva el texto conversacional.

**Motivo.** La latencia percibida mejora radicalmente con streaming. La compactación
redujo ~90 % los tokens por petición: sin ella, un «muéstrame todos los movimientos»
(200 filas) se reenviaba en cada turno y fundió la cuota diaria en una tarde.

## 8. Datos ficticios generados con semilla fija (18-jul)

**Decisión.** Generador procedural (`db.py`) con `random.Random(42)`: un año de
movimientos realistas de un asalariado español. La BD solo se regenera si no existe.

**Motivo.** Reproducibilidad de la demo y del vídeo. Ojo: regenerar borra las
operaciones hechas en runtime (Bizums del chat) — hacerlo solo a propósito
(p. ej. justo antes de grabar el vídeo).

## 9. Guardarraíles de conversación (18-jul)

**Decisión.** Normas de system prompt: ámbito estricto (solo finanzas; cualquier otro
tema se reconduce), confirmación obligatoria antes de ejecutar un Bizum, fidelidad a
las etiquetas de la BD (no reetiquetar categorías), mes sin año = el más reciente,
«haz lo mismo con X» = replicar formato anterior, sin narración de pasos internos,
fechas con mes en palabras, tuteo, importes con 2 decimales y €.

**Motivo.** Cada norma nace de un fallo observado en pruebas reales (ver
INCIDENCIAS.md). La calidad conversacional es un criterio puntuado (15).
