# Marca e interfaz: Unia, el asistente de Unicaja

## El nombre

**Unia** = *Unicaja* + *IA*. Es corto (cuatro letras), se pronuncia fácil («oye, Unia») y funciona bien por voz,
que es el canal principal del reto. Va acompañado de un descriptor, *asistente de Unicaja*, y de un lema,
*Tu banca, en una conversación*. «Habla con tu dinero» sigue siendo el nombre del **reto** (de la Cátedra), no
del producto: se usa en la memoria y en la documentación, pero no en la interfaz.

Se descartaron: *Uni* (se confunde con «universidad», y el proyecto es de la UGR), *Cuenta conmigo* (más largo y ya
parece un eslogan) y un nombre de persona (*Eva*, *Lola*), porque ya lo usan otros bancos.

**Cambiarlo es una línea:** `frontend/js/marca.js` (nombre, descriptor, lema y paleta de los gráficos). El prompt del
modelo (`backend/aplicacion/prompt.py`: «Te llamas Unia») y el título de la API (`entrada/http/app.py`) son los otros
dos sitios.

## Colores

Salen de la propia web de Unicaja (`unicajabanco.es`, hoja de estilos `clientlib-base`, octubre de 2026). Su sistema de
diseño declara cada color por su uso, así que se respetan los mismos papeles:

| Papel | Color | Uso en Unia |
|---|---|---|
| Petróleo (cabecera y botones de Unicaja) | `#005265` | cabecera, saldo, botones, burbujas del usuario |
| Petróleo oscuro (hover de sus botones) | `#00323a` | degradados, texto sobre lima |
| Verde Unicaja (acento, hover de enlaces) | `#278600` | borde de la tarjeta de confirmación, estado activo |
| Lima (botones secundarios) | `#95e891` | sello «u», barra de uso, botones en modo oscuro |
| Ámbar (botones de aviso) | `#edaf21` | segundo color de los gráficos y aviso de uso medio |
| Tinta (texto) | `#14232b` | texto principal |
| Éxito / información / peligro / aviso | `#048848` · `#026169` · `#cc2830` · `#825300` | ingresos, iconos, errores, avisos |
| Tintas claras | `#e6f3ed` · `#e6f3f4` · `#faeaea` · `#fdf5e6` | fondos de esos estados |
| Neutros | `#f6f9f9` · `#e5eef0` · `#d0dad6` | fondo, bordes |

**Tipografía:** Manrope, la misma de su web (`frontend/fonts`, licencia OFL). Se sirve desde el propio servidor: la
política de seguridad del navegador no permite cargar tipografías de otros dominios, no se envían datos a terceros y
funciona sin internet.

**Modo oscuro** automático según el sistema: mismos colores, con tonos claros del petróleo y del verde para los textos y
los gráficos.

### Contraste (WCAG AA, mínimo 4,5:1 en texto)

Medido con la fórmula de la guía WCAG 2.1: texto sobre blanco 16,1; petróleo sobre blanco 8,8; blanco sobre petróleo 8,8;
verde `#278600` sobre blanco 4,7; peligro 5,4; aviso 6,6. Un único par de su paleta no llega: el verde de éxito
`#048848` sobre su tinta clara da 3,98, así que el texto de ingresos usa `#046a38` (5,9). En oscuro todos los pares
están entre 6,7 y 15,3.

### Texto grande y alto contraste (9-oct)

Dos interruptores en la cabecera y en el login. Cada uno es una clase en `<html>` (`texto-grande`, `alto-contraste`;
reglas al final de `frontend/styles.css`) y se recuerda en `localStorage` con `js/dispositivos/preferencias.js`
(`js/ui/aspecto.js`). Para que no parpadee, `frontend/js/aspecto_previo.js` aplica las clases antes de pintar: es un
script clásico cargado en `<head>` porque la CSP no admite código en línea. Sin elección guardada, `prefers-contrast: more`
del sistema activa el alto contraste.

- **Texto grande**: la raíz pasa al 120 % (casi todo va en `rem`); se ajusta a mano lo que tiene ancho fijo (panel de
  cuenta, móvil simulado, tarjeta bancaria, campo del código) y la letra de los gráficos.
- **Alto contraste**: la misma paleta de Unicaja, con textos más oscuros, bordes visibles, sin sombras ni transparencias
  en la cabecera y enlaces subrayados. Ratios WCAG:

| Elemento | Claro (sobre blanco) | Oscuro (sobre `#12282f`) |
|---|---|---|
| Texto suave | `#2e3d43` · 10,6:1 | `#c9dadd` · 10,6:1 |
| Bordes | `#56676d` · 5,9:1 | `#8aa6ae` · 6,0:1 |
| Verde | `#1e6b00` · 6,7:1 | `#95e891` |
| Peligro | `#a81f26` · 6,2:1 (sobre su fondo) | `#ff8a8f` |
| Aviso | `#6b4400` · 7,9:1 | `#f2c24c` |

Los separadores y la rejilla de los gráficos (`--borde-suave`, `#7f8f95`) quedan en 3,4:1 a propósito: no son texto.

## Lo que NO está y hay que pedir a Unicaja

Los colores y la tipografía son los **publicados en su web**, no los de un manual de marca. Para una entrega final
conviene confirmarlos con la Cátedra. Faltan:

1. **El logotipo** (SVG): ya está en `frontend/assets/logo-unicaja.svg` (4-oct-2026), descargado de Wikimedia Commons
   (`commons/1/15/Logo_Unicaja.svg`, 166×48, petróleo `#005265` y verde `#2BD124`) y la interfaz lo muestra solo junto al
   nombre, en blanco sobre la cabecera. **No es el fichero oficial de la entidad**: confirmar con la Cátedra que se puede
   usar en el vídeo y la memoria, y sustituirlo por el que den si lo hay.
2. **El manual de identidad corporativa** (o confirmación de que se pueden usar estos tonos): sobre todo el verde
   exacto de la marca tras el rediseño de 2024 (`#278600` es el que domina en su web, pero la nueva identidad habla de
   «un verde más intenso»).
3. **Permiso de uso de marca** para el vídeo y la memoria, si la Cátedra lo exige.

## Cómo está construida la interfaz

- **Cabecera** petróleo con el sello, el nombre, el modelo en uso, el medidor de tokens, el interruptor de voz, el móvil
  simulado, los ajustes y el usuario.
- **Panel de cuenta** a la izquierda (saldo, IBAN enmascarado y últimos movimientos con un icono por categoría). Es el
  refuerzo visual permanente que pidieron en el directo; en pantallas pequeñas se reduce a la barra del saldo.
- **Conversación** con preguntas rápidas sobre el cuadro de texto, para empezar sin escribir.
- **Gráficos** con la paleta de Unicaja elija lo que elija el modelo (los datos no se tocan).
- **Acceso** a pantalla partida, con la marca a un lado y las cuentas de demostración.
- Iconos de trazo dibujados a mano (`ui/iconos.js`), sin emojis.
- Accesibilidad: foco visible, objetivos táctiles de 44 px, enlace «saltar al mensaje», regiones `aria-live`,
  `prefers-reduced-motion` y confirmación del Bizum con alternativas (ver DECISIONES nº 13).
