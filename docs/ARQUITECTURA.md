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
| `RepositorioClientes`, `Hasheador`, `SesionesAutenticadas`, `RegistroIntentos`, `RepositorioOperaciones`, `GeneradorCodigos`, `CanalOTP`, `BandejaMovil`, `Auditoria` | `puertos/seguridad.py` | `salida/seguridad/*`, `salida/persistencia/memoria_seguridad.py`, `salida/sqlite/{repositorios,auditoria}.py` |

### Mapa de ficheros

```
backend/
  main.py                      # solo: app = crear_aplicacion()
  composicion.py               # raíz de composición (inyección de dependencias manual)
  dominio/
    modelos.py                 # Cliente, Cuenta, Contacto, Movimiento, Mensaje, LlamadaHerramienta…
    operaciones.py             # OperacionPendiente + verificación del código OTP
    acceso.py                  # bloqueo temporal tras intentos fallidos
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
    casos_uso/                 # banco, bizum (OTP), acceso, movil, voz, ajustes, estado, graficos
    herramientas/              # registro.py + saldo, contactos, bizum, movimientos, grafico
  adaptadores/
    entrada/http/              # app.py, rutas_chat/banco/ajustes.py, sse.py, presentadores.py
    salida/                    # sqlite/, llm/, voz/, persistencia/, reloj.py
tests/                         # ~200 pruebas sin red: dominio, casos de uso, agente, SQLite, HTTP, arquitectura
frontend/
  index.html, styles.css
  js/main.js                   # composición del frontend
  js/marca.js                  # nombre, lema y paleta de Unia (un solo sitio para cambiarlos)
  js/api/                      # adaptadores hacia el backend (http, auth, chat SSE, voz, banco, operaciones, uso, ajustes, estado)
  js/aplicacion/conversacion.js# caso de uso: enviar mensaje y reflejar cada evento SSE
  js/dispositivos/             # micrófono, altavoz, preferencias (APIs del navegador)
  js/ui/                       # vista_chat, panel_cuenta, sugerencias, tarjeta_operacion, movil, medidor_uso, vista_login, panel_ajustes, iconos
  fonts/                       # Manrope (OFL), servida desde el propio servidor
```

### Cómo se amplía

- **Nueva herramienta del agente**: crear `aplicacion/herramientas/<nombre>.py` (esquema +
  función + etiqueta + riesgo) y añadirla a la lista de `composicion.py`. El agente y el
  frontend no cambian (la etiqueta «⚙️ Consultando…» viaja en el evento SSE).
- **Cambiar de base de datos**: nuevo adaptador que cumpla los puertos de `puertos/banco.py`.
- **Otro proveedor de voz o de LLM**: nuevo adaptador del puerto correspondiente.
- **Otra interfaz** (CLI, MCP, WhatsApp…): nuevo adaptador de entrada que llame a los mismos casos de uso.

### Documentación de la API (OpenAPI / Swagger)

La especificación se genera sola desde los modelos de `entrada/http/esquemas.py` (con ejemplos, errores por
ruta y el esquema de seguridad `sesion`). Por seguridad **no se publica por defecto**; para verla:

```bash
DOCS_API=1 uvicorn backend.main:app     # http://localhost:8000/docs  (Swagger)  ·  /redoc  ·  /openapi.json
python pruebas/exportar_openapi.py      # escribe docs/openapi.json sin arrancar el servidor
```

En Swagger: ejecuta `POST /auth/login` con una cuenta de demostración y el resto de peticiones usan la cookie.
Solo en esas rutas se relaja la CSP (Swagger carga scripts de jsDelivr); el resto de la app mantiene la estricta.

### Guardas del agente

El agente no se fía del modelo (sobre todo del pequeño al que cae tras un límite por minuto):
- **Espera antes de bajar de modelo:** un `LimitePorMinuto` de hasta 20 s se espera y se reintenta con el mismo modelo.
- **Promesa sin acción:** si la respuesta termina en «voy a… un momento» sin llamar a ninguna herramienta, se le obliga a cumplirlo (un empujón por turno).
- **Cifras o gráficos sin respaldo:** si no ha consultado nada y da importes que no aparecen en la conversación, o dice «aquí tienes el gráfico» sin haberlo generado, se le obliga a consultar antes de responder.
- **Gráfico escrito como ```json:** se convierte en gráfico.

## Errores y códigos HTTP

Los casos de uso lanzan errores de dominio con categoría (`dominio/errores.py`); **un solo módulo**
(`entrada/http/errores_http.py`) los traduce a HTTP. Todo error responde `{"detail": "mensaje legible", ...}`.

| Código | Categoría | Ejemplos |
|---|---|---|
| 400 | JSON roto o sin cuerpo | `POST` con `{roto` |
| 401 | `ErrorDeAutenticacion` | sin sesión, contraseña incorrecta |
| 403 | `ErrorDeAccesoDenegado` | escritura desde otro origen (defensa CSRF sobre `SameSite=Strict`) |
| 404 | `ErrorNoEncontrado` | contacto inexistente, operación ajena o inventada, ruta inexistente |
| 405 | método incorrecto | `DELETE /api/banco/saldo` |
| 409 | `ErrorDeConflicto` | saldo insuficiente, tope diario superado, operación ya procesada |
| 410 | `ErrorCaducado` | código OTP caducado |
| 413 | `ErrorCargaExcesiva` | mensaje de más de 1.500 caracteres, audio de más de 4 MB |
| 415 | `ErrorTipoNoSoportado` | `/stt` con un fichero que no es audio |
| 422 | `ErrorDeValidacion` | campo con tipo erróneo (con `errores: [{campo, motivo}]`), importe fuera de rango, mensaje vacío, código mal escrito |
| 423 | `ErrorBloqueado` | tres códigos OTP erróneos: operación cancelada |
| 429 | `ErrorLimiteExcedido` | login bloqueado, demasiadas peticiones por minuto, cuota diaria de tokens (con `Retry-After`) |
| 500 | cualquier otro fallo | cuerpo genérico con una referencia; el detalle va solo al log |
| 502 / 504 | `ErrorProveedorExterno` / `ErrorTiempoAgotado` | Whisper falla o no responde |
| 503 | `ErrorNoDisponible` | sin motor de IA, sin clave de voz |

`tests/test_errores_http.py` impide que una clase de error nueva quede por descuido en el 400 genérico.
Dentro del chat (SSE) los fallos del modelo no son errores HTTP: llegan como evento `error` o `aviso`; pero
los rechazos previos (413, 422, 429) sí se devuelven como HTTP antes de abrir el flujo.

## Estado que sobrevive a un reinicio

Sesiones de login, operaciones pendientes de confirmar, SMS del móvil simulado y conversaciones del chat se guardan en
SQLite (`salida/persistencia/sqlite_estado.py`, tablas `sesiones_auth`, `operaciones_pendientes`, `sms_movil` y
`sesiones_chat`), no en memoria. Así un reinicio del servidor (o la recarga automática de uvicorn con `--reload`) no
desconecta al cliente, no tira un Bizum a medias ni borra el SMS con el código. El token de sesión nunca se guarda en
claro (solo su huella sha256) y las operaciones guardan la huella del código, no el código. Lo único que sigue en memoria
es el contador de intentos de login y el limitador de ritmo, que se reinician a cero sin riesgo.

## Accesibilidad de la confirmación (ceguera, sordera, motricidad)

El OTP no puede depender de un solo sentido ni de teclear seis dígitos. Lo que hay ahora:

| Necesidad | Qué hace la app |
|---|---|
| **Ceguera** (lector de pantalla) | Al aparecer la tarjeta el foco va al campo del código y el lector lee el resumen («Confirma el Bizum de 25,00 € a Hijo Miguel…»). Los errores salen como `role="alert"`; cada SMS nuevo se anuncia **una sola vez** (región `aria-live` propia; el chat no relee cada fragmento del streaming y anuncia la respuesta terminada). Todos los botones y campos tienen nombre accesible |
| **No poder mirar o teclear** | Botón **«Aprobar con huella»** (Face ID / huella simulados, `POST /operaciones/{id}/aprobar`): confirma sin teclear nada, con las mismas reglas que el código (operación propia, pendiente y no caducada) |
| **Voz** | Opción «Leer los SMS en voz alta» en el móvil: el código se dice cifra a cifra («5, 8, 5, 9, 2, 1»). Dictar el código al micrófono no se ofrece a propósito: iría a un servicio de transcripción externo |
| **Sordera** | Nada depende del sonido: el SMS es texto, hay aviso visual (el 📱 parpadea) y vibración (`navigator.vibrate`); el código no se da nunca por llamada de voz |
| **Motricidad / táctil** | Objetivos táctiles de 44 px, foco visible, enlace «Saltar al cuadro de mensaje», todo operable con teclado |
| **Movimiento reducido** | La animación del móvil se desactiva con `prefers-reduced-motion` |

Es una **simulación**: en un banco real la aprobación con huella la firma la app del móvil con una clave del
dispositivo; aquí ambos canales viven en la misma página. La estructura se ha comprobado en Firefox, pero **no con
un lector de pantalla real** (NVDA, Orca, VoiceOver): es la prueba pendiente más valiosa antes de afirmar que es accesible.

## Control del gasto de tokens

Un turno gasta unos 4.000 tokens (≈1.900 de prompt y herramientas **por cada ronda**). Para no agotar la
cuota gratuita de Groq (8.000 tokens/min y 100.000/día por modelo) se controla en cuatro niveles:

| Qué | Cómo | Variable (valor por defecto) |
|---|---|---|
| **Medir** | cada llamada guarda sus tokens reales (`stream_options.include_usage`; si el proveedor no informa se estima y se marca `estimado`) en `uso_ia` | — |
| Mensaje | máximo de caracteres → 413 | `MAX_CARACTERES_MENSAJE` (1500) |
| Ritmo | máximo de peticiones por cliente y minuto → 429 | `PETICIONES_POR_MINUTO` (20) |
| Cuota diaria | tokens por cliente y día → 429 con `Retry-After` hasta medianoche | `TOKENS_DIA_CLIENTE` (80000) |
| Pregunta | tope de una consulta con todas sus rondas; si lo supera se corta con un mensaje | `TOKENS_MAX_TURNO` (30000) |
| Salida | `max_tokens` por llamada al modelo | `MAX_TOKENS_RESPUESTA` (4096) |
| **Reducir** | el historial reenviado se recorta por tokens | `MAX_TOKENS_HISTORIAL` (3000) |
| | un resultado SQL se recorta a un tamaño máximo en caracteres | `MAX_CARACTERES_RESULTADO` (6000) |

Se ve en la interfaz (medidor «⚡ 8,0k / 80k tokens hoy» en la cabecera), en `GET /api/uso` y en el evento SSE
`uso`. Las comprobaciones previas viven en `ServicioChat.enviar` (antes de abrir el streaming, para poder
responder con un código HTTP); la contabilidad y los topes del turno, en `Agente`. Puertos: `RegistroUso`
(SQLite) y `LimitadorPeticiones` (memoria).

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
| `operacion` | `{id, destinatario, importe, concepto, alertas, caduca}` (NUNCA el código) | tarjeta «Confirma tu Bizum» con campo de código |
| `fin` | texto completo final | reemplaza burbuja, dispara TTS |
| `error` | mensaje legible (los errores inesperados se registran en el log y no se detallan al cliente) | burbuja «⚠️» |

### Errores

Los casos de uso lanzan errores de dominio (`ErrorDeValidacion`, `ErrorNoEncontrado`,
`ErrorNoDisponible`) con mensaje legible. Cada adaptador los traduce a su idioma: HTTP
(422 / 404 / 503), SSE (`tipo: error`) o `{"ok": false, "error": …}` cuando quien pregunta es
el LLM, para que se explique al usuario. Los errores de los SDK se traducen en el adaptador
(`CuotaAgotada`, `ClaveInvalida`, `ProveedorInaccesible`…), de modo que el agente decide el
fallback sin importar `openai`.

## Seguridad

Regla central: **el LLM propone, el servidor decide**. Detalle y motivos en `DECISIONES.md` nº 11.

| Capa | Dónde | Qué hace |
|---|---|---|
| Login y sesión | `casos_uso/acceso.py`, `salida/seguridad/`, `entrada/http/rutas_auth.py` | scrypt con sal; cookie `HttpOnly` + `SameSite=Strict`; bloqueo 5 min tras 5 fallos; mismo error para usuario inexistente y contraseña errónea |
| Todo protegido | `entrada/http/seguridad.py` | dependencia `cliente_actual`: sin sesión válida → 401 en banco, chat, voz, estado y ajustes |
| Cliente en todo | puertos `RepositorioCuenta`, `RepositorioContactos`, `ConsultorMovimientos` | cada método recibe el `cliente_id` de la sesión; las herramientas reciben al `Cliente` y el LLM no puede elegirlo |
| Aislamiento NL→SQL | `salida/sqlite/consultor.py` | la consulta corre en una base en memoria con SOLO las filas del cliente + authorizer (sin ATTACH, PRAGMA ni sqlite_master) |
| OTP | `dominio/operaciones.py`, `casos_uso/bizum.py`, `rutas_operaciones.py` | operación pendiente, código de 6 dígitos de un solo uso (5 min, 3 intentos, solo su huella), validado en un endpoint aparte |
| Móvil simulado | `salida/persistencia/memoria_seguridad.MovilSimulado` | el único camino del código: `GET /movil/mensajes` (📱 en la interfaz), nunca el chat |
| Riesgo | `dominio/reglas.py` | tope por operación 1.000 €, diario 1.500 €; avisos de destinatario nuevo e importe ≥ 300 € |
| Auditoría | `salida/sqlite/auditoria.py` | login, OTP, Bizum solicitado/ejecutado/cancelado y consultas rechazadas |
| Navegador | `entrada/http/app.py` | CSP estricta, `X-Frame-Options: DENY`, `nosniff`, `no-store`; sin `/docs` |

### Endpoints

| Método y ruta | Auth | Uso |
|---|---|---|
| `POST /auth/login`, `GET /auth/yo`, `POST /auth/logout` | login: no | sesión |
| `POST /chat` (SSE), `POST /stt`, `POST /tts`, `GET /estado` | sí | conversación y voz |
| `GET /api/banco/saldo`, `/contactos`, `/movimientos` | sí | datos del cliente |
| `POST /api/banco/bizum` | sí | inicia el Bizum (pendiente de OTP) |
| `POST /operaciones/{id}/confirmar`, `/aprobar`, `/cancelar` | sí | confirmación con el código del móvil, con huella (alternativa accesible) o cancelación |
| `GET /movil/mensajes` | sí | SMS simulados del cliente |
| `GET /api/uso` | sí | gasto de tokens de la IA frente a los límites |
| `/ajustes/*` | sí | panel de claves y modelos |
| `/docs`, `/redoc`, `/openapi.json` | no | Swagger y OpenAPI: **solo con `DOCS_API=1`** (apagados por defecto) |

## Las 5 herramientas (function calling)

| Herramienta | Qué hace | Implementación |
|---|---|---|
| `consultar_saldo` | saldo, IBAN, titular | caso de uso `ConsultarSaldo` |
| `listar_contactos_bizum` | agenda Bizum | caso de uso `ListarContactos` |
| `transferencia_bizum` | **inicia** un Bizum (no lo envía): valida, crea una operación pendiente y manda el OTP al móvil simulado. Riesgo `ESCRITURA` | caso de uso `SolicitarBizum` + `dominio/reglas.py` (importe, saldo, tope por operación y diario) |
| `consultar_movimientos` | **NL→SQL**: el LLM escribe un SELECT de SQLite | `ConsultarMovimientos` → `reglas.validar_consulta_solo_lectura()` (solo SELECT/WITH, una sentencia, lista negra) y adaptador SQLite con conexión read-only, tope 60 filas |
| `generar_grafico` | el LLM emite la config Chart.js completa (tipo, datos, opciones) | evento SSE `grafico`; el backend solo valida que haya `type` y `data` — **sin plantillas** |

## Cadena de fallback LLM

`Ajustes.cadena_llm()` (dominio) → se recorre en `Agente.responder()` ante 429/red/5xx, **sin
consumir rondas** (un límite por minuto se explica distinto de una cuota diaria agotada) y avisando por SSE:

1. `openai/gpt-oss-120b` (Groq, `reasoning_effort="low"`) — principal (Llama 3.3 70B se retiró de Groq)
2. `openai/gpt-oss-20b` (Groq) — cuota diaria independiente
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
clientes(id, usuario UNIQUE, nombre, telefono, hash_contrasena)   -- scrypt con sal
cuenta(iban, cliente_id, titular, saldo)
movimientos(id AUTOINCREMENT, cliente_id, fecha 'YYYY-MM-DD', categoria, concepto, comercio,
            importe)  -- negativo = gasto; fecha SIN hora → desempatar con id
contactos_bizum(cliente_id, nombre, telefono)
auditoria(id, momento, cliente_id, accion, detalle, resultado)
uso_ia(id, momento, cliente_id, proveedor, modelo, tokens_entrada, tokens_salida, estimado)
```

Cuatro clientes ficticios (`sqlite/perfiles.py`): Alex (trabajador joven), Ana (estudiante), Marta
(familia con hijos) y José Luis (jubilado). Cada uno tiene sus ingresos fijos, recibos, hábitos de gasto,
contactos Bizum y saldo (`generador.py`, semilla fija por perfil).

Arranque (`esquema.inicializar`): si `data/banco.db` no existe o tiene un esquema antiguo se regenera;
si existe, solo se **desplazan las fechas** para que el último movimiento sea de hoy (así el «último mes»
de la demo es siempre el actual). `forzar=True` regenera todo y borra los Bizum hechos desde el chat.
Categorías: Nómina, Vivienda, Suscripciones, Deporte, Supermercado, Restaurantes, Transporte, Ropa,
Ocio, Salud, Compras online, Educación, Bizum.

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
