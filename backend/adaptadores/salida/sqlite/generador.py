"""Generador procedural de movimientos ficticios a partir de un perfil. Semilla fija: demo reproducible."""
import random
from datetime import date, timedelta

from ....dominio.modelos import Movimiento
from .perfiles import Perfil


def generar_movimientos(perfil: Perfil, desde: date, hasta: date) -> list[Movimiento]:
    rng = random.Random(perfil.semilla)
    movs: list[Movimiento] = []

    def anadir(d: date, cat: str, concepto: str, comercio: str, importe: float):
        # nunca generar movimientos fuera del rango (p. ej. recibos con fecha futura)
        if desde <= d <= hasta:
            movs.append(Movimiento(d, cat, concepto, comercio, round(importe, 2)))

    # mensuales fijos
    mes = date(desde.year, desde.month, 1)
    while mes <= hasta:
        for f in perfil.fijos:
            if mes.month % f.cada_meses != 0 and f.cada_meses > 1:
                continue
            importe = rng.uniform(*f.importe) if isinstance(f.importe, tuple) else f.importe
            anadir(mes.replace(day=f.dia), f.categoria, f.concepto, f.comercio, importe)
        mes = (mes.replace(day=28) + timedelta(days=5)).replace(day=1)  # siguiente mes

    # hábitos día a día
    d = desde
    while d <= hasta:
        for h in perfil.habitos:
            if h.solo_finde and d.weekday() < 4:
                continue
            if rng.random() < h.prob:
                anadir(d, h.categoria, h.concepto, rng.choice(h.comercios), -rng.uniform(*h.rango))
        if rng.random() < perfil.bizum_prob:
            contacto = rng.choice(perfil.contactos)
            importe = rng.uniform(*perfil.bizum_rango)
            if rng.random() < 0.55:
                anadir(d, "Bizum", f"Bizum enviado a {contacto.nombre}", "Bizum", -importe)
            else:
                anadir(d, "Bizum", f"Bizum recibido de {contacto.nombre}", "Bizum", importe)
        d += timedelta(days=1)

    movs.sort(key=lambda m: m.fecha)
    return movs
