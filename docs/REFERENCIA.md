# Referencia del código (generada)

Generada por `pruebas/generar_referencia.py` leyendo el código. No se edita a mano.

## Puertos (22)

| Puerto | Fichero | Métodos | Adaptador | Doble de pruebas |
|---|---|---|---|---|
| `RepositorioCuenta` | `aplicacion/puertos/banco.py` | `obtener(cliente_id: int) → Cuenta`<br>`registrar_movimiento(cliente_id: int, movimiento: Movimiento) → Cuenta`<br>`bizum_enviado_el(cliente_id: int, dia: date) → float`<br>`envios_bizum_a(cliente_id: int, nombre: str) → int` | `RepositorioCuentaSqlite` (`salida/sqlite/repositorios.py`) | `CuentaEnMemoria` |
| `RepositorioContactos` | `aplicacion/puertos/banco.py` | `listar(cliente_id: int) → list[Contacto]`<br>`buscar(cliente_id: int, nombre_o_telefono: str) → Contacto ∣ None` | `RepositorioContactosSqlite` (`salida/sqlite/repositorios.py`) | `ContactosEnMemoria` |
| `ConsultorMovimientos` | `aplicacion/puertos/banco.py` | `ejecutar_select(cliente_id: int, sql: str, limite: int) → ResultadoConsulta` | `ConsultorMovimientosSqlite` (`salida/sqlite/consultor.py`) | `ConsultorFalso` |
| `RepositorioTarjetas` | `aplicacion/puertos/banco.py` | `listar(cliente_id: int) → list[Tarjeta]`<br>`guardar_estado(cliente_id: int, tarjeta: Tarjeta) → None` | `RepositorioTarjetasSqlite` (`salida/sqlite/repositorios.py`) | `TarjetasEnMemoria` |
| `RepositorioSesiones` | `aplicacion/puertos/infraestructura.py` | `obtener(id_sesion: str) → list[Mensaje] ∣ None`<br>`guardar(id_sesion: str, mensajes: list[Mensaje]) → None` | `SesionesChatSqlite` (`salida/persistencia/sqlite_estado.py`) | `SesionesEnMemoria` |
| `RepositorioAjustes` | `aplicacion/puertos/infraestructura.py` | `cargar() → Ajustes`<br>`guardar(ajustes: Ajustes) → None` | `AjustesJson` (`salida/persistencia/ajustes_json.py`) | `AjustesEnMemoria` |
| `Reloj` | `aplicacion/puertos/infraestructura.py` | `hoy() → date`<br>`ahora() → datetime` | `RelojSistema` (`salida/reloj.py`) | `RelojFijo` |
| `SondaProveedores` | `aplicacion/puertos/infraestructura.py` | `listar_modelos(proveedor: str, api_key: str ∣ None=None) → list[str]`<br>`estado_ollama(url: str) → EstadoOllama` | `SondaOpenAI` (`salida/llm/sonda.py`) | `SondaFalsa` |
| `ProveedorLLM` | `aplicacion/puertos/llm.py` | `completar(modelo: ModeloRef, mensajes: Sequence[Mensaje], herramientas: Sequence[EsquemaHerramienta] ∣ None, max_tokens: int ∣ None=None) → Iterator[EventoLLM]` | `ProveedorLLMOpenAI` (`salida/llm/openai_compat.py`) | `LLMGuionizado` |
| `RepositorioClientes` | `aplicacion/puertos/seguridad.py` | `buscar_por_usuario(usuario: str) → tuple[Cliente, str] ∣ None`<br>`obtener(cliente_id: int) → Cliente ∣ None`<br>`listar() → list[Cliente]` | `RepositorioClientesSqlite` (`salida/sqlite/repositorios.py`) | `ClientesFalsos (test_acceso)` |
| `Hasheador` | `aplicacion/puertos/seguridad.py` | `hashear(contrasena: str) → str`<br>`verificar(contrasena: str, hash_guardado: str) → bool`<br>`gastar_tiempo(contrasena: str) → None` | `HasheadorScrypt` (`salida/seguridad/hasheador.py`) | `(el real, es rápido de crear)` |
| `SesionesAutenticadas` | `aplicacion/puertos/seguridad.py` | `crear(cliente_id: int) → str`<br>`cliente_de(token: str) → int ∣ None`<br>`cerrar(token: str) → None` | `SesionesAutenticadasSqlite` (`salida/persistencia/sqlite_estado.py`) | `SesionesAutenticadasEnMemoria` |
| `RegistroIntentos` | `aplicacion/puertos/seguridad.py` | `reservar(limites: dict[str, int], ahora: datetime, conservar_ventana: frozenset[str]=frozenset()) → ReservaIntento`<br>`devolver(reserva: ReservaIntento, reiniciar: str) → None` | `IntentosEnMemoria` (`salida/persistencia/memoria_seguridad.py`) | `IntentosEnMemoria` |
| `RepositorioOperaciones` | `aplicacion/puertos/seguridad.py` | `guardar(operacion: OperacionPendiente) → None`<br>`obtener(id_operacion: str) → OperacionPendiente ∣ None`<br>`pendientes_de(cliente_id: int) → list[OperacionPendiente]` | `OperacionesSqlite` (`salida/persistencia/sqlite_estado.py`) | `OperacionesEnMemoria` |
| `GeneradorCodigos` | `aplicacion/puertos/seguridad.py` | `nuevo_id() → str`<br>`nuevo_codigo() → str` | `GeneradorCodigosSeguro` (`salida/seguridad/codigos.py`) | `CodigosFijos` |
| `CanalOTP` | `aplicacion/puertos/seguridad.py` | `enviar(cliente_id: int, texto: str) → None` | `MovilSqlite` (`salida/persistencia/sqlite_estado.py`) | `MovilFalso` |
| `BandejaMovil` | `aplicacion/puertos/seguridad.py` | `mensajes(cliente_id: int) → list[dict]` | `MovilSqlite` (`salida/persistencia/sqlite_estado.py`) | `MovilFalso` |
| `Auditoria` | `aplicacion/puertos/seguridad.py` | `registrar(cliente_id: int ∣ None, accion: str, detalle: str, resultado: str) → None`<br>`ultimos(cliente_id: int, limite: int=20) → list[dict]` | `AuditoriaSqlite` (`salida/sqlite/auditoria.py`) | `AuditoriaEnMemoria` |
| `RegistroUso` | `aplicacion/puertos/uso.py` | `registrar(cliente_id: int, proveedor: str, modelo: str, uso: Uso, momento: datetime) → None`<br>`tokens_del_dia(cliente_id: int, dia: date) → int`<br>`tokens_locales_del_dia(cliente_id: int, dia: date) → int`<br>`ultimos(cliente_id: int, limite: int=10) → list[dict]`<br>`reiniciar_dia(cliente_id: int, dia: date) → int` | `UsoSqlite` (`salida/sqlite/uso.py`) | `UsoEnMemoria` |
| `LimitadorPeticiones` | `aplicacion/puertos/uso.py` | `permitir(cliente_id: int, ahora: datetime) → int ∣ None` | `LimitadorEnMemoria` (`salida/persistencia/limitador.py`) | `LimitadorEnMemoria` |
| `Transcriptor` | `aplicacion/puertos/voz.py` | `transcribir(audio: bytes, nombre_fichero: str) → str` | `TranscriptorWhisper` (`salida/voz/whisper.py`) | `TranscriptorFalso (test_http)` |
| `Sintetizador` | `aplicacion/puertos/voz.py` | `disponible() → bool`<br>`sintetizar(texto: str) → bytes` | `SintetizadorPiper` (`salida/voz/piper.py`) | `SintetizadorFalso (test_http)` |

## Casos de uso (24)

| Caso de uso | Fichero | Puertos que usa | Lo llama |
|---|---|---|---|
| `IniciarSesion` | `aplicacion/casos_uso/acceso.py` | `RepositorioClientes`, `Hasheador`, `SesionesAutenticadas`, `RegistroIntentos`, `Reloj`, `Auditoria` | POST /auth/login |
| `IdentificarCliente` | `aplicacion/casos_uso/acceso.py` | `SesionesAutenticadas`, `RepositorioClientes` | dependencia de todos los endpoints protegidos |
| `CerrarSesion` | `aplicacion/casos_uso/acceso.py` | `SesionesAutenticadas`, `Auditoria` | POST /auth/logout |
| `GestionAjustes` | `aplicacion/casos_uso/ajustes.py` | `RepositorioAjustes`, `SondaProveedores`, `frozenset[str]`, `Auditoria | None` | /ajustes/* |
| `ConsultarSaldo` | `aplicacion/casos_uso/banco.py` | `RepositorioCuenta` | herramienta consultar_saldo · GET /api/banco/saldo |
| `ListarContactos` | `aplicacion/casos_uso/banco.py` | `RepositorioContactos` | herramienta listar_contactos_bizum · GET /api/banco/contactos |
| `ConsultarMovimientos` | `aplicacion/casos_uso/banco.py` | `ConsultorMovimientos`, `Auditoria` | herramienta consultar_movimientos · GET /api/banco/movimientos |
| `SolicitarBizum` | `aplicacion/casos_uso/bizum.py` | `RepositorioCuenta`, `RepositorioContactos`, `RepositorioOperaciones`, `GeneradorCodigos`, `CanalOTP`, `Reloj`, `Auditoria` | herramienta transferencia_bizum · POST /api/banco/bizum |
| `ConfirmarOperacion` | `aplicacion/casos_uso/bizum.py` | `RepositorioCuenta`, `RepositorioOperaciones`, `Reloj`, `Auditoria`, `CerrojosPorCliente`, `DesbloquearTarjeta` | POST /operaciones/{id}/confirmar y /aprobar |
| `CancelarOperacion` | `aplicacion/casos_uso/bizum.py` | `RepositorioOperaciones`, `Auditoria`, `CerrojosPorCliente` | POST /operaciones/{id}/cancelar |
| `CerrojosPorCliente` | `aplicacion/casos_uso/cerrojos.py` | — | — |
| `ConsultarEstado` | `aplicacion/casos_uso/estado.py` | `RepositorioAjustes`, `Sintetizador` | GET /estado |
| `GraficoDeFuente` | `aplicacion/casos_uso/graficos.py` | — | — |
| `GenerarGraficoDeFuente` | `aplicacion/casos_uso/graficos.py` | `ConsultarMovimientos`, `Reloj` | — |
| `LeerMensajesMovil` | `aplicacion/casos_uso/movil.py` | `BandejaMovil` | GET /movil/mensajes |
| `ConsultarTarjetas` | `aplicacion/casos_uso/tarjetas.py` | `RepositorioTarjetas` | herramienta consultar_tarjetas · GET /api/banco/tarjetas |
| `BloquearTarjeta` | `aplicacion/casos_uso/tarjetas.py` | `RepositorioTarjetas`, `Reloj`, `Auditoria`, `RepositorioOperaciones`, `CerrojosPorCliente` | herramienta bloquear_tarjeta (sin OTP, auditado) |
| `SolicitarDesbloqueoTarjeta` | `aplicacion/casos_uso/tarjetas.py` | `RepositorioTarjetas`, `RepositorioOperaciones`, `GeneradorCodigos`, `CanalOTP`, `Reloj`, `Auditoria` | herramienta desbloquear_tarjeta (operación pendiente de OTP) |
| `DesbloquearTarjeta` | `aplicacion/casos_uso/tarjetas.py` | `RepositorioTarjetas`, `Auditoria` | la ejecuta ConfirmarOperacion al confirmar el desbloqueo |
| `ConsultarUso` | `aplicacion/casos_uso/uso.py` | `RegistroUso`, `PresupuestoUso`, `Reloj` | GET /api/uso |
| `UsoDeCliente` | `aplicacion/casos_uso/uso.py` | — | — |
| `AdministrarUso` | `aplicacion/casos_uso/uso.py` | `RepositorioClientes`, `RegistroUso`, `PresupuestoUso`, `Reloj`, `Auditoria` | — |
| `TranscribirAudio` | `aplicacion/casos_uso/voz.py` | `Transcriptor`, `RepositorioAjustes`, `LimitadorPeticiones`, `Reloj` | POST /stt |
| `SintetizarVoz` | `aplicacion/casos_uso/voz.py` | `Sintetizador`, `LimitadorPeticiones`, `Reloj` | POST /tts |

## Herramientas del agente (8)

| Herramienta | Riesgo | Fichero | Estado en pantalla |
|---|---|---|---|
| `consultar_saldo` | lectura | `aplicacion/herramientas/saldo.py` | Consultando saldo… |
| `listar_contactos_bizum` | lectura | `aplicacion/herramientas/contactos.py` | Buscando contactos… |
| `transferencia_bizum` | escritura | `aplicacion/herramientas/bizum.py` | Preparando el Bizum… |
| `consultar_movimientos` | lectura | `aplicacion/herramientas/movimientos.py` | Analizando tus movimientos… |
| `generar_grafico` | lectura | `aplicacion/herramientas/grafico.py` | Generando gráfico… |
| `consultar_tarjetas` | lectura | `aplicacion/herramientas/tarjetas.py` | Consultando tus tarjetas… |
| `bloquear_tarjeta` | proteccion | `aplicacion/herramientas/tarjetas.py` | Bloqueando la tarjeta… |
| `desbloquear_tarjeta` | escritura | `aplicacion/herramientas/tarjetas.py` | Preparando el desbloqueo… |

## Endpoints (27)

| Método | Ruta | Auth | Petición | Respuesta | Errores |
|---|---|---|---|---|---|
| POST | `/auth/login` | no | PeticionLogin | ClienteOut | 401, 429 |
| GET | `/auth/yo` | sí | — | ClienteOut | 401 |
| POST | `/auth/logout` | no | — | OkOut | — |
| GET | `/api/banco/saldo` | sí | — | CuentaOut | 401 |
| GET | `/api/banco/contactos` | sí | — | lista de ContactoOut | 401 |
| GET | `/api/banco/tarjetas` | sí | — | lista de TarjetaOut | 401 |
| POST | `/api/banco/bizum` | sí | PeticionBizum | BizumPendienteOut | 401, 404, 409 |
| GET | `/api/banco/movimientos` | sí | — | ConsultaOut | 401 |
| POST | `/operaciones/{id_operacion}/confirmar` | sí | PeticionCodigo | ComprobanteOut o ComprobanteTarjetaOut | 400, 401, 404, 409, 410, 423 |
| POST | `/operaciones/{id_operacion}/aprobar` | sí | — | ComprobanteOut o ComprobanteTarjetaOut | 401, 404, 409, 410 |
| POST | `/operaciones/{id_operacion}/cancelar` | sí | — | OkOut | 401, 404, 409 |
| GET | `/movil/mensajes` | sí | — | lista de SmsOut | 401 |
| GET | `/api/uso` | sí | — | UsoOut | 401 |
| GET | `/api/admin/uso` | sí | — | lista de UsoClienteOut | 401, 403 |
| POST | `/api/admin/uso/{usuario}/reiniciar` | sí | — | UsoClienteOut | 401, 403, 404 |
| GET | `/ajustes` | sí | — | AjustesOut | 401, 403 |
| POST | `/ajustes/probar` | sí | PeticionProbar | PruebaClaveOut | 401, 403, 404 |
| POST | `/ajustes/claves` | sí | PeticionClave | AjustesConMensajeOut | 401, 403, 404 |
| PATCH | `/ajustes/claves/{proveedor}` | sí | PeticionModelos | AjustesOut | 401, 403, 404 |
| DELETE | `/ajustes/claves/{proveedor}` | sí | — | AjustesOut | 401, 403 |
| POST | `/ajustes/activar` | sí | PeticionActivar | AjustesOut | 401, 403, 404 |
| PUT | `/ajustes/ollama` | sí | PeticionOllama | AjustesOut | 401, 403 |
| GET | `/ajustes/ollama/estado` | sí | — | EstadoOllamaOut | 401, 403 |
| POST | `/chat` | sí | PeticionChat | — | 400, 401, 413, 429 |
| POST | `/stt` | sí | — | TranscripcionOut | 401, 413, 415, 429, 502, 503, 504 |
| POST | `/tts` | sí | PeticionTTS | — | 401, 429, 503 |
| GET | `/estado` | sí | — | EstadoOut | 401 |

## Tests (693)

| Fichero | Pruebas |
|---|---|
| `tests/test_acceso.py` | 18 |
| `tests/test_agente.py` | 48 |
| `tests/test_arquitectura.py` | 73 |
| `tests/test_bizum_otp.py` | 33 |
| `tests/test_chat.py` | 13 |
| `tests/test_dominio.py` | 18 |
| `tests/test_endurecimiento_ronda4.py` | 28 |
| `tests/test_errores_http.py` | 44 |
| `tests/test_graficos.py` | 29 |
| `tests/test_http.py` | 80 |
| `tests/test_ollama_seguro.py` | 3 |
| `tests/test_persistencia.py` | 8 |
| `tests/test_seguridad_chat.py` | 6 |
| `tests/test_sqlite.py` | 56 |
| `tests/test_tarjetas.py` | 167 |
| `tests/test_texto.py` | 9 |
| `tests/test_uso.py` | 54 |
| `tests/test_uso_http.py` | 6 |
