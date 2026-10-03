"""Conversión de objetos de la aplicación a las respuestas JSON de la API."""
from ....aplicacion.casos_uso.estado import EstadoSistema
from ....aplicacion.casos_uso.uso import ResumenUso
from ....dominio.ajustes import Ajustes, enmascarar
from ....dominio.modelos import Cliente, ComprobanteBizum, Cuenta, ResultadoConsulta
from ....dominio.operaciones import OperacionPendiente
from ....dominio.proveedores import CATALOGO, ModeloRef


def cliente(c: Cliente) -> dict:
    return {"usuario": c.usuario, "nombre": c.nombre, "es_admin": c.es_admin}


def operacion_pendiente(o: OperacionPendiente) -> dict:
    """Nunca incluye el código ni su huella."""
    return {
        "id": o.id,
        "destinatario": o.destinatario,
        "importe": o.importe,
        "concepto": o.concepto,
        "alertas": list(o.alertas),
        "caduca": o.caduca.isoformat(),
    }


def uso(r: ResumenUso) -> dict:
    return {
        "tokens_hoy": r.tokens_hoy, "limite_dia": r.limite_dia, "restante": r.restante, "porcentaje": r.porcentaje,
        "por_turno": r.por_turno, "peticiones_por_minuto": r.peticiones_por_minuto,
        "max_caracteres_mensaje": r.max_caracteres_mensaje, "ultimos": r.ultimos,
    }


def cuenta(c: Cuenta) -> dict:
    return {"iban": c.iban, "titular": c.titular, "saldo": c.saldo}


def comprobante_bizum(c: ComprobanteBizum) -> dict:
    return {
        "ok": True,
        "destinatario": c.destinatario,
        "telefono": c.telefono,
        "importe": c.importe,
        "concepto": c.concepto,
        "nuevo_saldo": round(c.nuevo_saldo, 2),
    }


def resultado_consulta(r: ResultadoConsulta) -> dict:
    return {"ok": True, "columnas": r.columnas, "filas": r.filas, "num_filas": len(r.filas), "truncado": r.truncado}


def cadena_legible(cadena: list[ModeloRef]) -> list[str]:
    return [f"{e.modelo} ({e.proveedor})" for e in cadena]


def estado(e: EstadoSistema) -> dict:
    return {
        "ok": True,
        "proveedor": e.principal.proveedor if e.principal else None,
        "modelo": e.principal.modelo if e.principal else None,
        "cadena_fallback": cadena_legible(e.cadena),
        "voz_disponible": e.voz_entrada,
        "tts_servidor": e.voz_servidor,
        "configurado": e.configurado,
    }


def vista_ajustes(a: Ajustes) -> dict:
    """Ajustes para el frontend: las claves API nunca salen, solo su máscara."""
    cadena = a.cadena_llm()
    transcripcion = a.transcripcion()
    return {
        "activo": a.activo,
        "configurado": a.configurado,
        "claves": [
            {
                "proveedor": p,
                "nombre": CATALOGO[p].nombre,
                "mascara": enmascarar(cfg.api_key),
                "modelo": cfg.modelo,
                "modelo_respaldo": cfg.modelo_respaldo,
                "modelos": cfg.modelos,
            }
            for p, cfg in a.claves.items()
            if p in CATALOGO
        ],
        "catalogo": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "url_claves": p.url_claves,
                "prefijo": p.prefijo,
                "nota": p.nota,
                "modelo": p.modelo,
                "modelo_respaldo": p.modelo_respaldo,
            }
            for p in CATALOGO.values()
        ],
        "ollama": {"url": a.ollama_url, "modelo": a.ollama_modelo, "fallback_local": a.fallback_local},
        "voz_entrada": CATALOGO[transcripcion.proveedor].nombre if transcripcion else None,
        "proveedor": cadena[0].proveedor if cadena else None,
        "modelo": cadena[0].modelo if cadena else None,
        "cadena_fallback": cadena_legible(cadena),
    }
