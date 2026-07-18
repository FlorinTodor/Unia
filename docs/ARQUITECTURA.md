# Arquitectura — «Habla con tu dinero»

Asistente bancario conversacional (Reto Unicaja · UGR). Backend FastAPI + frontend
vanilla JS. Todo en español, todo probado contra la app real.

## Mapa de ficheros

| Fichero | Responsabilidad |
|---|---|
| `backend/config.py` | Proveedores LLM (Groq/Cerebras/Ollama, todos API OpenAI-compatible), cliente por proveedor, **cadena de fallback** `cadena_llm()`, cliente STT |
| `backend/db.py` | SQLite (`data/banco.db`): esquema, **generador de movimientos ficticios** (semilla fija 42, ~360 movs/año), operaciones (saldo, bizum, contactos) y `ejecutar_select()` con validación de SQL |
| `backend/banco_api.py` | API bancaria ficticia REST (`/api/banco/*`): saldo, contactos, bizum, movimientos |
| `backend/herramientas.py` | Esquemas JSON de las 5 herramientas (function calling) + `ejecutar()` que las despacha |
| `backend/agente.py` | System prompt (10 normas) y `responder()`: **bucle del agente** con streaming, tool calling, fallback de proveedor y reintentos |
| `backend/main.py` | Servidor: `/chat` (SSE), `/stt` (Whisper), `/tts` (Piper), `/estado`, estáticos; sesiones en memoria; **compactación de historial**; normalización de números para voz; saneado de caracteres invisibles |
| `frontend/index.html` | Página única; CDNs: Chart.js, marked, DOMPurify |
| `frontend/app.js` | Chat SSE, micrófono (MediaRecorder→`/stt`), TTS dual (navegador→`/tts`), render de markdown y gráficos |
| `frontend/styles.css` | Tema oscuro, burbujas, tablas, tarjetas de gráfico, animación de grabación |
| `data/banco.db` | BD generada al arrancar si no existe (gitignored) |
| `data/voces/` | Modelo Piper `es_ES-sharvard-medium` (gitignored; se descarga con `python -m piper.download_voices`) |

## Flujo de un mensaje de chat

```
navegador                    backend                              proveedor LLM
   │ POST /chat {session_id, mensaje}
   ├────────────────────────►│
   │                         │ compactar historial (quita tool-traffic viejo)
   │                         │ agente.responder() ──────────────► stream chat.completions
   │                         │   ◄─ deltas de texto / tool_calls ─┘
   │  SSE: {tipo, dato}      │   ejecuta herramientas (db.py)
   │◄────────────────────────│   repite hasta respuesta final (máx 6 rondas útiles)
   │ render en vivo          │
```

### Protocolo SSE (`/chat`)

Cada evento es `data: {"tipo": ..., "dato": ...}\n\n`:

| tipo | dato | uso en frontend |
|---|---|---|
| `delta` | fragmento de texto | streaming en la burbuja |
| `herramienta` | nombre de la herramienta | estado «⚙️ Consultando saldo…» (efímero) |
| `aviso` | texto | nota «ℹ️» persistente (cambio de proveedor) |
| `grafico` | `{titulo, config}` (config Chart.js completa) | tarjeta con canvas + `new Chart()` |
| `fin` | texto completo final | reemplaza burbuja, dispara TTS |
| `error` | mensaje | burbuja «⚠️» |

## Las 5 herramientas (function calling)

| Herramienta | Qué hace | Implementación |
|---|---|---|
| `consultar_saldo` | saldo, IBAN, titular | `db.obtener_saldo()` |
| `listar_contactos_bizum` | agenda Bizum | `db.listar_contactos()` |
| `transferencia_bizum` | envía Bizum (requiere confirmación previa del usuario, por prompt) | `db.transferir_bizum()` — valida contacto, saldo, tope 1.000 € |
| `consultar_movimientos` | **NL→SQL**: el LLM escribe un SELECT de SQLite | `db.ejecutar_select()` — solo SELECT/WITH, una sentencia, lista negra de palabras, conexión read-only, tope 60 filas |
| `generar_grafico` | el LLM emite la config Chart.js completa (tipo, datos, opciones) | evento SSE `grafico`; el backend solo valida que haya `type` y `data` — **sin plantillas** |

## Cadena de fallback LLM

`config.cadena_llm()` → se recorre en `agente.responder()` ante 429/red/5xx, **sin
consumir rondas** y avisando por SSE:

1. `llama-3.3-70b-versatile` (Groq) — principal
2. `openai/gpt-oss-120b` (Groq, `reasoning_effort="low"`) — cuota diaria independiente
3. `qwen3:8b` (Ollama local, `extra_body={"reasoning_effort": "none"}` ≡ sin thinking)

Errores de generación (p. ej. JSON de herramienta inválido) → hasta 2 reintentos
silenciosos con el mismo proveedor. Rondas agotadas → última llamada sin herramientas
para resumir lo conseguido.

## Voz

- **Entrada**: MediaRecorder (webm) → `POST /stt` → Whisper `large-v3-turbo` en Groq
  (`language=es`, `temperature=0`, prompt de dominio bancario; audio <4000 bytes se
  rechaza — anti-alucinación).
- **Salida**: `frontend/app.js::leerEnVozAlta()` — voces del navegador si existen;
  si no (Chrome en Linux no trae), `POST /tts` → Piper local. Antes de sintetizar,
  `main._normalizar_para_voz()` convierte números a palabras con num2words (Piper los
  lee dígito a dígito); >7 dígitos (teléfonos/IBAN) se dejan tal cual. Las tablas y el
  código NO se leen: el frontend filtra líneas que empiezan por `|` o ```` ``` ````.
- Velocidad: `TTS_LENGTH_SCALE` (0.78 por defecto; menor = más rápido).

## Base de datos

```sql
cuenta(iban, titular, saldo)
movimientos(id AUTOINCREMENT, fecha 'YYYY-MM-DD', categoria, concepto, comercio,
            importe)  -- negativo = gasto; fecha SIN hora → desempatar con id
contactos_bizum(nombre, telefono)
```

Generación: `db.inicializar()` al arrancar solo si `data/banco.db` no existe
(`forzar=True` para reset — borra los Bizum hechos en runtime). Perfil realista:
nómina 1.850 €/mes, alquiler, suscripciones, supermercados, Bizum, etc. Sin fechas
futuras. Categorías: Nómina, Vivienda, Suscripciones, Deporte, Supermercado,
Restaurantes, Transporte, Ropa, Ocio, Salud, Compras online, Bizum.

## Variables de entorno (`.env`)

| Variable | Por defecto | Uso |
|---|---|---|
| `LLM_PROVIDER` | `groq` | proveedor principal (`groq`/`cerebras`/`ollama`) |
| `GROQ_API_KEY` | — | LLM principal + Whisper (sin ella no hay voz de entrada) |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | modelo principal |
| `GROQ_MODEL_FALLBACK` | `openai/gpt-oss-120b` | 2º eslabón |
| `OLLAMA_MODEL` / `OLLAMA_URL` | `qwen3:8b` / `localhost:11434/v1` | fallback local |
| `CEREBRAS_API_KEY` | — | opcional (requiere facturación activa) |
| `MODELO_STT` | `whisper-large-v3-turbo` | transcripción |
| `TTS_LENGTH_SCALE` | `0.78` | velocidad de la voz Piper |

## Arranque

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload     # http://localhost:8000
```
