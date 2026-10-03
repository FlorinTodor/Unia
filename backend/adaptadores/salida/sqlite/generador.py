"""Generador procedural de movimientos ficticios con patrones realistas de un usuario español.

Semilla fija para que la demo sea reproducible.
"""
import random
from datetime import date, timedelta

from ....dominio.modelos import Contacto, Movimiento

TITULAR = "Alex García"
IBAN = "ES21 2103 0000 1122 3344 5566"
SALDO_INICIAL = 1200.00

SUPERMERCADOS = ["Mercadona", "Carrefour", "Lidl", "Dia", "Alcampo"]
RESTAURANTES = ["Bar Manolo", "La Trattoria", "Sushi Go", "Burger King", "100 Montaditos", "El Rincón de Ana"]
GASOLINERAS = ["Repsol", "Cepsa", "BP"]
TIENDAS_ROPA = ["Zara", "Primark", "Decathlon", "Pull&Bear"]
OCIO = ["Cine Kinépolis", "Bolera Ozone", "Entradas.com", "Steam"]
FARMACIAS = ["Farmacia Central", "Farmacia San Juan"]
CONTACTOS = [
    Contacto("María López", "600111222"),
    Contacto("Pablo Ruiz", "611333444"),
    Contacto("Lucía Fernández", "622555666"),
    Contacto("Javi Moreno", "633777888"),
]


def generar_movimientos(desde: date, hasta: date) -> list[Movimiento]:
    rng = random.Random(42)
    movs: list[Movimiento] = []

    def add(d: date, cat: str, concepto: str, comercio: str, importe: float):
        # nunca generar movimientos fuera del rango (p. ej. recibos con fecha futura)
        if desde <= d <= hasta:
            movs.append(Movimiento(d, cat, concepto, comercio, round(importe, 2)))

    # Mensuales fijos
    mes = date(desde.year, desde.month, 1)
    while mes <= hasta:
        def dia(n):
            return mes.replace(day=n)

        if dia(1) >= desde:
            add(dia(1), "Nómina", "Nómina Tecnosur SL", "Tecnosur SL", 1850.00)
            add(dia(2), "Vivienda", "Alquiler piso c/ Recogidas", "Inmobiliaria Genil", -650.00)
        if desde <= dia(5) <= hasta:
            add(dia(5), "Suscripciones", "Fibra + móvil", "Digi", -34.90)
            add(dia(3), "Deporte", "Cuota mensual gimnasio", "Basic-Fit", -29.90)
            add(dia(10), "Vivienda", "Factura electricidad", "Endesa", -round(rng.uniform(42, 78), 2))
            add(dia(15), "Suscripciones", "Netflix", "Netflix", -12.99)
            add(dia(20), "Suscripciones", "Spotify Premium", "Spotify", -10.99)
            if mes.month % 2 == 0:
                add(dia(12), "Vivienda", "Factura agua", "Emasagra", -round(rng.uniform(25, 38), 2))
        # siguiente mes
        mes = (mes.replace(day=28) + timedelta(days=5)).replace(day=1)

    # Variables día a día
    d = desde
    while d <= hasta:
        if rng.random() < 0.30:
            add(d, "Supermercado", "Compra alimentación", rng.choice(SUPERMERCADOS), -rng.uniform(8, 70))
        if d.weekday() >= 4 and rng.random() < 0.35:
            add(d, "Restaurantes", "Comida/cena fuera", rng.choice(RESTAURANTES), -rng.uniform(9, 55))
        if rng.random() < 0.07:
            add(d, "Transporte", "Combustible", rng.choice(GASOLINERAS), -rng.uniform(30, 65))
        if rng.random() < 0.04:
            add(d, "Ropa", "Compra ropa/deporte", rng.choice(TIENDAS_ROPA), -rng.uniform(12, 75))
        if rng.random() < 0.06:
            add(d, "Ocio", "Ocio y entretenimiento", rng.choice(OCIO), -rng.uniform(6, 40))
        if rng.random() < 0.04:
            add(d, "Salud", "Farmacia", rng.choice(FARMACIAS), -rng.uniform(4, 28))
        if rng.random() < 0.04:
            add(d, "Compras online", "Pedido online", "Amazon", -rng.uniform(9, 90))
        if rng.random() < 0.08:
            contacto = rng.choice(CONTACTOS)
            if rng.random() < 0.55:
                add(d, "Bizum", f"Bizum enviado a {contacto.nombre}", "Bizum", -rng.uniform(5, 60))
            else:
                add(d, "Bizum", f"Bizum recibido de {contacto.nombre}", "Bizum", rng.uniform(5, 60))
        d += timedelta(days=1)

    movs.sort(key=lambda m: m.fecha)
    return movs
