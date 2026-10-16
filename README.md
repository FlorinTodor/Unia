# Unia · asistente de Unicaja

> Proyecto del reto «Habla con tu dinero» (Cátedra Unicaja · UGR).

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
