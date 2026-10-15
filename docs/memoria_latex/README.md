# Memoria técnica en LaTeX

Versión LaTeX de `docs/MEMORIA.md` (memoria técnica de Unia para el reto «Habla con tu dinero»).
Compila con **pdflatex**; no necesita paquetes exóticos (ni `minted` ni `fontspec`).

## Compilar en local

```bash
cd docs/memoria_latex
pdflatex main.tex
pdflatex main.tex     # segunda pasada: índice y referencias cruzadas
```

Sale `main.pdf`. Los ficheros auxiliares (`*.aux`, `*.log`, `*.toc`…) y el PDF están en `.gitignore`.

## Compilar en Overleaf

1. Comprime la carpeta `docs/memoria_latex/` en un `.zip`.
2. En Overleaf: *New Project → Upload Project* y sube el `.zip`.
3. En *Menu*, comprueba que el compilador es **pdfLaTeX** y que el documento principal es `main.tex`.

## Estructura

| Fichero | Contenido |
|---|---|
| `main.tex` | Raíz: clase, índice e `\input` de todo |
| `preambulo.tex` | Paquetes, estilos de tablas, listados, encabezado y pie |
| `colores.tex` | Colores de Unicaja (de `docs/MARCA.md`) |
| `portada.tex` | Portada (logos de la UGR y de Unicaja, título y autor) |
| `logos/` | `ugr.png` (de la web de la cátedra) y `unicaja.pdf` (del SVG de `frontend/assets`, convertido con cairosvg) |
| `capitulos/00_introduccion.tex` … `08_limitaciones.tex` | Un fichero por apartado de la memoria |
| `capitulos/09_anexo.tex` | Anexo «Cómo probarlo» |
| `figuras/arquitectura.tex` | Diagrama de arquitectura hexagonal (TikZ) |
| `figuras/secuencia_bizum.tex` | Diagrama de secuencia del Bizum con OTP (TikZ) |

## Al editar

- El contenido sale de `docs/MEMORIA.md`: si cambia la memoria en Markdown, actualiza aquí el capítulo correspondiente.
- Rutas e identificadores con guiones bajos: `\ruta{backend/dominio/reglas.py}` (sin escapar, corta la línea en `/ . _`;
  no admite espacios ni acentos). Para el resto de código en línea: `\cod{...}` escapando `_ % & # { }`.

- El PDF omite a propósito las referencias internas de `MEMORIA.md` (números de DECISIONES/INCIDENCIAS, rutas a otros docs, commit): un tribunal no las necesita.

- Las capturas `figuras/grafico_*.png` y `figuras/chat_grafico.png` se generan con `pruebas/capturar_graficos_memoria.py` contra una copia de la app en el 8006 (ver cabecera del script).
