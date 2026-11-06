# Revisión manual de los topics

Los topics los propone el algoritmo (Louvain sobre la coocurrencia de
conceptos) y aquí se corrigen a mano. El análisis lee estos dos ficheros y
**recalcula todo** sobre los topics revisados: artículos, series, clase, pico y
citas. No edites `data/analysis/topics.csv`: es una salida, se sobrescribe en
cada ejecución y no está en git.

Después de cada cambio:

```bash
python scripts/topic_evolution.py              # aplica la revisión
python scripts/topic_evolution.py --sin-revision   # para comparar con la detección automática
```

Al principio de la salida se resume la revisión (topics fusionados,
descartados, conceptos movidos…) y se avisa de las erratas.

## `conceptos.csv`: qué conceptos forman cada topic

Una fila por concepto. **La columna `topic` decide a qué topic pertenece.**

| Para… | Haz esto en la columna `topic` |
|---|---|
| mover un concepto a otro topic | cambia el identificador (`T01` → `T15`) |
| quitar un concepto que no pinta nada | déjala vacía o pon `-` |
| añadir un concepto suelto (las filas del final, sin topic) | escribe el topic |
| dividir un topic | pon un identificador nuevo (p. ej. `T39` o `ABANDONO`) en los conceptos que se separan |
| poner un concepto en dos topics | duplica la fila y pon un topic en cada una |

El orden de las filas no importa. La columna `articulos` (en cuántos artículos
aparece el concepto) es informativa.

**Ojo**: un artículo entra en un topic si tiene **al menos dos** de sus
conceptos (`min_conceptos_articulo`). Un topic con solo dos conceptos casi
sinónimos ("Abandono", "Tasa de abandono") se queda casi sin artículos; dale
varios conceptos.

## `topics.csv`: nombre, grupo, fusiones y descartes

Una fila por topic. Las columnas `etiqueta_automatica`, `articulos` y `clase`
son las de la detección automática, para orientarse; no hace falta tocarlas.

| Columna | Para qué |
|---|---|
| `nombre` | el nombre que tendrá en el informe y en el artículo (vacío: la etiqueta automática) |
| `grupo` | familia temática para ordenarlos en el artículo (p. ej. *Metodologías*, *Evaluación*, *Contenidos*, *Contexto institucional*) |
| `fusionar_en` | otro topic en el que se integra este (todos sus conceptos pasan allí) |
| `descartar` | `x` si no es un tema (p. ej. un cajón de sastre) |
| `notas` | libre: por qué se decidió algo (útil para el apartado de método) |

Un topic nuevo creado al dividir puede tener su fila aquí para darle nombre y
grupo.

## Cómo abordarlo

1. Abre `data/analysis/informe_topics.html` junto a estos ficheros: para cada
   topic muestra su serie, sus artículos centrales y sus pioneros, que ayudan a
   entender de qué trata.
2. Repasa `topics.csv` de arriba abajo: ponle **nombre** a cada topic y decide
   si se descarta o se fusiona.
3. Repasa en `conceptos.csv` los conceptos de cada topic y mueve o quita los
   intrusos (p. ej. "Sistemas Multiagente" en el de evaluación continua).
4. Ejecuta el análisis y revisa el resultado.

Los ficheros admiten coma, punto y coma o tabulador, así que se pueden editar
en VS Code, LibreOffice o Excel. Están en git: el historial de cambios queda
como registro de la revisión.

Si cambian los parámetros de detección o el grafo, la revisión sigue valiendo
(fija los conceptos de cada topic, no depende de la numeración). Los conceptos
nuevos que no aparezcan aquí se quedan fuera y el análisis avisa. Para empezar
de cero: mueve o borra los dos CSV y ejecuta
`python scripts/topic_evolution.py --plantilla-revision`.
