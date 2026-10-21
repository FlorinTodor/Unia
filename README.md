# Unia, Unicaja's banking assistant

**English** · [Español](#unia-el-asistente-de-unicaja)

> Built for the «Habla con tu dinero» (Talk to your money) challenge from the Unicaja Chair at the University of Granada.

[![Unia demo video](https://florintodor.dev/media/poster/unia.jpg)](https://florintodor.dev/en/proyectos/unia/)

**Demo video and project page:** [florintodor.dev/en/proyectos/unia](https://florintodor.dev/en/proyectos/unia/)
(the video is in Spanish)

A conversational banking assistant built on generative AI. You can handle your money
**by voice or in writing** (so it also works for people who can't or don't want to speak):
check your balance, send Bizum transfers (the Spanish instant payment system), ask about
your transactions in plain language, get **dynamic charts without templates**, and check,
block or unblock your cards. The LLM proposes and the server decides: money only moves
with an OTP code.
Technical report: [`docs/Unia_memoria_tecnica.pdf`](docs/Unia_memoria_tecnica.pdf), in Spanish
(LaTeX source in `docs/memoria_latex/`).

## Architecture

```
┌───────────────┐   SSE / REST   ┌──────────────────────────────┐
│   Frontend    │ ◄────────────► │        FastAPI backend       │
│  chat + voice │                │  login · OTP · limits        │
│  Chart.js     │                │  LLM agent (tool calling)    │
│  simulated    │                │   ├─ consultar_saldo         │
│  phone        │                │   ├─ listar_contactos_bizum  │
└───────────────┘                │   ├─ consultar_movimientos ──┼──► SQLite (NL → SQL, per-customer copy)
        │ audio                  │   ├─ generar_grafico ────────┼──► Chart.js chart to the frontend
        ▼                        │   ├─ transferencia_bizum ────┼──► pending operation + SMS with code
   POST /stt ───► Whisper (Groq) │   ├─ consultar_tarjetas      │
   POST /tts ───► OmniVoice/Piper│   ├─ bloquear_tarjeta        │
                                 │   └─ desbloquear_tarjeta ────┼──► pending operation + SMS with code
                                 └──────────────────────────────┘
```

- **Provider-agnostic LLM**: every provider exposes an OpenAI-compatible API; they are
  switched from the admin settings panel (or with `LLM_PROVIDER`).
- **NL → SQL**: the LLM turns the user's question into an SQLite `SELECT`, validated on
  the server (read-only, a single statement, a keyword blacklist).
- **Charts without templates**: the LLM decides the chart type, the title and the period.
  For the usual queries (spending by category, by month, by merchant, income against
  spending) the server computes the data; for anything else, the LLM queries the
  transactions and builds the Chart.js configuration itself, which the server validates
  and the frontend renders.
- **Voice**: input through Whisper large-v3-turbo (Groq's free API, with temperature 0,
  a domain prompt and a short-audio filter against hallucinations). Output on the server
  (`POST /tts`) with **OmniVoice** on the local GPU (optional: `requirements-voz.txt`,
  CC-BY-NC weights) and **Piper** as the fallback; the browser's voices are the last
  resort. Written chat always works. The Piper model and OmniVoice's reference voice live
  in `data/voces/`, in the repository.
- **Latency**: token-by-token SSE streaming + inference on Groq (~300-800 tok/s).

## LLM provider analysis (summary)

| Provider | Model | Cost | Speed | Free limit | Role |
|---|---|---|---|---|---|
| **Groq** | GPT-OSS 120B | Free | ★★★★★ | 8,000 tokens/min and a daily quota, per model | **Main** (+ Whisper STT) |
| **Groq** | GPT-OSS 20B | Free | ★★★★★ | separate quota | **Fallback 1** (same key) |
| **Local Ollama** | Qwen3 8B | Free | ★★★ | No limit | **Fallback 2** (offline) |
| Cerebras | GPT-OSS 120B | — | ★★★★★ | requires enabling billing | Rejected (no free API tier any more) |
| Google AI Studio | Gemini Flash | Free | ★★★★ | 20 req/day (top models) | Rejected (limits + privacy) |
| OpenRouter | various | Free | ★★★ | 50 req/day | Rejected (limits) |

The choice was an **automatic fallback chain** (Groq's daily limits are per model, so a
second model on the same key is a real fallback): if a provider returns 429 or the
network fails, the agent jumps to the next link *within the same message* and tells the
user. On a per-minute limit, instead, it waits (up to 40 s per turn) and retries with the
same model: the small one is less reliable.

### Keeping latency and token use down

- **History compaction**: SQL results and chart configs from older turns are dropped from
  the context (~90% fewer tokens per request).
- SQL queries capped at 60 rows + an instruction to use aggregations (charts use
  aggregated data: a full year is ~12 rows, not hundreds).
- Reasoning models with reasoning set to the minimum (`reasoning_effort`): on the local
  fallback it cuts latency from ~13 s to ~2-3 s.

## Getting started

```bash
# 1. Dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env
# Edit .env: CONTRASENA_ADMIN (12+ characters) for the admin profile and, if you like,
# GROQ_API_KEY (free at https://console.groq.com/keys). The key can also be pasted later
# from the settings panel, logged in as admin.

# 3. Run
uvicorn backend.main:app --reload --no-proxy-headers
# Open http://localhost:8000
```

The fictitious database (`data/banco.db`: four customers, two years of transactions) is
generated automatically on start-up. Log in as `alex`, `ana`, `marta` or `jose`; the
password is `CONTRASENA_<USER>` from `.env` or, if it isn't set, the username followed by 2026.

### Local fallback with Ollama

```bash
ollama pull qwen3:8b   # the default model (with little VRAM: qwen3:4b and OLLAMA_MODEL=qwen3:4b)
# In .env: LLM_PROVIDER=ollama
```

## Example requests

The assistant speaks Spanish:

- «¿Cuánto dinero tengo?» (How much money do I have?)
- «¿Cuánto gasté en supermercados en junio?» (How much did I spend at supermarkets in June?)
- «Envíale 20 € a María por la cena» (Send María €20 for dinner) → the assistant prepares
  the Bizum and a code arrives on the simulated phone (📱) → it is confirmed with the code
  or the fingerprint, never through the chat
- «Hazme un gráfico de mis gastos por categoría de los últimos 3 meses» (Chart my spending
  by category over the last 3 months)
- «¿Cómo ha evolucionado mi gasto mensual este año?» (How has my monthly spending changed
  this year?), an autonomous line chart

## Project structure

Hexagonal architecture (details in `docs/ARQUITECTURA.md`): dependencies always point
inwards, and `tests/test_arquitectura.py` checks it.

```
backend/
  dominio/       # pure rules and entities (Bizum limit, read-only SQL, fallback chain)
  aplicacion/    # use cases, agent, tool registry and ports (interfaces)
  adaptadores/
    entrada/http/  # FastAPI: SSE chat, voice, banking API, settings
    salida/        # SQLite, OpenAI-compatible LLM, Whisper, OmniVoice/Piper, security, state
  composicion.py # the only place that wires ports to adapters
  main.py        # uvicorn backend.main:app
frontend/
  index.html, styles.css
  js/{api,aplicacion,dispositivos,ui}/   # ES modules: SSE chat, voice, settings panel, Chart.js
tests/           # 750 offline tests (including security and isolation): python -m pytest -q
pruebas/         # demo + test battery against the running app (uses the real LLM)
```

---

# Unia, el asistente de Unicaja

[English](#unia-unicajas-banking-assistant) · **Español**

> Proyecto del reto «Habla con tu dinero» (Cátedra Unicaja · UGR).

[![Vídeo de la demo de Unia](https://florintodor.dev/media/poster/unia.jpg)](https://florintodor.dev/proyectos/unia/)

**Vídeo de la demo y ficha del proyecto:** [florintodor.dev/proyectos/unia](https://florintodor.dev/proyectos/unia/)

Asistente bancario conversacional basado en IA generativa. Permite interactuar con
tus finanzas **por voz o por escrito** (accesible para personas que no pueden o no
quieren hablar): consultar saldo, enviar Bizum, analizar movimientos en lenguaje
natural, generar **gráficos dinámicos sin plantillas** y consultar, bloquear o desbloquear tarjetas.
El LLM propone y el servidor decide: el dinero solo se mueve con un código OTP.
Memoria técnica: [`docs/Unia_memoria_tecnica.pdf`](docs/Unia_memoria_tecnica.pdf) (fuente LaTeX en `docs/memoria_latex/`).

## Arquitectura

```
┌───────────────┐   SSE / REST   ┌──────────────────────────────┐
│   Frontend    │ ◄────────────► │        Backend FastAPI       │
│  chat + voz   │                │  login · OTP · límites       │
│  Chart.js     │                │  Agente LLM (tool calling)   │
│  móvil        │                │   ├─ consultar_saldo         │
│  simulado     │                │   ├─ listar_contactos_bizum  │
└───────────────┘                │   ├─ consultar_movimientos ──┼──► SQLite (NL → SQL, copia del cliente)
        │ audio                  │   ├─ generar_grafico ────────┼──► gráfico Chart.js al frontend
        ▼                        │   ├─ transferencia_bizum ────┼──► operación pendiente + SMS con código
   POST /stt ───► Whisper (Groq) │   ├─ consultar_tarjetas      │
   POST /tts ───► OmniVoice/Piper│   ├─ bloquear_tarjeta        │
                                 │   └─ desbloquear_tarjeta ────┼──► operación pendiente + SMS con código
                                 └──────────────────────────────┘
```

- **LLM agnóstico al proveedor**: todos los proveedores exponen API compatible con OpenAI;
  se cambian en el panel de ajustes del administrador (o con `LLM_PROVIDER`).
- **NL → SQL**: el LLM traduce la pregunta del usuario a un `SELECT` de SQLite,
  validado en el servidor (solo lectura, una sentencia, lista negra de palabras clave).
- **Gráficos sin plantillas**: el LLM decide el tipo de gráfico, el título y el periodo. Para las
  consultas habituales (gastos por categoría, por mes, por comercio, ingresos frente a gastos) los
  datos los calcula el servidor; para cualquier otra, el LLM consulta los movimientos y construye
  él mismo la configuración Chart.js, que el servidor valida y el frontend renderiza.
- **Voz**: entrada por Whisper large-v3-turbo (API gratuita de Groq, con temperatura 0,
  prompt de dominio y filtro de audio corto contra alucinaciones). Salida en el servidor
  (`POST /tts`) con **OmniVoice** en la GPU local (opcional: `requirements-voz.txt`, pesos CC-BY-NC)
  y **Piper** de reserva; las voces del navegador quedan como último recurso. El chat escrito
  funciona siempre. El modelo de Piper y la voz de referencia de OmniVoice van en `data/voces/`, en el repositorio.
- **Latencia**: streaming SSE token a token + inferencia en Groq (~300-800 tok/s).

## Análisis de proveedores LLM (resumen)

| Proveedor | Modelo | Coste | Velocidad | Límite gratuito | Rol |
|---|---|---|---|---|---|
| **Groq** | GPT-OSS 120B | Gratis | ★★★★★ | 8.000 tokens/min y cuota diaria, por modelo | **Principal** (+ Whisper STT) |
| **Groq** | GPT-OSS 20B | Gratis | ★★★★★ | cuota independiente | **Fallback 1** (misma clave) |
| **Ollama local** | Qwen3 8B | Gratis | ★★★ | Sin límite | **Fallback 2** (offline) |
| Cerebras | GPT-OSS 120B | — | ★★★★★ | requiere activar facturación | Descartado (ya no hay free tier de API) |
| Google AI Studio | Gemini Flash | Gratis | ★★★★ | 20 req/día (modelos top) | Descartado (límites + privacidad) |
| OpenRouter | varios | Gratis | ★★★ | 50 req/día | Descartado (límites) |

Se eligió una **cadena de fallback automática** (los límites diarios de Groq son por
modelo, así que un segundo modelo de la misma clave es un fallback real): si un
proveedor devuelve 429 o falla la red, el agente salta al siguiente eslabón *en el
mismo mensaje* y avisa al usuario. Ante un límite por minuto, en cambio, espera (hasta 40 s por turno)
y reintenta con el mismo modelo: el pequeño es menos fiable.

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
# Edita .env: CONTRASENA_ADMIN (12+ caracteres) para el perfil de administración y, si quieres,
# GROQ_API_KEY (gratis en https://console.groq.com/keys). La clave también puede pegarse después
# desde el panel de ajustes entrando como admin.

# 3. Arrancar
uvicorn backend.main:app --reload --no-proxy-headers
# Abre http://localhost:8000
```

La base de datos ficticia (`data/banco.db`: cuatro clientes, dos años de movimientos) se
genera automáticamente al arrancar. Entrar con `alex`, `ana`, `marta` o `jose`; la contraseña es
`CONTRASENA_<USUARIO>` de `.env` o, si no existe, el usuario seguido de 2026.

### Fallback local con Ollama

```bash
ollama pull qwen3:8b   # el modelo por defecto (con poca VRAM: qwen3:4b y OLLAMA_MODEL=qwen3:4b)
# En .env: LLM_PROVIDER=ollama
```

## Ejemplos de uso

- «¿Cuánto dinero tengo?»
- «¿Cuánto gasté en supermercados en junio?»
- «Envíale 20 € a María por la cena» → el asistente prepara el Bizum y llega un código al móvil
  simulado (📱) → se confirma con el código o con la huella, nunca a través del chat
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
    salida/        # SQLite, LLM OpenAI-compatible, Whisper, OmniVoice/Piper, seguridad, estado
  composicion.py # único sitio que conecta puertos con adaptadores
  main.py        # uvicorn backend.main:app
frontend/
  index.html, styles.css
  js/{api,aplicacion,dispositivos,ui}/   # módulos ES: chat SSE, voz, panel de ajustes, Chart.js
tests/           # 750 pruebas sin red (incluye seguridad y aislamiento): python -m pytest -q
pruebas/         # demo + batería contra la app en marcha (usa el LLM real)
```
