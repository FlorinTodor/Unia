# 💬💶 Habla con tu dinero — Reto Unicaja · UGR

Asistente bancario conversacional basado en IA generativa. Permite interactuar con
tus finanzas **por voz o por escrito** (accesible para personas que no pueden o no
quieren hablar): consultar saldo, enviar Bizum, analizar movimientos en lenguaje
natural y generar **gráficos dinámicos sin plantillas**.

## Arquitectura

```
┌───────────────┐   SSE / REST   ┌──────────────────────────────┐
│   Frontend    │ ◄────────────► │        Backend FastAPI       │
│  chat + voz   │                │                              │
│  Chart.js     │                │  Agente LLM (tool calling)   │
│  Web Speech   │                │   ├─ consultar_saldo         │
│  (TTS)        │                │   ├─ transferencia_bizum ────┼──► API bancaria ficticia
└───────────────┘                │   ├─ consultar_movimientos ──┼──► SQLite (NL → SQL)
        │ audio                  │   └─ generar_grafico ────────┼──► spec Chart.js al frontend
        ▼                        │                              │
   POST /stt ────────────────────┼──► Whisper (Groq, gratuito)  │
                                 └──────────────────────────────┘
```

- **LLM agnóstico al proveedor**: Groq, Cerebras y Ollama exponen API compatible con
  OpenAI; se cambia de proveedor con una variable de entorno (`LLM_PROVIDER`).
- **NL → SQL**: el LLM traduce la pregunta del usuario a un `SELECT` de SQLite,
  validado en el servidor (solo lectura, una sentencia, lista negra de palabras clave).
- **Gráficos sin plantillas**: el LLM razona qué tipo de gráfico conviene y emite la
  configuración Chart.js completa, que el frontend renderiza tal cual.
- **Voz**: entrada por Whisper large-v3-turbo (API gratuita de Groq, con temperatura 0,
  prompt de dominio y filtro de audio corto contra alucinaciones). Salida con doble vía:
  voces del navegador (Web Speech API) si existen, y si no —Brave/Chromium en Linux no trae
  voces— síntesis en el servidor con **Piper** (voz neuronal española local, ~0,3 s por
  frase, endpoint `POST /tts`). Ambas son opcionales: el chat escrito funciona siempre.
  Para descargar la voz: `python -m piper.download_voices es_ES-sharvard-medium --data-dir data/voces`
- **Latencia**: streaming SSE token a token + inferencia en Groq (~300-800 tok/s).

## Análisis de proveedores LLM (resumen)

| Proveedor | Modelo | Coste | Velocidad | Límite gratuito | Rol |
|---|---|---|---|---|---|
| **Groq** | Llama 3.3 70B | Gratis | ★★★★★ | 1.000 req/día · 100k tokens/día | **Principal** (+ Whisper STT) |
| **Groq** | GPT-OSS 120B | Gratis | ★★★★★ | cuota diaria independiente | **Fallback 1** (misma clave) |
| **Ollama local** | Qwen3 8B | Gratis | ★★★ | Sin límite | **Fallback 2** (offline) |
| Cerebras | GPT-OSS 120B | — | ★★★★★ | requiere activar facturación | Descartado (ya no hay free tier de API) |
| Google AI Studio | Gemini Flash | Gratis | ★★★★ | 20 req/día (modelos top) | Descartado (límites + privacidad) |
| OpenRouter | varios | Gratis | ★★★ | 50 req/día | Descartado (límites) |

Se eligió una **cadena de fallback automática** (los límites diarios de Groq son por
modelo, así que un segundo modelo de la misma clave es un fallback real): si un
proveedor devuelve 429 o falla la red, el agente salta al siguiente eslabón *en el
mismo mensaje* y avisa al usuario. Medido: ~3 s por turno incluso con el principal agotado.

### Control de latencia y consumo de tokens

- **Compactación de historial**: los resultados SQL y las configs de gráficos de turnos
  antiguos se eliminan del contexto (~90% menos tokens por petición).
- Consultas SQL con tope de 60 filas + instrucción de usar agregaciones (los gráficos
  usan datos agregados: un año completo son ~12 filas, no cientos).
- Modelos razonadores con el razonamiento al mínimo (`reasoning_effort`): en el
  fallback local reduce la latencia de ~13 s a ~2-3 s.

## Puesta en marcha

```bash
# 1. Dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configuración
cp .env.example .env
# Edita .env y pon tu GROQ_API_KEY (gratis en https://console.groq.com/keys)

# 3. Arrancar
uvicorn backend.main:app --reload
# Abre http://localhost:8000
```

La base de datos ficticia (`data/banco.db`, ~12 meses de movimientos realistas) se
genera automáticamente al arrancar.

### Fallback local con Ollama

```bash
ollama pull qwen3:4b   # (o qwen3:8b si tu GPU tiene VRAM suficiente)
# En .env: LLM_PROVIDER=ollama
```

## Ejemplos de uso

- «¿Cuánto dinero tengo?»
- «¿Cuánto gasté en supermercados en junio?»
- «Envíale 20 € a María por la cena» → el asistente pide confirmación → «sí»
- «Hazme un gráfico de mis gastos por categoría de los últimos 3 meses»
- «¿Cómo ha evolucionado mi gasto mensual este año?» (gráfico de líneas autónomo)

## Estructura del proyecto

Arquitectura hexagonal (detalle en `docs/ARQUITECTURA.md`): las dependencias apuntan siempre
hacia dentro, y `tests/test_arquitectura.py` lo verifica.

```
backend/
  dominio/       # reglas y entidades puras (tope Bizum, SQL de solo lectura, cadena de fallback)
  aplicacion/    # casos de uso, agente, registro de herramientas y puertos (interfaces)
  adaptadores/
    entrada/http/  # FastAPI: chat SSE, voz, API bancaria, ajustes
    salida/        # SQLite, LLM OpenAI-compatible, Whisper, Piper, ajustes, sesiones
  composicion.py # único sitio que conecta puertos con adaptadores
  main.py        # uvicorn backend.main:app
frontend/
  index.html, styles.css
  js/{api,aplicacion,dispositivos,ui}/   # módulos ES: chat SSE, voz, panel de ajustes, Chart.js
tests/           # ~200 pruebas sin red (incluye seguridad y aislamiento): python -m pytest -q
pruebas/         # demo + batería contra la app en marcha (usa el LLM real)
```
