# Cómo se añade una funcionalidad (caso real: bloquear y desbloquear tarjeta)

Guía para la memoria técnica y para quien herede el proyecto. Primero la receta genérica, después el caso real
con los números medidos sobre el código (`git diff --stat`, 4-oct-2026), el camino de una petición por las capas
y, sin maquillar, **dónde la arquitectura no fue tan limpia**.

La funcionalidad: «he perdido la tarjeta». Cada cliente tiene 1-2 tarjetas ficticias; el asistente puede
**consultarlas**, **bloquearlas al instante** (sin OTP: es la dirección segura, queda auditado) y **pedir su
desbloqueo**, que sí exige OTP como un Bizum (decisión nº 20 de `DECISIONES.md`).

---

## 1. La receta, paso a paso

Orden recomendado: de dentro hacia fuera. Cada paso se puede probar sin los siguientes (los dobles están en
`tests/fakes.py`).

| # | Paso | Dónde | Qué se escribe |
|---|---|---|---|
| 1 | **Dominio**: entidad, regla y errores | `backend/dominio/modelos.py`, `reglas.py`, `errores.py` | La entidad (`Tarjeta`), las reglas puras (`elegir_tarjeta`, `bloquear_tarjeta`) y los errores con su categoría HTTP (`TarjetaAmbigua` hereda de `ErrorDeConflicto` → 409). Sin base de datos, sin red |
| 2 | **Puerto**: qué necesita la aplicación del exterior | `backend/aplicacion/puertos/banco.py` | Un `Protocol` (`RepositorioTarjetas`). Todo método recibe el `cliente_id`: el aislamiento lo garantiza quien lo implementa |
| 3 | **Adaptador** SQLite (y migración) | `backend/adaptadores/salida/sqlite/repositorios.py`, `esquema.py`, `perfiles.py` | La clase que cumple el puerto, la tabla en `DDL_COMPLEMENTARIO` (`CREATE TABLE IF NOT EXISTS`) y el sembrado de datos de demostración, idempotentes |
| 4 | **Caso de uso**: el flujo | `backend/aplicacion/casos_uso/tarjetas.py` | Orquesta dominio + puertos y audita. No sabe nada de HTTP, SQL ni del LLM |
| 5 | **Herramienta** del agente | `backend/aplicacion/herramientas/tarjetas.py` | Esquema JSON para el modelo + función + etiqueta + nivel de riesgo. Si el caso de uso ya sabe qué decir, `respuesta_final` (el modelo no narra) y eventos SSE |
| 6 | **Cableado** | `backend/composicion.py` | Crear el adaptador, inyectarlo en los casos de uso y añadir la herramienta a la lista del registro. **Es el único fichero que lo conoce todo** |
| 7 | **Prompt** (si hace falta) | `backend/aplicacion/prompt.py` | Una norma mínima (la 14ª). Cada norma nace de un bug real (`INCIDENCIAS.md`) |
| 8 | **Salida** (si aplica) | `entrada/http/sse.py`, `rutas_*.py`, `esquemas.py` | Un evento SSE nuevo y/o un endpoint REST; los errores ya se traducen solos por su categoría |
| 9 | **Tests** | `tests/` | Dominio, caso de uso, herramienta, aislamiento entre clientes, SQLite/migración, HTTP. `tests/test_arquitectura.py` vigila que ningún import apunte hacia fuera |
| 10 | **Docs** | `docs/` | `python pruebas/exportar_openapi.py` y `python pruebas/generar_referencia.py`; ARQUITECTURA, DECISIONES |

Reglas que se comprueban solas: el dominio no importa nada del proyecto, la aplicación no importa adaptadores, las
entradas no conocen las salidas (`tests/test_arquitectura.py`, módulos analizados).

---

## 2. El caso real: bloqueo de tarjeta

### 2.1 Ficheros NUEVOS

| Fichero | Líneas | Qué es |
|---|---:|---|
| `backend/aplicacion/casos_uso/tarjetas.py` | 121 | `ConsultarTarjetas`, `BloquearTarjeta` (cancela los desbloqueos pendientes), `SolicitarDesbloqueoTarjeta`, `DesbloquearTarjeta` |
| `backend/aplicacion/casos_uso/cerrojos.py` | 19 | `CerrojosPorCliente`, sacado de `bizum.py` para que bloquear y confirmar compartan cerrojo sin importarse en círculo |
| `backend/aplicacion/herramientas/tarjetas.py` | 184 | las 3 herramientas (`consultar_tarjetas`, `bloquear_tarjeta`, `desbloquear_tarjeta`) y su red de seguridad |
| `frontend/js/ui/tarjeta_bancaria.js` | 93 | la tarjeta visual (marca, últimos 4, estado) que pinta el evento `tarjeta` |
| **Producción nueva** | **396** | (303 de backend + 93 de frontend) |
| `tests/test_tarjetas.py` | 685 | 167 pruebas: dominio, casos de uso, herramientas, agente, carreras con hilos, SQLite, migración |

### 2.2 Ficheros TOCADOS (líneas añadidas / quitadas, `git diff --numstat HEAD`, 4-oct-2026)

| Capa | Fichero | +/- | Por qué |
|---|---|---|---|
| Dominio | `dominio/reglas.py` | +91 / -1 | buscar, elegir, bloquear y desbloquear tarjeta (la regla de negocio) |
| | `dominio/modelos.py` | +28 / -1 | `Tarjeta`, `ComprobanteTarjeta` |
| | `dominio/errores.py` | +26 | 4 errores de tarjeta |
| | `dominio/operaciones.py` | +14 / -2 | `TipoOperacion` y `referencia`: la operación pendiente ya no es solo un Bizum |
| Aplicación | `puertos/banco.py` | +11 / -1 | puerto `RepositorioTarjetas` (la transición de estado es atómica) |
| | `puertos/seguridad.py` | +4 | `pendientes_de(cliente_id)`: bloquear cancela los desbloqueos pendientes |
| | `casos_uso/bizum.py` | +33 / -27 | `ConfirmarOperacion` ejecuta también el desbloqueo; `CancelarOperacion` audita por tipo; `CerrojosPorCliente` se mueve a `cerrojos.py` |
| | `chat.py` | +10 / -8 | el aviso «resultado de la operación» al modelo distingue Bizum/desbloqueo |
| | `eventos.py` | +13 / -1 | evento `TarjetaMostrada` y `tipo` en `OperacionPorConfirmar` |
| | `herramientas/registro.py` | +47 | nivel `Riesgo.PROTECCION`, el gancho `orden_directa` y su validación al arrancar, `pregunta_valida` (ver 2.4) |
| | `texto.py` | +111 | detector de órdenes de bloqueo, extracción de los datos de la tarjeta y enmascarado de números largos |
| | `agente.py` | +69 / -12 | **solo** la red de seguridad del modelo (empujón y llamada del servidor) y los topes de las acciones de protección (ver 2.4 y 4) |
| | `prompt.py` | +8 / -3 | norma 14 (+ dos menciones en el encabezado y la norma 8) |
| Adaptadores | `salida/sqlite/repositorios.py` | +45 / -2 | `RepositorioTarjetasSqlite` (UPDATE condicional) |
| | `salida/sqlite/esquema.py` | +39 / -2 | tabla `tarjetas`, columnas nuevas de `operaciones_pendientes`, sembrado |
| | `salida/sqlite/perfiles.py` | +8 | las tarjetas de demostración de cada cliente |
| | `salida/persistencia/sqlite_estado.py` | +20 / -5 | guardar `tipo` y `referencia` de la operación y listar las pendientes |
| | `salida/persistencia/memoria_seguridad.py` | +4 / -1 | lo mismo para la versión en memoria |
| | `entrada/http/sse.py` | +10 / -1 | evento SSE `tarjeta` y campos nuevos del evento `operacion` |
| | `entrada/http/esquemas.py`, `presentadores.py`, `rutas_operaciones.py`, `rutas_banco.py` | +44 / -6 | comprobante del desbloqueo y `GET /api/banco/tarjetas` |
| Composición | `composicion.py` | +12 / -4 | el cableado (1 adaptador, 4 casos de uso, 1 línea de herramientas) |
| **Backend tocado** | 24 ficheros | **+558 / -77** | |
| Frontend | `js/ui/vista_chat.js` | +67 / -1 | pinta la tarjeta bancaria en el chat |
| | `js/ui/tarjeta_operacion.js` | +32 / -13 | la tarjeta de confirmación ya no dice siempre «Bizum» (según `tipo`) |
| | `js/main.js`, `js/aplicacion/conversacion.js`, `js/ui/iconos.js`, `js/ui/movil.js`, `js/ui/sugerencias.js` | +20 | cableado del evento, icono, sugerencia |
| | `styles.css` | +47 / -2 | estilos de la tarjeta |
| **Frontend tocado** | 8 ficheros | **+161 / -16** | (más los 93 de `tarjeta_bancaria.js`) |

Tests y herramientas de apoyo: `tests/fakes.py` +25 (el doble `TarjetasEnMemoria`), `tests/test_http.py` +66/-4,
`tests/test_seguridad_chat.py` +44/-8, `tests/test_bizum_otp.py` +6/-3 y `tests/test_errores_http.py` +2/-2:
**143 líneas añadidas** en tests existentes. `pruebas/generar_referencia.py` +15/-8 no es un test (genera la referencia).
Los tests existentes no fallaron por lógica: solo hubo que adaptar los sitios donde se construyen `ConfirmarOperacion`
(3: su constructor recibe el caso de uso de desbloqueo) y `BloquearTarjeta` (2: ahora recibe las operaciones y los cerrojos).

**Resumen honesto**: ≈ 860 líneas de backend (303 en 3 ficheros nuevos + 558 en 24 tocados) y ≈ 250 de frontend (93 nuevas
+ 161 añadidas en 8 ficheros), frente a ≈ 720 de tests (576 nuevas + 143 modificadas). De lo de backend, unas 280 son el
propio caso de uso y la herramienta; el resto es dominio, esquema y el hecho de que el desbloqueo con OTP **reutiliza** el flujo de
confirmación existente en vez de duplicarlo. Una parte importante (~160 líneas de `texto.py`, `registro.py` y `agente.py`, más
sus tests) no es la funcionalidad sino **la defensa frente al modelo pequeño** (2.4 y 4): esa es la cifra que más creció tras
la primera versión (antes de las revisiones eran ≈ 675 de producción). El número de tests pasó de 514 a 693.

### 2.3 Lo que NO hubo que tocar (y por qué)

| No se tocó | Por qué no hizo falta |
|---|---|
| **Las rondas, el fallback de proveedores, el streaming y los límites de tokens del agente** | solo conoce `RegistroHerramientas` y el puerto `ProveedorLLM`; las herramientas llegan por la lista del registro |
| **El protocolo SSE** (`rutas_chat.py`, formato `data: {tipo, dato}`) | un evento nuevo es una `dataclass` en `eventos.py` + 10 líneas en `sse.py`; el servicio de chat reenvía cualquier `EventoChat` |
| **Login, sesión, cookies, CSRF, límites de tokens** | la herramienta recibe el `Cliente` ya autenticado; no existe forma de elegir otro |
| **El aislamiento NL→SQL** (`consultor.py`) | copia una lista cerrada de tablas con las filas del cliente: la tabla `tarjetas` queda fuera sin hacer nada (hay un test que lo comprueba) |
| **El flujo OTP** (generador de códigos, SMS simulado, 3 intentos, caducidad, huella) | el desbloqueo es una `OperacionPendiente` más; `ConfirmarOperacion` sirve el código, la huella y la cancelación |
| **Los adaptadores LLM, voz, ajustes, uso** | ningún puerto cambió |

Lo que **sí** se tocó, aunque «no debía»: el bucle del agente (`Agente.responder`). Primero +17/-10 y, tras las revisiones,
+40/-12 en total: un empujón y una llamada del servidor cuando el modelo no ejecuta una orden clara (2.4), y los topes de
las acciones de protección (una por turno y solo si la pregunta habla de tarjetas). Es poco, pero es el fichero más delicado y
el motivo no es la funcionalidad sino la debilidad del modelo local. **El frontend** tampoco quedó sin tocar: ver 2.2.

### 2.4 El agente tampoco se libró

La funcionalidad en sí (tres herramientas) no pidió nada al agente. Pero probándola con el modelo local
(qwen3:8b) apareció el fallo de siempre en los modelos pequeños (INCIDENCIAS nº 95): de 5 formulaciones coloquiales
(«perdí mi tarjeta», «me han robado la tarjeta», «congela mi tarjeta», «creo que me han clonado la tarjeta», «no
encuentro mi tarjeta») solo una llamó a la herramienta; en las otras 4 **respondía «Tarjeta bloqueada» sin llamar
a nada**, es decir, mentía. Con el gancho, las 5 acaban bloqueando de verdad. Es el mismo patrón que el Bizum (nº 93-94), y el Bizum lo resolvía con
código dentro de `agente.py` y con el nombre `transferencia_bizum` escrito a mano.

Esta vez se resolvió con un **gancho genérico**: `Herramienta.orden_directa` (+ `aviso_orden`). Una herramienta
puede declarar «esta frase del usuario es una orden mía»; si el modelo no la llama, el agente le da un empujón y,
si aun así no la llama, la ejecuta el servidor. Solo para acciones seguras o que dejan una operación pendiente de
OTP (el registro lo exige al arrancar: sin `aviso_orden` o con riesgo de solo lectura lanza un `ValueError`). El
gancho se aplica **con cualquier modelo**, no solo con el pequeño: si el modelo grande tampoco llama a la herramienta
ante una orden clara, también se le empuja y, en último término, la ejecuta el servidor. El Bizum sigue con su guarda
propia (no se migró: fuera de alcance).

**El detector no era «solo orden inequívoca»**, como se escribió en la primera versión de esta guía. La regex inicial
(`pide_bloquear_tarjeta`) daba positivo con «como puedo bloquear mi tarjeta» (sin `?`), «¿cómo puedo bloquear mi
tarjeta» (solo se miraba el `?` final), «quiero saber cómo bloquear la tarjeta», «se puede bloquear la tarjeta desde la app»,
«no sé si bloquear la tarjeta», «perdí el tren pero tengo la tarjeta», «a mi madre le han robado la tarjeta», «perdí
la tarjeta pero la encontré», «he perdido la cartera, la tarjeta no» y «cuánto gasté con la tarjeta visa antes de
bloquearla»: el servidor **bloqueaba una tarjeta que nadie había pedido bloquear**. Y daba falso negativo con «he perdido la
tarjeta. ¿Qué hago?» y «bloquea la visa, he visto actividad rara» (el `activ` de las reactivaciones cazaba «actividad»).
Ahora está acotado: solo cuenta la primera persona en presente o perfecto («bloquea(me)…», «quiero bloquear…», «he
perdido / perdí / me han robado / me robaron / me han clonado…») con la tarjeta a pocas palabras del verbo; no cuenta si hay
«cómo / explica / se puede / quiero saber / qué pasa si / no sé si / si…», «pero», «la encontré», «la tarjeta no», el
infinitivo suelto, una pregunta (con o sin `¿`, aunque junto a una orden: se descarta solo la frase pregunta) ni lo que le
pasa a otra persona. Además el servidor ya no pasa a la herramienta la frase entera sino solo los 4 dígitos junto a
«terminada en / ••», la marca y el tipo (con negación o duda no pasa nada y pregunta cuál), y solo ejecuta una
acción de protección por turno y solo si la última pregunta habla de tarjetas.

### 2.5 Camino de «he perdido la tarjeta» por las capas

```
 usuario ── «he perdido la tarjeta» ──►  POST /chat                                   (cookie de sesión)
                                           │
 ADAPTADOR ENTRADA  entrada/http/        rutas_chat.py + seguridad.py  → identifica al Cliente (401 si no hay sesión)
                                           │
 APLICACIÓN         chat.py              ServicioChat.enviar: límites de uso, un turno a la vez, historial
                    agente.py            Agente.responder ──► ProveedorLLM.completar ──┐   (puerto)
                                           ▲                                            ▼
                                           │                          ADAPTADOR SALIDA  llm/openai_compat.py → Groq / Ollama
                                           │        «llama a bloquear_tarjeta»
                    herramientas/registro.py   RegistroHerramientas.ejecutar("bloquear_tarjeta", args, cliente)
                    herramientas/tarjetas.py   ejecutar_bloqueo(args, cliente)
                    casos_uso/tarjetas.py      BloquearTarjeta(cliente, consulta)
                                           │
 DOMINIO            dominio/reglas.py      elegir_tarjeta(...)  → ¿una sola activa? ¿varias? ¿ya bloqueada?
                                           │                      bloquear_tarjeta(...) → Tarjeta(bloqueada=True)
                    aplicacion/puertos/    RepositorioTarjetas.guardar_estado(cliente.id, tarjeta)      (puerto)
                                           │
 ADAPTADOR SALIDA   sqlite/repositorios.py UPDATE tarjetas ... WHERE id=? AND cliente_id=?   (el aislamiento)
                    sqlite/auditoria.py    «tarjeta_bloqueada»
                                           │
 APLICACIÓN         ResultadoHerramienta(datos, eventos=(TarjetaMostrada,), respuesta_final="Listo, he bloqueado…")
                    agente.py              el turno acaba SIN otra vuelta al modelo (no gasta tokens, no puede mentir)
                                           │
 ADAPTADOR ENTRADA  sse.py                 TarjetaMostrada → {"tipo":"tarjeta","dato":{marca,tipo,ultimos4,estado,…}}
 usuario ◄── SSE: herramienta · tarjeta · uso · fin ──
```

Desbloquear es igual hasta el caso de uso, pero `SolicitarDesbloqueoTarjeta` crea una `OperacionPendiente`
(`tipo=desbloqueo_tarjeta`) y manda el código al móvil simulado; la tarjeta **sigue bloqueada** hasta que el cliente
escribe el código (o aprueba con la huella) en `POST /operaciones/{id}/confirmar`, fuera del LLM, y
`ConfirmarOperacion` llama a `DesbloquearTarjeta`.

---

## 3. Comparación honesta

### Con una arquitectura sin capas

Un backend típico de un solo fichero (rutas FastAPI con `sqlite3` dentro y el agente llamando a funciones):

| Qué habría que tocar | Dónde se mezclaría |
|---|---|
| La regla «no bloquear una ya bloqueada», «elegir la única candidata» | en la ruta HTTP **y** en la función que llama el agente (dos copias que divergen, como ya pasó con el Bizum antes de la hexagonal) |
| El SQL de `UPDATE tarjetas` | dentro de la función de la herramienta, con el `cliente_id` pasado a mano: un descuido y un cliente toca la tarjeta de otro |
| El esquema JSON de la herramienta y el `if nombre == ...` del bucle del agente | en el propio bucle: cada herramienta nueva es una rama nueva en el fichero más delicado |
| Los tests | sin puertos hay que levantar SQLite y/o un LLM para probar una regla de 5 líneas |
| El desbloqueo con OTP | copiar o reescribir la confirmación del Bizum |

No es que sea imposible: es que cada cambio toca el mismo fichero central y la regla de negocio acaba duplicada.
Aquí la regla está una vez (`reglas.py`) y la probamos sin base de datos (los tests de dominio de
`test_tarjetas.py`, milisegundos).

**Coste real de las capas** (no se vende solo): para 3 herramientas hay 6 sitios que tocar en vez de 1-2
(dominio, puerto, adaptador, caso de uso, herramienta, composición) y bastante código «de fontanería»
(`presentadores`, `esquemas`). Compensa cuando hay varias funcionalidades, varias interfaces y tests; para un
prototipo de una sola pantalla sobraría.

### Con MCP / A2A

- **MCP** (Model Context Protocol) estandariza cómo un *cliente de IA externo* descubre y llama herramientas.
  Aquí hay un solo cliente (nuestro agente, en el mismo proceso) y un solo proveedor de herramientas (el banco):
  añadir MCP sería una capa de red y de serialización sin nadie al otro lado. **No hace falta**. Y si algún día
  hiciera falta (que Claude Desktop use nuestras herramientas), es un **adaptador de entrada más**
  (`entrada/mcp/`) que llama a los mismos casos de uso: esa es precisamente la ventaja de la hexagonal; no habría
  que reescribir nada.
- **A2A** (agente a agente) tiene sentido cuando otro agente de otra organización hace trabajo por nosotros
  (reservar mesa, un AVE). El bloqueo de tarjeta es 100 % interno y debe ser determinista: delegarlo sería peor.
- **Cuándo sí se justifica algo más: 40 herramientas.** Medido con el estimador del proyecto, estas 3 herramientas
  más la norma 14 suman **≈ 600 tokens por ronda** (≈ 420 las herramientas, ≈ 190 la norma): ya es un ~30 % más
  de los ≈ 1.900 de prompt+herramientas por ronda. Con 40 herramientas se enviaría un prompt enorme en cada
  petición, el modelo pequeño se confundiría eligiendo, y la cuota gratuita se agotaría. La solución prevista
  (PLAN, bloque 2, punto 2) es **seleccionar las herramientas por categoría** (cuentas, pagos, tarjetas,
  análisis) con un paso previo barato y mandar solo las de esa categoría. **No está implementada todavía**: hoy
  se mandan las 8. El `RegistroHerramientas` es el punto donde se enchufaría (un filtro en `esquemas()`), sin
  tocar las herramientas.

---

## 4. Cómo de limpio fue: lo que NO fue tan limpio

Cosas que se encontraron al hacerlo. Es lo más útil de la guía para decidir qué refactorizar.

1. **La operación pendiente tiene forma de Bizum.** `OperacionPendiente` tiene `destinatario`, `telefono`,
   `importe` y `concepto`. Para el desbloqueo se reutilizan (destinatario = «Visa débito ••4821», importe = 0,
   concepto = «Desbloqueo de tarjeta») y se añadieron `tipo` y `referencia`. Funciona y evita duplicar el flujo OTP,
   pero es un apaño. Y la misma forma llega al **evento SSE `operacion`** y a la tarjeta de confirmación del
   frontend: hubo que adaptar la tarjeta de confirmación (`tipo` decide título y filas) para que no diga «Confirma tu Bizum de 0,00 €». Lo limpio sería una operación
   con una carga útil propia de cada tipo.
2. **`ConfirmarOperacion` tiene un `if tipo`.** El tercer tipo de operación debería convertir eso en un registro
   de ejecutores por tipo (como el de herramientas). Con dos tipos no compensa. Además el constructor ganó un
   parámetro obligatorio, y hubo que corregir 3 sitios de los tests que lo construyen, y el caso de uso devuelve
   ahora una unión (`ComprobanteBizum | ComprobanteTarjeta`).
3. **El agente sí tuvo que cambiar** para proteger al modelo pequeño (2.4): la guarda del Bizum estaba escrita a
   mano dentro de `agente.py` con su nombre de herramienta. Se generalizó con un gancho (que vale para todos los
   modelos), pero es un cambio en el fichero «que no debía cambiar». Si el modelo fuera siempre uno grande, no habría
   hecho falta.
4. **`chat.py` conoce los tipos de operación.** El texto que se le cuenta al modelo cuando el cliente confirma
   (o no) la operación fuera del chat estaba escrito para el Bizum («el dinero YA se ha enviado»); hubo que
   hacerlo depender del tipo.
5. **Migraciones a mano.** No hay herramienta de migraciones: `esquema.py` tiene `DDL_COMPLEMENTARIO` con
   `CREATE TABLE IF NOT EXISTS` y, para añadir columnas a una tabla que ya existe, un `PRAGMA table_info` +
   `ALTER TABLE ADD COLUMN`. Es aditivo e idempotente (probado sobre una copia de la base real, con Bizums hechos
   que no desaparecen) y no cambia `VERSION_ESQUEMA`, que es lo que dispararía la regeneración destructiva. Pero
   cada cambio de esquema es código escrito a mano y probado a mano.
6. **El nivel de riesgo no tenía sitio para «escritura sin OTP».** `Riesgo` solo tenía lectura y escritura (= OTP).
   Bloquear una tarjeta modifica estado sin OTP, así que se añadió `PROTECCION`. Es una decisión de seguridad,
   no un detalle técnico (decisión nº 20). El test `test_bizum_es_la_unica_herramienta_de_escritura...` sigue verde
   pero recorre una lista fija de herramientas: no vigila las nuevas. (Corregido después: ahora `test_seguridad_chat.py` exige que toda herramienta ESCRITURA devuelva
   una `OperacionPorConfirmar` y que el registro real de `composicion.py` no tenga más escrituras que las esperadas.)
7. **La documentación generada tiene listas manuales.** `pruebas/generar_referencia.py` enumera a mano los módulos
   de herramientas y qué llama a cada caso de uso: hubo que editarlo, y de paso se vio que `REFERENCIA.md` llevaba
   semanas desfasada (decía 320 tests). El registro de herramientas no es introspectable sin construirlas.
8. **El prompt crece.** Cada funcionalidad cuesta tokens en cada ronda (3) y una norma nueva puede interferir con
   las demás; solo se detecta probando con el modelo real. La norma 14 se probó con qwen3:8b en vivo (INCIDENCIAS 95).
9. **El frontend sí se hizo, pero en un paso aparte.** El backend emite el evento `tarjeta` y el campo `tipo` de la
   operación; la tarjeta visual (`tarjeta_bancaria.js`, 93 líneas) y la adaptación de la tarjeta de confirmación
   (`tarjeta_operacion.js`) llegaron después, con +161/-16 en 8 ficheros más (2.2). La arquitectura por módulos lo permitió
   (`js/ui/` + una rama en `conversacion.js`).

### Limitaciones reales (lo que salió mal en esta funcionalidad)

10. **Un detector de órdenes con regex en español es frágil.** Se endureció en **tres rondas** (la tercera: otras tarjetas, otras personas, aplazamientos, rectificaciones, hechos antiguos, citas, coste de las regex; incidencias 101-107) y todavía habrá frases que se le
    escapen (en ambos sentidos). Por eso la **validación de la orden pasó a la propia herramienta** (`pregunta_valida` + `rechazo_final`, decisión 20): ya no depende de que el modelo o el gancho se porten bien. Cada una de las frases de 2.4 que lo rompían quedó como prueba, pero la lista de
    formas de decir «he perdido la tarjeta» no se acaba. Se mitiga con tres cosas: el servidor solo actúa tras un
    empujón fallido, solo con una orden explícita y solo para bloquear (la dirección segura), y los falsos positivos
    cuestan poco (la tarjeta se reactiva con OTP).
11. **Un modelo débil obliga a un gancho en el agente.** El coste real de «añadir una herramienta» **no fue cero**: tres
    herramientas en dos ficheros nuevos fueron limpias, pero hubo que tocar el bucle del agente y el registro, y
    escribir un detector con su batería de pruebas. Con un modelo grande habría sido solo la receta del apartado 1.
12. **Streaming con texto falso.** A veces el modelo escribe «Tarjeta bloqueada correctamente…» como `delta` ANTES de llamar
    a la herramienta; el evento `fin` lo corrige después con el texto del servidor, pero mientras tanto el usuario lo ve.
    Evitarlo exigiría retener los `delta` de cada ronda hasta saber si termina en una herramienta con `respuesta_final`,
    y eso rompería el streaming de todas las demás respuestas. Se deja como limitación conocida.
13. **El mensaje del usuario sigue en el historial tal cual.** Si escribe un número de tarjeta completo, el servidor lo
    enmascara en la auditoría y nunca lo repite en sus respuestas, pero el propio mensaje del usuario queda en la
    conversación guardada.

---

## 5. Cómo comprobarlo

```bash
source .venv/bin/activate
python -m pytest -q tests/test_tarjetas.py          # 110 pruebas de la funcionalidad
python -m pytest -q tests/test_arquitectura.py      # la regla de dependencia sigue intacta
python -m pytest -q                                 # 636 en total
```

En vivo (modelo local, servidor aparte): «¿qué tarjetas tengo?», «he perdido la tarjeta», «bloquea la tarjeta
terminada en 4821» y «desbloquea mi tarjeta» (queda pendiente del código del móvil). Hay que **reiniciar uvicorn**
para que cargue el backend nuevo; al arrancar crea la tabla `tarjetas` y las 6 tarjetas sin tocar nada más.
