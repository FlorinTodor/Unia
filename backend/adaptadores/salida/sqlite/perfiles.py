"""Los cuatro clientes ficticios de la demo, con vidas financieras distintas."""
import os
from dataclasses import dataclass

from ....dominio.modelos import Contacto


@dataclass(frozen=True)
class Fijo:
    """Movimiento mensual (nómina, alquiler, recibos). `importe` fijo o (mín, máx) para facturas variables."""

    dia: int
    categoria: str
    concepto: str
    comercio: str
    importe: float | tuple[float, float]
    cada_meses: int = 1  # 2 = solo en meses pares (agua)


@dataclass(frozen=True)
class Habito:
    """Gasto que ocurre al azar cada día con cierta probabilidad."""

    categoria: str
    concepto: str
    comercios: tuple[str, ...]
    prob: float
    rango: tuple[float, float]
    solo_finde: bool = False  # viernes a domingo


@dataclass(frozen=True)
class Perfil:
    usuario: str
    nombre: str
    telefono: str
    iban: str
    semilla: int
    saldo_actual: float  # saldo con el que arranca la demo (el generador no lo deduce de los movimientos)
    fijos: tuple[Fijo, ...]
    habitos: tuple[Habito, ...]
    bizum_prob: float
    bizum_rango: tuple[float, float]
    contactos: tuple[Contacto, ...]


ALEX = Perfil(
    usuario="alex", nombre="Alex García", telefono="611000111",
    iban="ES21 2103 0000 1122 3344 5566", semilla=42, saldo_actual=4200.0,
    fijos=(
        Fijo(1, "Nómina", "Nómina Tecnosur SL", "Tecnosur SL", 1850.00),
        Fijo(2, "Vivienda", "Alquiler piso c/ Recogidas", "Inmobiliaria Genil", -650.00),
        Fijo(3, "Deporte", "Cuota mensual gimnasio", "Basic-Fit", -29.90),
        Fijo(5, "Suscripciones", "Fibra + móvil", "Digi", -34.90),
        Fijo(10, "Vivienda", "Factura electricidad", "Endesa", (-78.0, -42.0)),
        Fijo(12, "Vivienda", "Factura agua", "Emasagra", (-38.0, -25.0), cada_meses=2),
        Fijo(15, "Suscripciones", "Netflix", "Netflix", -12.99),
        Fijo(20, "Suscripciones", "Spotify Premium", "Spotify", -10.99),
    ),
    habitos=(
        Habito("Supermercado", "Compra alimentación", ("Mercadona", "Carrefour", "Lidl", "Dia", "Alcampo"), 0.30, (8, 70)),
        Habito("Restaurantes", "Comida/cena fuera", ("Bar Manolo", "La Trattoria", "Sushi Go", "Burger King", "100 Montaditos", "El Rincón de Ana"), 0.35, (9, 55), solo_finde=True),
        Habito("Transporte", "Combustible", ("Repsol", "Cepsa", "BP"), 0.07, (30, 65)),
        Habito("Ropa", "Compra ropa/deporte", ("Zara", "Primark", "Decathlon", "Pull&Bear"), 0.04, (12, 75)),
        Habito("Ocio", "Ocio y entretenimiento", ("Cine Kinépolis", "Bolera Ozone", "Entradas.com", "Steam"), 0.06, (6, 40)),
        Habito("Salud", "Farmacia", ("Farmacia Central", "Farmacia San Juan"), 0.04, (4, 28)),
        Habito("Compras online", "Pedido online", ("Amazon",), 0.04, (9, 90)),
    ),
    bizum_prob=0.08, bizum_rango=(5, 60),
    contactos=(
        Contacto("María López", "600111222"), Contacto("Pablo Ruiz", "611333444"),
        Contacto("Lucía Fernández", "622555666"), Contacto("Javi Moreno", "633777888"),
    ),
)

ANA = Perfil(
    usuario="ana", nombre="Ana Ruiz", telefono="622000222",
    iban="ES64 2103 0000 2233 4455 6677", semilla=7, saldo_actual=480.0,
    fijos=(
        Fijo(1, "Vivienda", "Habitación piso compartido", "Inmobiliaria Albaicín", -280.00),
        Fijo(2, "Transporte", "Abono mensual bus universitario", "Rober Granada", -20.00),
        Fijo(3, "Nómina", "Ayuda familiar", "Familia Ruiz", 300.00),
        Fijo(5, "Suscripciones", "Móvil prepago", "Lowi", -9.99),
        Fijo(10, "Nómina", "Beca de colaboración", "Universidad de Granada", 250.00),
        Fijo(15, "Suscripciones", "Spotify Estudiantes", "Spotify", -5.99),
    ),
    habitos=(
        Habito("Supermercado", "Compra alimentación", ("Mercadona", "Lidl", "Dia"), 0.22, (5, 30)),
        Habito("Restaurantes", "Comida fuera", ("Bar Manolo", "100 Montaditos", "Burger King", "Telepizza"), 0.22, (5, 20)),
        Habito("Ocio", "Salir de fiesta", ("Discoteca Granada 10", "Cine Kinépolis", "Entradas.com"), 0.10, (5, 30)),
        Habito("Ropa", "Compra ropa", ("Primark", "Pull&Bear", "Shein"), 0.03, (10, 45)),
        Habito("Compras online", "Pedido online", ("Amazon", "Wallapop"), 0.05, (5, 40)),
        Habito("Educación", "Fotocopias y libros", ("Copistería Campus", "Librería Técnica"), 0.04, (3, 40)),
    ),
    bizum_prob=0.18, bizum_rango=(3, 30),
    contactos=(
        Contacto("Carmen Soler", "655010101"), Contacto("Dani Ortega", "655020202"),
        Contacto("Irene Vidal", "655030303"), Contacto("Mamá", "655040404"),
    ),
)

MARTA = Perfil(
    usuario="marta", nombre="Marta Moreno", telefono="633000333",
    iban="ES18 2103 0000 3344 5566 7788", semilla=21, saldo_actual=3650.0,
    fijos=(
        Fijo(1, "Nómina", "Nómina Hospital Clínico", "SAS", 2100.00),
        Fijo(1, "Nómina", "Nómina pareja", "Construcciones Vega SL", 1500.00),
        Fijo(3, "Vivienda", "Cuota hipoteca", "Unicaja Banco", -820.00),
        Fijo(5, "Educación", "Cuota colegio concertado", "Colegio Sagrada Familia", -145.00),
        Fijo(7, "Suscripciones", "Fibra, móviles y TV", "Movistar", -79.90),
        Fijo(10, "Vivienda", "Factura electricidad", "Endesa", (-130.0, -70.0)),
        Fijo(12, "Vivienda", "Factura agua", "Emasagra", (-70.0, -40.0), cada_meses=2),
        Fijo(18, "Vivienda", "Seguro del hogar", "Mapfre", -48.00),
    ),
    habitos=(
        Habito("Supermercado", "Compra semanal", ("Mercadona", "Carrefour", "Alcampo"), 0.55, (30, 120)),
        Habito("Restaurantes", "Comida en familia", ("La Trattoria", "Burger King", "El Rincón de Ana"), 0.30, (25, 80), solo_finde=True),
        Habito("Transporte", "Combustible", ("Repsol", "Cepsa"), 0.15, (45, 80)),
        Habito("Ropa", "Ropa y calzado", ("Zara Kids", "Decathlon", "El Corte Inglés"), 0.08, (20, 120)),
        Habito("Ocio", "Ocio familiar", ("Cine Kinépolis", "Parque de las Ciencias"), 0.10, (10, 70)),
        Habito("Salud", "Farmacia y pediatra", ("Farmacia Central", "Clínica Dental Sonrisa"), 0.08, (10, 60)),
        Habito("Compras online", "Pedido online", ("Amazon", "Zalando"), 0.10, (15, 110)),
    ),
    bizum_prob=0.06, bizum_rango=(5, 40),
    contactos=(
        Contacto("Jorge Vega", "666010101"), Contacto("Abuela Pilar", "666020202"),
        Contacto("Cole - Extraescolares", "666030303"), Contacto("Sofía Navarro", "666040404"),
    ),
)

JOSE = Perfil(
    usuario="jose", nombre="José Luis Romero", telefono="644000444",
    iban="ES95 2103 0000 4455 6677 8899", semilla=3, saldo_actual=9400.0,
    fijos=(
        Fijo(1, "Nómina", "Pensión de jubilación", "Seguridad Social", 1480.00),
        Fijo(5, "Vivienda", "Cuota comunidad de vecinos", "Comunidad Calle Elvira", -62.00),
        Fijo(8, "Suscripciones", "Teléfono fijo y ADSL", "Movistar", -24.50),
        Fijo(10, "Vivienda", "Factura electricidad", "Endesa", (-95.0, -55.0)),
        Fijo(12, "Vivienda", "Factura agua", "Emasagra", (-45.0, -30.0), cada_meses=2),
        Fijo(20, "Suscripciones", "Seguro de decesos", "Santa Lucía", -31.00),
    ),
    habitos=(
        Habito("Supermercado", "Compra de la semana", ("Mercadona", "Dia", "Coviran"), 0.35, (6, 40)),
        Habito("Salud", "Farmacia", ("Farmacia San Juan", "Farmacia Central"), 0.22, (4, 45)),
        Habito("Restaurantes", "Café y menú", ("Bar Manolo", "Cafetería Alhambra"), 0.08, (3, 18), solo_finde=True),
        Habito("Ocio", "Quiniela y lotería", ("Administración de Loterías",), 0.05, (2, 15)),
        Habito("Transporte", "Taxi", ("Radio Taxi Granada",), 0.03, (6, 15)),
    ),
    bizum_prob=0.03, bizum_rango=(5, 30),
    contactos=(
        Contacto("Hijo Miguel", "677010101"), Contacto("Hija Elena", "677020202"),
        Contacto("Vecina Rosa", "677030303"), Contacto("Nieto Hugo", "677040404"),
    ),
)

PERFILES = (ALEX, ANA, MARTA, JOSE)


class _Administrador:
    """Perfil de gestión: configura la IA (claves, modelos, Ollama). Sin cuenta bancaria."""

    usuario = "admin"
    nombre = "Administrador"
    telefono = "+34 600 000 000"


ADMIN = _Administrador()


ANIO_DEMO = 2026


def contrasena_demo(usuario: str) -> str:
    """Contraseña con la que se siembra la base de datos (que solo guarda su hash).

    No hay contraseñas escritas en el código: se toma de `CONTRASENA_<USUARIO>` (p. ej. en `.env`) y, si no
    existe, es el usuario seguido del año de la demo. Cámbiala con la variable de entorno al desplegar.
    """
    return os.getenv(f"CONTRASENA_{usuario.upper()}") or f"{usuario}{ANIO_DEMO}"
