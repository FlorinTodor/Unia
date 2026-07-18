# Registro de incidencias y arreglos

Problemas reales encontrados durante las pruebas (18 de julio de 2026), su causa raíz
y dónde está el arreglo. Material directo para el apartado de robustez de la memoria.

| # | Síntoma | Causa raíz | Arreglo | Dónde |
|---|---|---|---|---|
| 1 | Respuestas que tardan «unos segundos» de forma intermitente | 429 por límite de tokens/minuto de Groq (12k TPM); el cliente reintentaba en silencio con backoff | `max_retries=0` + salto inmediato al siguiente proveedor de la cadena | `config.cliente_para`, `agente.responder` |
| 2 | Cuota diaria de Groq fundida en una tarde (100k tokens/día) | cada petición reenviaba TODO el historial, incluidas 200 filas SQL de un «muéstrame todos los movimientos» | compactación de historial (~90 % menos tokens) + tope de 60 filas + norma de agregación | `main._compactar_historial`, `db.ejecutar_select`, prompt n.3 |
| 3 | Mensaje fantasma «¿Hvað er misal, doctor?» al usar el micrófono | alucinación de Whisper con audio corto/silencio | rechazo de audio <4000 bytes, `temperature=0`, prompt de dominio | `main.stt` |
| 4 | El asistente respondía encantado sobre libros litúrgicos | sin límite de ámbito en el prompt | norma 8 (solo finanzas, reconduce el resto) + norma 9 (transcripciones sin sentido → pedir repetición) | prompt |
| 5 | Burbuja «⚠️ Failed to parse tool call arguments as JSON» | error de generación de Groq (JSON de herramienta inválido), esporádico; además llegaba en mitad del stream, fuera del try | try cubre el consumo del stream; hasta 2 reintentos silenciosos | `agente.responder` |
| 6 | «No he podido completar la operación» en tareas complejas | los saltos de proveedor y reintentos consumían rondas del agente (quedaban 4 de 6) | los saltos/reintentos ya no cuentan; si se agotan de verdad, llamada final sin herramientas que resume lo conseguido | `agente.responder` |
| 7 | Burbuja vacía al final de algunas respuestas | el frontend pintaba burbuja aunque `fin` llegara sin texto | guard de contenido antes de crear burbuja | `app.js` |
| 8 | «18 de julio de 202​​2026» | el modelo cuela caracteres unicode invisibles (zero-width) | saneado de `​‌‍⁠﻿` en todo lo emitido | `main._RE_INVISIBLES` |
| 9 | La voz no sonaba en absoluto | Chrome en Linux no trae voces de `speechSynthesis` (falla silenciosa) | TTS dual: navegador si hay voces, si no Piper en el servidor (`/tts`) | `app.js::leerEnVozAlta`, `main.tts` |
| 10 | La voz leía «4-9-5-2» dígito a dígito | fonetizador de Piper no expande números | normalización con num2words antes de sintetizar (importes → «X euros con Y céntimos»; >7 dígitos se dejan: teléfonos/IBAN) | `main._normalizar_para_voz` |
| 11 | Voz demasiado lenta | ritmo por defecto de la voz sharvard | `length_scale` 0.78 configurable (`TTS_LENGTH_SCALE`) | `main.tts` |
| 12 | La voz leía las tablas markdown enteras («ID, categoría, concepto…») y las tablas se veían como texto crudo | el chat no renderizaba tablas y el TTS recibía el markdown completo | marked+DOMPurify para render; el TTS filtra líneas de tabla/código; norma: toda tabla lleva conclusión en prosa (eso es lo que se lee) | `index.html`, `app.js`, `styles.css`, prompt n.7 |
| 13 | Latencia de ~13 s con el modelo local | modo *thinking* de qwen3 activado por defecto | `reasoning_effort: "none"` vía extra_body (→ 2-3 s por turno) | `agente._extra_params` |
| 14 | «Último movimiento» equivocado entre dos del mismo día | `fecha` no tiene hora; `ORDER BY fecha DESC` empata y SQLite devuelve cualquiera | norma: desempatar con `ORDER BY fecha DESC, id DESC` | prompt n.3 |
| 15 | Movimiento con fecha futura (Spotify el 20 siendo día 18) | el generador añadía los recibos del mes en curso sin comprobar el rango | guard de rango en `add()` del generador | `db._generar_movimientos` |
| 16 | Al comparar «julio y marzo» mezcló julio de 2025 y 2026; etiquetó Bizums recibidos como «Nómina»; narraba «Paso 1 / Paso 2»; «haz lo mismo» no replicaba el gráfico | ambigüedad de año sin regla; el modelo reetiquetaba resultados; estilo verboso de gpt-oss; petición relativa sin regla | normas: mes sin año = más reciente; etiquetas tal cual la BD; prohibido narrar pasos; «lo mismo con X» = replicar formato | prompt n.2, 6, 10 |
| 17 | El Bizum de prueba «desapareció» | regeneración manual de la BD (semilla fija) para arreglar #15 | comportamiento esperado: la BD solo se regenera a propósito; documentado | `db.inicializar` |

## Lecciones generales

- **Los límites gratuitos son por modelo y por día**: diseñar siempre para el 429.
- **Todo fallo de voz tiene causa concreta** (alucinación de silencio, voces
  inexistentes en Linux, números sin expandir): probar en la plataforma real del
  usuario, no asumir el comportamiento del navegador.
- **Cada rareza del modelo se convierte en norma de prompt** — el system prompt es
  el changelog de todos los malentendidos observados.
- Las pruebas destructivas del usuario («muéstrame todo», preguntas trampa,
  peticiones dobles) destaparon más bugs que cualquier test sintético.
