# Buscador JENUINO — GraphRAG local


Buscador semántico sobre los artículos de las **JENUI** (Jornadas sobre la Enseñanza Universitaria de la Informática). Escribes una consulta y devuelve una **lista de artículos relacionados**, cada uno con su **BibTeX** para citar, combinando:

- **Búsqueda vectorial de texto completo** (embeddings) — recall sobre todo el
  cuerpo del artículo.
- **Grafo de conocimiento** (LightRAG) sobre título + resumen + palabras clave —
  para encontrar artículos **relacionados por conceptos compartidos**.

### ¿Por qué dos sistemas separados?

Son de naturaleza muy distinta y esa asimetría es la razón de separarlos:

| | Búsqueda vectorial | Grafo de conocimiento |
|---|---|---|
| Motor | solo embeddings | LLM por cada fragmento |
| Coste de construir | minutos, gratis | horas en local (o unos euros por API) |
| Cubre | **texto completo** del artículo | título + resumen + palabras clave |
| Responde a | ¿qué tan parecido es este texto a tu consulta? | ¿qué artículos comparten los mismos conceptos docentes? |

Si fueran un solo proceso, indexar un artículo nuevo obligaría a pagar siempre
el camino caro (llamadas a un LLM) solo para poder buscarlo. Separados, el
artículo es **buscable en segundos** en cuanto pasa por el índice vectorial, y
el grafo lo enriquece después —construirlo lleva horas en local— añadiendo la
sección "🔗 Relacionado por" de cada resultado. Si el grafo aún no existe o está
a medio construir, la búsqueda simplemente sigue funcionando solo con vectores.

En cada consulta se combinan los dos: la similitud vectorial pone el grueso del
ranking y el grafo reordena o rescata artículos que comparten conceptos con los
mejores resultados, pero pesa poco **a propósito**, para no imponerse sobre lo
que realmente escribiste (ver [`peso_texto` / `peso_grafo`](#search--ranking)).

Por defecto corre **100% en local** con [Ollama](https://ollama.com) (sin enviar
datos a ninguna API). Los proveedores de LLM y de embeddings son **intercambiables** (ver ["Cambiar de LLM / embeddings"](#cambiar-de-llm--embeddings-patrón-estrategia)).

## Requisitos

- Python 3.11+ y [Ollama](https://ollama.com) instalado y arrancado.
- Modelos de Ollama (para el modo local por defecto):
  ```bash
  ollama pull bge-m3     # embeddings (obligatorio)
  ollama pull phi4:14b   # LLM para extraer el grafo
  ```

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

**Si acabas de clonar el repo, no hace falta construir nada.** El índice
vectorial y el grafo de los artículos ya existentes se versionan (`data/`,
`rag_storage/`), así que solo con instalar dependencias ya puedes buscar:

```bash
./scripts/run.sh           # arranca la web (usa el entorno virtual del proyecto)
```

Equivale a `python scripts/server.py` con el entorno activado. Si lo lanzas con el Python del sistema sin activar el entorno, obtendrás un mensaje indicándote cómo hacerlo (las dependencias viven en `.venv`, no en el Python global).

Para pararlo o recargar `config.json` (que se lee **al arrancar**, así que un cambio no surte efecto hasta reiniciar):

```bash
./scripts/stop.sh        # para el servidor y libera el puerto 8000
./scripts/restart.sh     # para y vuelve a arrancar -> recarga config.json
```

Abre <http://127.0.0.1:8000>, busca (p. ej. *"gamificación en programación"*) y obtienes la lista de artículos con resumen, palabras clave, **PDF** y **BibTeX** (botón «Copiar cita»).

> El enlace **PDF** de cada resultado no funcionará hasta que descargues los
> PDFs (`pdf/` no se versiona, ver [Datos de entrada](#datos-de-entrada)); el
> resto —búsqueda, resumen, palabras clave, grafo y BibTeX— funciona igual sin ellos.

### Cómo leer un resultado

Cada tarjeta muestra, de arriba abajo:

- **Porcentaje** (arriba a la derecha) — relevancia del artículo para tu consulta: `peso_texto · similitud de texto + peso_grafo · empuje del grafo`.
- **Título** — enlaza al PDF.
- **Autores · JENUI año · categoría** — metadatos, en gris.
- **Resumen** del artículo.
- **🔗 Relacionado por** *(texto violeta)* — **conceptos del grafo de conocimiento** que este artículo comparte con los mejores resultados de tu búsqueda. Explican *por qué* es relevante para **lo que buscaste**. Es  dinámico (cambia con cada consulta) y puede no aparecer: entonces el artículo
  entró solo por parecido de texto, no por conexión de conceptos.
- **Palabras clave** *(chips azules)* — las que pusieron los **autores** en el
  artículo. Describen de qué va el artículo **en sí**; son fijas, salga en la
  búsqueda que salga. No tienen relación con tu consulta.

En una frase: el **violeta** dice por qué el artículo encaja con tu búsqueda; el
**azul** dice de qué trata el artículo por sí mismo.

**Corrección ortográfica.** Si escribes con erratas (*"aprendisaje vasado"*), el
buscador corrige hacia palabras del propio corpus y avisa: *"Mostrando
resultados para **aprendizaje basado**…"*, con un enlace para buscar tu texto
tal cual. Usa el vocabulario de los artículos, así que **no** altera términos
técnicos (`scrum`, `abp`, `tfg`). Se desactiva con `search.corregir_ortografia`
en `config.json`.

---

## Datos de entrada

Solo hace falta lo de aquí abajo si quieres los **PDFs** (para el enlace "ver
PDF" de cada resultado) o si vas a **construir el índice desde cero** —no para
buscar tras clonar el repo, que ya viene listo.

- `pdf/` — un PDF por artículo, nombrado `JENUI_<año>_<n>.pdf`.
- `fichas/` — un HTML por artículo (`JENUI_<año>_<n>.html`) con metadatos limpios
  y BibTeX. Se usan para corregir títulos/autores/acentos y para las citas.

Ninguna de las dos carpetas se versiona: son las actas de JENUI, con copyright
de JENUI/los autores. En su lugar se versiona [`fuentes/enlaces_jenui.csv`](fuentes/enlaces_jenui.csv)
(año, fichero, título, autores, categoría y las URLs oficiales en aenui.org de
cada PDF y ficha). Para descargarlas:

```bash
python scripts/download_sources.py            # descarga lo que falte en pdf/ y fichas/
python scripts/download_sources.py --limit 5  # prueba con solo 5 artículos
```

Incremental, igual que el resto del pipeline: si ya tienes algún artículo
descargado, lo salta.

## Construir el índice desde cero

Necesario solo si partes de un corpus nuevo o distinto (o si borraste `data/`
y `rag_storage/`): tras clonar el repo, el índice y el grafo de los artículos
ya existentes vienen construidos y este paso no hace falta.

```bash
# 1. PDFs + fichas -> data/corpus.jsonl (texto + metadatos + bibtex)   (segundos)
python scripts/ingest.py

# 2. Índice vectorial de texto completo                                (~3-4 min)
python scripts/build_fulltext.py

# 3. Grafo de conocimiento con LightRAG                                 (horas, en local)
#    Reanudable: puedes cortar con Ctrl-C y relanzarlo; salta lo ya hecho.
python scripts/build_graph.py
```

> **Tiempo del grafo:** con un LLM local la extracción de entidades es lenta, así que el grafo se construye sobre título+resumen+palabras clave (~254 llamadas). El texto completo (`--scope full`) es mucho más lento y rara vez compensa. La web **funciona en cuanto termina el paso 2**; el grafo solo añade la sección "Relacionado por conceptos". Para ver el progreso del paso 3 mientras corre: `python scripts/status.py --watch`.

---

## Añadir nuevos artículos / años

El sistema es **incremental**: solo procesa lo nuevo, sin rehacer todo.

1. **Añade las filas nuevas a [`fuentes/enlaces_jenui.csv`](fuentes/enlaces_jenui.csv)** (año,
   fichero, título, autores, categoría, URL del PDF y de la ficha en
   aenui.org) y descárgalas:
   ```bash
   python scripts/download_sources.py
   ```
   Sirve tanto para artículos sueltos como para un **año entero** (p. ej. todos
   los `JENUI_2026_*`). Si ya tienes los ficheros a mano (PDF/HTML), también
   puedes copiarlos directamente a `pdf/` y `fichas/` respetando el nombrado
   `JENUI_<año>_<n>` y saltarte este paso.

2. **Reprocesa solo lo nuevo:**
   ```bash
   python scripts/ingest.py            # añade al corpus solo los PDFs que faltan
   python scripts/build_fulltext.py    # embebe solo los artículos nuevos y los añade
   python scripts/build_graph.py       # LightRAG procesa solo los documentos nuevos
   ```
   Cada paso te dirá cuántos artículos hay ya y cuántos son nuevos. Si no hay
   nada nuevo, no hace nada.

3. **Refresca el buscador** (si el servidor está en marcha):
   ```bash
   curl -X POST http://127.0.0.1:8000/api/reload
   ```
   El servidor también detecta los cambios solo (recarga por fecha de fichero),
   así que basta con esperar unos segundos o reiniciarlo.

**Rehacer todo desde cero** (p. ej. tras corregir la extracción o cambiar de
LLM): la cadena completa, en orden:

```bash
python scripts/ingest.py --rebuild          # corpus (aplica el recorte de bibliografía)
python scripts/build_fulltext.py --rebuild  # índice vectorial            (~13 min)
rm -rf rag_storage/                         # descarta el grafo anterior
python scripts/build_graph.py               # grafo de conocimiento       (coste del LLM)
python scripts/merge_aliases.py             # consolida entidades         (local)
python scripts/build_concepts.py            # índice de conceptos         (local)
```

> **Pendiente para la máquina nueva.** El recorte de bibliografía
> (`ingestion.quitar_bibliografia`) ya está activo pero solo surte efecto al
> reconstruir. Se aplicará solo con la cadena de arriba. En una máquina con GPU
> grande conviene además volver al LLM local (`config.json` →
> `providers.llm.provider: "ollama"`, un modelo de 14B+), con lo que el grafo
> sale gratis y con nombres de entidad más consistentes.

---

## Configuración: `config.json`

**Todos los ajustes están en [config.json](config.json)**, en la raíz. No hace
falta tocar código para cambiar modelos, la ontología del grafo, los pesos del
ranking o el troceado.

Prioridad: **variable de entorno > `config.json` > valor por defecto**. Usa el
JSON para la configuración estable del proyecto y las variables de entorno para
pruebas puntuales.

> **¿Por qué un solo fichero y no uno por herramienta?** Porque los valores están
> acoplados entre etapas: el modelo de embeddings lo usan `scripts/build_fulltext.py`,
> `scripts/build_graph.py` y el propio buscador a la vez (si se desincronizan, el
> índice deja de ser coherente), y los `entity_types` que produce el grafo son
> justo lo que filtra el buscador. Un único fichero con secciones evita que esos
> valores compartidos diverjan.

### `providers` — modelos

| Clave | Valores | Por defecto |
|---|---|---|
| `llm.provider` | `ollama`, `openai`, `anthropic` | `ollama` |
| `llm.model` | modelo concreto | `phi4:14b` |
| `embeddings.provider` | `ollama`, `openai` | `ollama` |
| `embeddings.model` | modelo concreto | `bge-m3` |
| `embeddings.dim` | fuerza la dimensión (`null` = la del modelo) | `null` |
| `ollama.host` | URL de Ollama | `http://localhost:11434` |
| `ollama.num_ctx` | contexto del LLM local | `16384` |

Dimensiones conocidas: `bge-m3` 1024, `nomic-embed-text` 768,
`text-embedding-3-small` 1536, `text-embedding-3-large` 3072. Si usas otro
modelo, indícalo en `embeddings.dim`.

### `graph` — construcción del grafo (LightRAG)

| Clave | Qué hace | Por defecto |
|---|---|---|
| `scope` | `meta` (título+resumen+keywords) o `full` (texto completo) | `full` |
| `entity_types` | **ontología del dominio: qué debe extraer el LLM** | ver abajo |
| `chunk_token_size` | tamaño de chunk; mayor = menos llamadas al LLM = más rápido | `1800` |
| `chunk_overlap_token_size` | solape entre chunks | `100` |
| `entity_extract_max_gleaning` | pasadas extra para captar entidades omitidas (`0` ≈ mitad de tiempo) | `1` |
| `llm_max_async` | peticiones paralelas al LLM | `2` |
| `language` | idioma de la extracción | `Spanish` |

**`entity_types` es el ajuste de mayor impacto.** La ontología por defecto de
LightRAG (`Person`, `Organization`, `Location`, …) hacía que el **49 % de las
entidades fuesen autores, departamentos y universidades**: metadatos que no
relacionan artículos por tema (medido: de 549 entidades, el 94 % aparecía en un
solo artículo, o sea que no conectaban nada). La ontología actual pide solo
conceptos docentes:

```json
"entity_types": [
  "metodologia_docente",     // ABP, aula invertida, gamificación
  "herramienta",             // Moodle, GitHub Classroom, SonarQube
  "tecnologia",              // Python, SQL, Docker
  "asignatura",              // Bases de Datos, Ingeniería del Software
  "competencia",             // trabajo en equipo, pensamiento crítico
  "instrumento_evaluacion",  // rúbrica, encuesta, portafolio
  "concepto_educativo"       // motivación, abandono, evaluación continua
]
```

Adáptala a tu corpus: si indexas otro dominio, cambia estos tipos y reconstruye
el grafo (borra `rag_storage/`).

### `search` — ranking

| Clave | Qué hace | Por defecto |
|---|---|---|
| `top_k` | resultados devueltos | `15` |
| `pooling` | agregación de fragmentos: `max` / `mean_topk` / `hybrid` | `hybrid` |
| `pooling_k` | nº de mejores fragmentos para la media | `5` |
| `pooling_alpha` | peso del máximo en el híbrido: `α·max + (1−α)·media` | `0.5` |
| `peso_texto` | peso de la similitud vectorial | `0.85` |
| `peso_grafo` | peso del empuje por conceptos compartidos | `0.3` |
| `n_semillas` | cuántos resultados top siembran la expansión por grafo | `3` |
| `umbral_semilla` | similitud mínima para que un artículo sea semilla (evita que uno genérico arrastre conceptos ajenos) | `0.5` |
| `umbral_concepto` | suelo absoluto de afinidad concepto↔consulta (espacio centrado) | `0.2` |
| `factor_relativo` | corte adaptativo por consulta: `media + factor·desviación` | `0.5` |
| `max_conceptos_semilla` | tope de conceptos de las semillas que se usan (los más afines) | `20` |
| `max_articulos_por_entidad` | una entidad en más de N artículos se considera genérica y se ignora | `12` |
| `corregir_ortografia` | corrige erratas de la consulta con el vocabulario del corpus | `true` |
| `tipos_entidad_descartados` | **red de seguridad**: tipos que se filtran al leer el grafo | lista de 28 |

**Pooling** (`pooling*`): cómo se resume un artículo troceado en un solo score.
`max` toma el mejor fragmento (máximo recall, pero un artículo que menciona el
tema de refilón empata con uno que lo trata a fondo); `hybrid` combina el máximo
con la media de los `k` mejores, premiando la cobertura. Ver la página `/testing`
para ver las similitudes por fragmento de cada artículo.

**Filtrado de conceptos** (`umbral_concepto`, `factor_relativo`,
`max_conceptos_semilla`): al expandir por grafo, los conceptos de las semillas se
filtran por su afinidad con la consulta en **tres pasos encadenados**:

1. **suelo absoluto** (`umbral_concepto`) — descarta lo claramente irrelevante y
   frena consultas sin señal;
2. **corte relativo** (`media + factor·desviación`) — se adapta a cada consulta;
3. **tope** (`max_conceptos_semilla`) — se queda con los N más afines.

> Las afinidades son coseno en **espacio centrado** (se resta la media para
> separar mejor), así que están comprimidas: una coincidencia casi perfecta ronda
> 0.4–0.55, no 0.9. Por eso el suelo es 0.2 y no un valor alto: subirlo a 0.4
> tiraría hasta el concepto central de una consulta corta (para "ABP" caería el
> propio `Aprendizaje Basado en Proyectos`). El **tope** es lo que de verdad
> protege ante consultas débiles —como un acrónimo— sin depender de un número
> absoluto. Requiere el índice de conceptos (`scripts/build_concepts.py`); sin él, no filtra.

`tipos_entidad_descartados` protege por si el LLM ignora la ontología pedida
(pasa con modelos pequeños): al cargar el grafo se descarta todo nodo cuyo
`entity_type` esté en la lista (`person`, `organization`, `location`, `unknown`…).
La comparación **normaliza** el tipo (minúsculas, sin acentos ni guiones), así que
`Organización`, `organizacion` y `ORGANIZATION` se filtran igual.

### `fulltext` — índice vectorial

| Clave | Qué hace | Por defecto |
|---|---|---|
| `chunk_chars` | tamaño del fragmento en caracteres | `1200` |
| `overlap_chars` | solape entre fragmentos | `150` |
| `batch_size` | textos por lote enviados al modelo de embeddings | `16` |

### Cambiar de proveedor (patrón estrategia)

Edita `config.json` o exporta variables (`JENUI_LLM_PROVIDER`,
`JENUI_EMBED_PROVIDER`, `JENUI_LLM_MODEL`, `JENUI_EMBED_MODEL`, `OLLAMA_HOST`).
Las claves de API se leen **solo** del entorno: `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY` (nunca las pongas en `config.json`, que se versiona).

Ejemplos:

```bash
# LLM potente por API (Anthropic) + embeddings locales gratis
export ANTHROPIC_API_KEY=sk-ant-...
export JENUI_LLM_PROVIDER=anthropic          # usa claude-sonnet-5 por defecto
python scripts/build_graph.py

# Todo OpenAI (embeddings de más calidad para la búsqueda)
export OPENAI_API_KEY=sk-...
export JENUI_LLM_PROVIDER=openai             # gpt-4o-mini
export JENUI_EMBED_PROVIDER=openai           # text-embedding-3-small (dim 1536)
python scripts/build_fulltext.py --rebuild   # re-embebe con el nuevo modelo
python scripts/build_graph.py
```

> **Importante:** el modelo de **embeddings** define la dimensión de los vectores.
> Si cambias de embeddings, hay que **reconstruir** el índice full-text y el grafo
> (`--rebuild` / borrar `rag_storage/`). El sistema guarda en
> `data/index_manifest.json` con qué proveedor se construyó y **aborta con un aviso
> claro** si intentas mezclar embeddings incompatibles. Cambiar solo el **LLM** no
> obliga a re-embeber, pero sí a rehacer el grafo si quieres reextraer entidades.
>
> Añadir un proveedor nuevo (p. ej. Azure, Cohere) = crear una subclase en
> [jenui/providers/](jenui/providers/); no cambia nada más.

---

## Estructura

```
config.json          TODOS los ajustes (modelos, ontología, ranking, troceado)
.env                 solo claves de API (no se versiona)

fuentes/
└── enlaces_jenui.csv  año/fichero/título/autores + URLs oficiales (aenui.org) de cada PDF y ficha

scripts/             puntos de entrada (uno por comando)
├── download_sources.py PDFs + fichas oficiales (aenui.org) -> pdf/ y fichas/
├── ingest.py          PDFs + fichas -> data/corpus.jsonl
├── build_fulltext.py  corpus -> índice vectorial
├── build_graph.py     corpus -> grafo de conocimiento
├── build_concepts.py  índice de vectores de concepto (filtro de relevancia)
├── merge_aliases.py   consolida entidades equivalentes del grafo
├── status.py          progreso del grafo, índice vectorial y corpus
├── server.py          arranca la web
├── run.sh             arranca server.py con el entorno virtual
├── stop.sh            para el servidor
└── restart.sh         para y vuelve a arrancar (recarga config.json)

jenui/               el sistema (un fichero por clase pública)
├── config/          Settings, Paths
├── domain/          Article, SearchResult
├── providers/       estrategias de LLM y embeddings
├── ingestion/       PDFs y fichas -> corpus
├── indexing/        corpus -> índice vectorial y grafo
├── graph/           lectura y consolidación del grafo
├── search/          Searcher, Ranker
└── web/             API HTTP e interfaz

static/index.html    interfaz web
docs/ARCHITECTURE.md diseño del sistema y puntos de extensión
```

Los scripts de `scripts/` son puntos de entrada finos: toda la lógica vive en el
paquete `jenui`. Ver **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** para el
diseño por capas, los invariantes del sistema y cómo extenderlo.

## Consolidar entidades equivalentes

LightRAG fusiona entidades por nombre **exacto**, así que un mismo concepto se
parte (`Investigación-acción` / `Investigación-Acción` / `ABP`) y deja de
conectar artículos. El buscador une las variantes tipográficas por su cuenta;
para las semánticas:

```bash
python scripts/merge_aliases.py --dry-run    # revisa qué fusionaría
python scripts/merge_aliases.py              # aplica
```

Es local y sin LLM: solo cuesta tiempo de embeddings. Conviene ejecutarlo tras
construir el grafo, y de nuevo si añades artículos con **otro** modelo.

## API

- `GET /api/search?q=<consulta>&k=15` → lista de artículos (incluye `bibtex`).
- `GET /api/explain?q=<consulta>` → búsqueda **instrumentada**: las etapas
  intermedias (recuperador vectorial con similitudes por fragmento, grafo y
  ranker). La consume la página de testing.
- `GET /api/status` → estado del índice (nº artículos, full-text, grafo, embeddings).
- `POST /api/reload` → recarga corpus, vectores y grafo sin reiniciar.
- `GET /pdf/<fichero>` → sirve el PDF original.

## Página de testing

<http://127.0.0.1:8000/testing> — misma búsqueda, pero mostrando **cómo se
construye el resultado** paso a paso:

1. **Recuperador vectorial** — similitud de cada artículo, con las mejores
   similitudes por fragmento y el *pooling* aplicado, de mejor a peor.
2. **Grafo de conocimiento** — semillas elegidas, conceptos de las semillas con
   su afinidad a la consulta (cuáles se usan y cuáles se descartan y por qué), y
   los artículos relacionados que aportan.
3. **Ranker** — el desglose `peso_texto·texto + peso_grafo·grafo` de cada
   resultado final.

Útil para entender el ranking y para calibrar los parámetros de `config.json`.
