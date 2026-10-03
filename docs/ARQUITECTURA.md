# Arquitectura — «Habla con tu dinero»

Asistente bancario conversacional (Reto Unicaja · UGR). Backend FastAPI con arquitectura hexagonal + frontend
JS vanilla en módulos ES. Todo en español, todo probado contra la app real.

## Arquitectura hexagonal (puertos y adaptadores)

La regla única: **las dependencias apuntan hacia dentro**. El negocio no sabe que existen
FastAPI, SQLite, Groq ni Piper; son detalles intercambiables que se enchufan por «puertos».

```
                    ┌─────────────────────────────────────────────────────┐
  HTTP / SSE        │  APLICACIÓN                                         │      SQLite
  (FastAPI)  ─────► │   ServicioChat → Agente → RegistroHerramientas      │ ◄──── (repositorios)
  adaptadores/      │   casos de uso: saldo · bizum · movimientos · voz   │      LLM OpenAI-compat.
  entrada           │   ajustes · estado                                  │ ◄──── (cadena fallback)
                    │        ▲ puertos (Protocol)  ▲                      │      Whisper · Piper
                    │  ┌─────┴──────────────────────┴─────┐              │ ◄──── ajustes.json
                    │  │ DOMINIO: modelos, reglas, errores│              │      sesiones en memoria
                    │  └──────────────────────────────────┘              │      adaptadores/salida
                    └─────────────────────────────────────────────────────┘
                                composicion.py  (único que lo cablea todo)
```

| Capa | Carpeta | Qué contiene | Puede importar |
|---|---|---|---|
| **Dominio** | `backend/dominio/` | Entidades (`Cuenta`, `Movimiento`, `Mensaje`…), reglas (`TOPE_BIZUM`, validación de SQL de solo lectura), errores de negocio, `Ajustes` + cadena de fallback, catálogo de proveedores | nada |
| **Aplicación** | `backend/aplicacion/` | Casos de uso, agente, servicio de chat, registro de herramientas, prompt, y los **puertos** (`puertos/`) | dominio |
| **Adaptadores de entrada** | `backend/adaptadores/entrada/http/` | Routers FastAPI, protocolo SSE, presentadores JSON, mapeo error→HTTP | dominio, aplicación |
| **Adaptadores de salida** | `backend/adaptadores/salida/` | SQLite, cliente OpenAI-compatible, Whisper, Piper, ajustes JSON, sesiones | dominio, aplicación |
| **Composición** | `backend/composicion.py` | Crea los adaptadores, los inyecta en los casos de uso y construye la app | todo |

Se comprueba automáticamente: `tests/test_arquitectura.py` analiza los imports de cada
módulo y falla si el dominio importa la aplicación, si la aplicación importa un adaptador,
si una entrada conoce una salida, o si dominio/aplicación usan `fastapi`, `openai`, `sqlite3`…

### Puertos (qué necesita la aplicación del mundo exterior)

| Puerto | Fichero | Adaptador que lo implementa |
|---|---|---|
| `RepositorioCuenta`, `RepositorioContactos`, `ConsultorMovimientos` | `puertos/banco.py` | `salida/sqlite/repositorios.py` |
| `ProveedorLLM` (+ errores del puerto) | `puertos/llm.py` | `salida/llm/openai_compat.py` |
| `Transcriptor`, `Sintetizador` | `puertos/voz.py` | `salida/voz/whisper.py`, `salida/voz/piper.py` |
| `RepositorioSesiones`, `RepositorioAjustes`, `Reloj`, `SondaProveedores` | `puertos/infraestructura.py` | `salida/persistencia/*`, `salida/reloj.py`, `salida/llm/sonda.py` |

### Mapa de ficheros

```
backend/
  main.py                      # solo: app = crear_aplicacion()
  composicion.py               # raíz de composición (inyección de dependencias manual)
  dominio/
    modelos.py                 # Cuenta, Contacto, Movimiento, Mensaje, LlamadaHerramienta…
    reglas.py                  # tope Bizum, saldo suficiente, validar_consulta_solo_lectura
    errores.py                 # ErrorDeValidacion / ErrorNoEncontrado / ErrorNoDisponible…
    ajustes.py                 # Ajustes + cadena_llm() + transcripcion()
    proveedores.py             # catálogo (Groq, Gemini, OpenAI…) y modelos Whisper
  aplicacion/
    agente.py                  # bucle de tool calling + fallback + reintentos (sin SDK)
    chat.py                    # ServicioChat: sesión, compactación, saneado, errores
    prompt.py                  # system prompt (10 normas)
    texto.py                   # limpiar invisibles, normalizar números para voz
    eventos.py                 # Delta, HerramientaEnUso, Aviso, Grafico, Fin, ErrorChat
    puertos/                   # interfaces
    casos_uso/                 # banco, voz, ajustes, estado, graficos
    herramientas/              # registro.py + saldo, contactos, bizum, movimientos, grafico
  adaptadores/
    entrada/http/              # app.py, rutas_chat/banco/ajustes.py, sse.py, presentadores.py
    salida/                    # sqlite/, llm/, voz/, persistencia/, reloj.py
tests/                         # 100 pruebas sin red: dominio, casos de uso, agente, SQLite, HTTP, arquitectura
frontend/
  index.html, styles.css
  js/main.js                   # composición del frontend
  js/api/                      # adaptadores hacia el backend (http, chat SSE, voz, ajustes, estado)
  js/aplicacion/conversacion.js# caso de uso: enviar mensaje y reflejar cada evento SSE
  js/dispositivos/             # micrófono, altavoz, preferencias (APIs del navegador)
  js/ui/                       # vista_chat, cabecera, panel_ajustes, dom
```

### Cómo se amplía

- **Nueva herramienta del agente**: crear `aplicacion/herramientas/<nombre>.py` (esquema +
  función + etiqueta + riesgo) y añadirla a la lista de `composicion.py`. El agente y el
  frontend no cambian (la etiqueta «⚙️ Consultando…» viaja en el evento SSE).
- **Cambiar de base de datos**: nuevo adaptador que cumpla los puertos de `puertos/banco.py`.
- **Otro proveedor de voz o de LLM**: nuevo adaptador del puerto correspondiente.
- **Otra interfaz** (CLI, MCP, WhatsApp…): nuevo adaptador de entrada que llame a los mismos casos de uso.

## Flujo de un mensaje de chat

```
navegador          adaptador HTTP         aplicación                    adaptador LLM
   │ POST /chat ───►│ rutas_chat           │                                  │
   │                │──► ServicioChat.enviar(sesión, texto)                   │
   │                │      carga/crea sesión (RepositorioSesiones), compacta  │
   │                │      Agente.responder ──────────► ProveedorLLM.completar ┤──► API del proveedor
   │                │         ◄── DeltaTexto / PeticionHerramientas ◄──────────┘
   │                │         RegistroHerramientas.ejecutar → casos de uso → repositorios
   │ SSE ◄──────────│◄── Delta · HerramientaEnUso · Grafico · Aviso · Fin · ErrorChat
```

### Protocolo SSE (`/chat`)

Cada evento es `data: {"tipo": ..., "dato": ...}\n\n`:

| tipo | dato | uso en frontend |
|---|---|---|
| `delta` | fragmento de texto | streaming en la burbuja |
| `herramienta` | nombre (+ `etiqueta` legible) | estado «⚙️ Consultando saldo…» (efímero) |
| `aviso` | texto | nota «ℹ️» persistente (cambio de proveedor) |
| `grafico` | `{titulo, config}` (config Chart.js completa) | tarjeta con canvas + `new Chart()` |
| `fin` | texto completo final | reemplaza burbuja, dispara TTS |
| `error` | mensaje legible (los errores inesperados se registran en el log y no se detallan al cliente) | burbuja «⚠️» |

### Errores

Los casos de uso lanzan errores de dominio (`ErrorDeValidacion`, `ErrorNoEncontrado`,
`ErrorNoDisponible`) con mensaje legible. Cada adaptador los traduce a su idioma: HTTP
(422 / 404 / 503), SSE (`tipo: error`) o `{"ok": false, "error": …}` cuando quien pregunta es
el LLM, para que se explique al usuario. Los errores de los SDK se traducen en el adaptador
(`CuotaAgotada`, `ClaveInvalida`, `ProveedorInaccesible`…), de modo que el agente decide el
fallback sin importar `openai`.

## Las 5 herramientas (function calling)

| Herramienta | Qué hace | Implementación |
|---|---|---|
| `consultar_saldo` | saldo, IBAN, titular | caso de uso `ConsultarSaldo` |
| `listar_contactos_bizum` | agenda Bizum | caso de uso `ListarContactos` |
| `transferencia_bizum` | envía Bizum (requiere confirmación previa del usuario, por prompt) | caso de uso `EnviarBizum` + `dominio/reglas.py` — valida contacto, saldo, tope 1.000 € |
| `consultar_movimientos` | **NL→SQL**: el LLM escribe un SELECT de SQLite | `ConsultarMovimientos` → `reglas.validar_consulta_solo_lectura()` (solo SELECT/WITH, una sentencia, lista negra) y adaptador SQLite con conexión read-only, tope 60 filas |
| `generar_grafico` | el LLM emite la config Chart.js completa (tipo, datos, opciones) | evento SSE `grafico`; el backend solo valida que haya `type` y `data` — **sin plantillas** |

## Cadena de fallback LLM

`Ajustes.cadena_llm()` (dominio) → se recorre en `Agente.responder()` ante 429/red/5xx, **sin
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
- **Salida**: `frontend/js/dispositivos/altavoz.js::leerEnVozAlta()` — voces del navegador si existen;
  si no (Brave/Chromium en Linux no trae), `POST /tts` → Piper local. Antes de sintetizar,
  `aplicacion/texto.normalizar_para_voz()` convierte números a palabras con num2words (Piper los
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

Generación: `esquema.inicializar()` (adaptador SQLite, al arrancar) solo si `data/banco.db` no existe
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
