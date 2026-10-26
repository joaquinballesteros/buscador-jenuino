# Arquitectura

Documento para quien vaya a **mantener o extender** el sistema. Para instalarlo
y usarlo, ver el [README](../README.md).

## 1. Qué resuelve

Dada una consulta en lenguaje natural, devolver una **lista de artículos de
congreso relacionados**, cada uno con su BibTeX.

Dos decisiones marcan el diseño:

1. **Ninguna búsqueda invoca al LLM.** El LLM solo interviene al construir el
   grafo. Una consulta se resuelve embebiendo el texto y haciendo un producto
   matricial: milisegundos y coste cero, aunque el grafo se haya construido con
   una API de pago.
2. **Construcción incremental.** Añadir artículos procesa solo los nuevos, en
   las tres etapas.

## 2. Capas

Las dependencias van en un solo sentido; ninguna capa conoce a las de arriba.

```
         ┌──────────────────────────────────────────┐
  web    │ create_app                               │  API HTTP + interfaz
         ├──────────────────────────────────────────┤
 search  │ Searcher · Ranker                        │  orquesta la consulta
         ├────────────────────┬─────────────────────┤
 graph   │ KnowledgeGraph     │ indexing            │  recuperadores
         │ GraphReader        │ VectorIndex         │
         │ AliasResolver      │ GraphBuilder        │
         ├────────────────────┴─────────────────────┤
ingestion│ CorpusBuilder · PdfExtractor · Ficha…    │  fuentes -> corpus
         ├──────────────────────────────────────────┤
providers│ EmbeddingProvider · LLMProvider (ABC)    │  estrategias
         ├──────────────────────────────────────────┤
 config  │ Settings · Paths                         │
         ├──────────────────────────────────────────┤
 domain  │ Article · SearchResult                   │  modelo puro
         └──────────────────────────────────────────┘
```

`domain` no importa nada del proyecto: se puede probar aislado y no arrastra
dependencias externas.

## 3. Los tres flujos

### 3.1 Ingesta — `scripts/ingest.py`

```
pdf/*.pdf ──> PdfExtractor ──┐
                             ├─> CorpusBuilder ─> CorpusRepository ─> corpus.jsonl
fichas/*.html ─> FichaParser ┘
```

Cada artículo se compone de dos fuentes, por fiabilidad:

| Fuente | Aporta | Fiabilidad |
|---|---|---|
| PDF | texto completo, metadatos aproximados | baja: acentos rotos, títulos desordenados |
| Ficha HTML | título, autores, resumen, BibTeX | alta: viene de base de datos |

`TextNormalizer` repara los artefactos de LaTeX (`evaluacio´n` → `evaluación`,
`ensen~anza` → `enseñanza`). Se aplica a **todo** el texto, porque el resumen de
las fichas recientes también los arrastra.

El corpus es JSON Lines para poder **añadir** sin reescribir.

### 3.2 Indexado — `scripts/build_fulltext.py` y `scripts/build_graph.py`

Dos índices independientes, con costes muy distintos:

| | Índice vectorial | Grafo de conocimiento |
|---|---|---|
| Motor | solo embeddings | LLM por cada fragmento |
| Coste | minutos, gratis | horas (o unos euros por API) |
| Cubre | **texto completo** | según `graph.scope` |
| Aporta | parecido con la consulta | conceptos compartidos entre artículos |

Están separados precisamente por esa asimetría: si fueran un solo proceso, añadir un artículo exigiría pagar el camino caro solo para hacerlo buscable. Así es buscable en segundos y el grafo lo enriquece después.

**Chunking con contexto.** `TextChunker` no embebe el fragmento del cuerpo tal
cual: le antepone `Article.chunk_context` (título + palabras clave) antes de
embeberlo, aunque lo que se **muestra** en pantalla siga siendo el fragmento
sin prefijo (`VectorIndexBuilder._prepare` separa ambos textos). Un fragmento
suelto del cuerpo ("los resultados muestran una mejora del 20%") no dice de
qué artículo viene; con el prefijo, el embedding sí lo sabe. Es una mejora casi
gratis: no añade llamadas al modelo de embeddings, solo alarga el texto de
entrada de cada una. El resumen no entra en el prefijo — ya está entero en
`dense_header`, que es el primer fragmento — para no gastar presupuesto de
caracteres repitiéndolo en cada fragmento del cuerpo.

### 3.3 Búsqueda — `Searcher`

```
consulta
   │
   ├─ SpellCorrector             ── corrige erratas con el vocabulario del corpus
   ├─ embed (1 llamada al modelo de embeddings)
   ├─ VectorIndex.score_articles     ── producto matricial sobre los fragmentos
   │     └─ pooling híbrido: alpha·mejor_fragmento + (1-alpha)·media_top-k
   │        (el máximo da recall; la media premia la cobertura del tema)
   ├─ KnowledgeGraph.related_articles ── expande desde las N mejores semillas
   │     └─ filtra los conceptos de las semillas por afinidad con la consulta:
   │        suelo absoluto → corte relativo (media+factor·desv) → tope top-N
   └─ Ranker  →  peso_texto · similitud + peso_grafo · conceptos compartidos
```

El grafo pesa poco a propósito: reordena y rescata artículos afines, pero no
manda sobre la consulta del usuario.

El filtrado de conceptos usa afinidad coseno en **espacio centrado** (se resta el
vector medio para contrarrestar la anisotropía). Está comprimida, así que el
suelo absoluto es bajo (0.2) y quien de verdad protege ante consultas débiles —un
acrónimo como "ABP"— es el **tope top-N**, que es relativo a cada consulta. La
página `/testing` (`Searcher.explain`) muestra estas etapas con sus valores.

**El peso del grafo por artículo se gradúa por relevancia.**
`KnowledgeGraph._expand` suma, por artículo, la relevancia a la consulta de
cada concepto conservado que posee, en vez de contar en plano los conceptos
compartidos: así compartir un concepto muy afín pesa más que uno marginal, y
el empuje del grafo queda continuo en vez de casi binario. Incluye a las
propias semillas, que acumulan peso por los conceptos afines que ellas mismas
aportan igual que cualquier otro artículo candidato — son, por construcción,
las que más conceptos relevantes concentran.

## 4. Puntos de extensión

### Añadir un proveedor de LLM o embeddings

Es el patrón **estrategia**: hereda de la interfaz y regístralo. Nada más cambia.

```python
class CohereEmbeddingProvider(EmbeddingProvider):
    name = "cohere"
    def embed(self, texts): ...
    def as_lightrag_func(self): ...

ProviderFactory.EMBEDDINGS["cohere"] = CohereEmbeddingProvider
```

### Cambiar la ontología del grafo

`config.json` → `graph.entity_types`. **Es el ajuste de mayor impacto sobre la
calidad.** Con la ontología genérica de LightRAG (`Person`, `Organization`,
`Location`), el 49 % de las entidades de este corpus eran autores y
universidades, y el 94 % aparecía en un solo artículo: no conectaban nada.
Cambiarla obliga a reconstruir el grafo.

### Ajustar el ranking

`config.json` → `search`, sin reconstruir nada: pesos texto/grafo, *pooling* de
fragmentos (`pooling*`), semillas (`n_semillas`, `umbral_semilla`) y filtrado de
conceptos (`umbral_concepto`, `factor_relativo`, `max_conceptos_semilla`).
Usa la página `/testing` para ver el efecto de cada cambio etapa por etapa.
Recuerda que `config.json` se lee al arrancar: `./scripts/restart.sh` para aplicarlo.

## 5. Invariantes que no conviene romper

1. **Los embeddings fijan la dimensión.** Mezclar dos modelos corrompe el
   índice. `IndexManifest` lo detecta y aborta. Cambiarlos exige `--rebuild`.
2. **El LLM sí se puede cambiar**, pero los nombres de entidad pueden variar de
   estilo y fragmentar el grafo: LightRAG fusiona por nombre **exacto**.
   `IndexManifest` avisa y `scripts/merge_aliases.py` lo corrige.
3. **La búsqueda nunca debe llamar al LLM.** Es lo que la mantiene instantánea
   y gratuita.
4. **El grafo es opcional.** Si falta o está a medio construir, la búsqueda
   funciona solo con vectores. `KnowledgeGraph` degrada en silencio.

## 6. Consolidación de entidades

LightRAG fusiona entidades solo por nombre exacto, así que el mismo concepto se
parte y deja de conectar artículos. Medido en una sola pasada de este corpus:
`Investigación-acción`, `Investigación-Acción` y `Formación en
Investigación-Acción` como tres nodos.

Se resuelve en dos capas:

| Capa | Dónde | Coste | Une |
|---|---|---|---|
| Textual | `AliasResolver`, siempre activa | gratis | mayúsculas, acentos, guiones |
| Semántica | `SemanticAliasBuilder`, opcional | embeddings locales | `ABP` ↔ `Aprendizaje basado en proyectos` |

La segunda genera `data/entity_aliases.json`, que la primera aplica al cargar.

## 7. Recarga en caliente

`Searcher` compara las fechas de modificación del corpus, del índice y del
GraphML, y recarga solo lo que cambió. Consecuencias prácticas:

- se pueden añadir artículos con el servidor levantado;
- la web va incorporando el grafo **mientras se construye**, sin reiniciar.

## 8. Mapa de ficheros

| Fichero | Clase pública | Responsabilidad |
|---|---|---|
| `config/paths.py` | `Paths` | rutas del proyecto |
| `config/settings.py` | `Settings` | `config.json` + `.env` + entorno |
| `domain/article.py` | `Article` | un artículo |
| `domain/search_result.py` | `SearchResult` | un resultado y su porqué |
| `providers/embedding_provider.py` | `EmbeddingProvider` | interfaz de embeddings |
| `providers/llm_provider.py` | `LLMProvider` | interfaz de LLM |
| `providers/provider_factory.py` | `ProviderFactory` | resuelve la estrategia |
| `ingestion/text_normalizer.py` | `TextNormalizer` | repara acentos y eñes |
| `ingestion/pdf_extractor.py` | `PdfExtractor` | PDF → texto y metadatos |
| `ingestion/ficha_parser.py` | `FichaParser` | ficha HTML → metadatos y BibTeX |
| `ingestion/bibtex_builder.py` | `BibtexBuilder` | BibTeX de reserva |
| `ingestion/corpus_repository.py` | `CorpusRepository` | persistencia JSONL |
| `ingestion/bibliography_stripper.py` | `BibliographyStripper` | recorta la bibliografía del cuerpo |
| `ingestion/corpus_builder.py` | `CorpusBuilder` | orquesta la ingesta |
| `indexing/text_chunker.py` | `TextChunker` | troceado con solape |
| `indexing/vector_index.py` | `VectorIndex` | vectores y consulta |
| `indexing/vector_index_builder.py` | `VectorIndexBuilder` | construcción incremental |
| `indexing/graph_builder.py` | `GraphBuilder` | grafo con LightRAG |
| `indexing/index_manifest.py` | `IndexManifest` | coherencia de proveedores |
| `graph/entity_type_filter.py` | `EntityTypeFilter` | descarta metadatos |
| `graph/graph_reader.py` | `GraphReader` | GraphML → entidad/artículos |
| `graph/alias_resolver.py` | `AliasResolver` | consolida variantes |
| `graph/semantic_alias_builder.py` | `SemanticAliasBuilder` | mapa de alias |
| `graph/concept_index.py` | `ConceptIndex` | vectores de concepto (centrado) para relevancia |
| `graph/concept_embedding_builder.py` | `ConceptEmbeddingBuilder` | genera los vectores nombre+descripción |
| `graph/knowledge_graph.py` | `KnowledgeGraph` | grafo consultable |
| `search/ranker.py` | `Ranker` | combina señales |
| `search/spell_corrector.py` | `SpellCorrector` | corrige erratas con vocabulario del corpus |
| `search/searcher.py` | `Searcher` | orquesta la búsqueda (y `explain` para /testing) |
| `web/app.py` | `create_app` | API HTTP e interfaz |
| `analysis/concept_source.py` | `ConceptCorpusBuilder` | conceptos por artículo (grafo y/o keywords) |
| `analysis/topic_detector.py` | `TopicDetector` | topics = comunidades de coocurrencia |
| `analysis/topic_evolution.py` | `TopicEvolution` | series, clases y conceptos emergentes |
| `analysis/topic_flow.py` | `TopicFlowBuilder` | topics por ventanas y sus enlaces |
| `analysis/citation_links.py` | `CitationNetwork` | validación por citas internas |
| `analysis/topic_analysis.py` | `TopicAnalysis` | orquesta el análisis |
| `analysis/report_writer.py` | `ReportWriter` | CSV, JSON e informe HTML |

## 9. Análisis temporal de topics

`jenui/analysis/` es un consumidor más del grafo, **independiente del
buscador**: nada en `search/` ni en `web/` lo importa. Respeta los invariantes:
no llama al LLM (solo lee el GraphML) y degrada a palabras clave si no hay grafo.

```
corpus.jsonl ─┐
GraphML ──────┼─> ConceptCorpusBuilder ─> TopicDetector ─> TopicEvolution ─┐
alias ────────┘   (ruido, hubs)            (Louvain)        (series, clase)  ├─> ReportWriter
                                          TopicFlowBuilder ─────────────────┤   (CSV, JSON, HTML)
referencias_jenui.csv ─> CitationNetwork ───────────────────────────────────┘
```

**Grafo propio.** Se construye en otro almacén (`Paths.with_rag_dir`, opción
`--rag-dir` de los scripts) con `scope meta` y sin autores ni año
(`GraphBuilder.build(metadata=False)`). Cada almacén tiene su propio
`entity_aliases.json`, así que fusionar alias en uno no pisa el otro.

**Conceptos** (`ConceptCorpusBuilder`). Une entidades del grafo y palabras
clave por la clave de `AliasResolver`. `NoiseFilter` descarta por nombre lo
que `EntityTypeFilter` no puede descartar por tipo. Los conceptos en más de
`max_fraccion_concepto` de los artículos (*hubs*) conservan su serie pero no
entran en la detección de comunidades, donde conectarían todo con todo.

**Topics** (`TopicDetector`). Coocurrencia con peso de Salton y Louvain con
semilla fija (reproducible). Un artículo pertenece a un topic si tiene al
menos `min_conceptos_articulo` de sus conceptos.

**Clasificación** (`TopicEvolution.classify`). Sobre la prevalencia
suavizada, con umbrales relativos al pico de cada topic:

| Clase | Criterio (claves de `analysis.clasificacion`) |
|---|---|
| emergente reciente | emerge hace menos de `anios_consolidacion` años |
| emergente consolidado | emerge, y desde entonces está en ≥ `cobertura_minima` de los años con nivel reciente ≥ `nivel_consolidado` del pico |
| pasajero | nivel reciente < `nivel_apagado` tras ≤ `duracion_max_pasajero` años activo |
| recurrente | ≥ `anios_min_recurrente` años con cobertura ≥ `cobertura_minima`, no apagado |
| en declive | apagado tras una vida larga |
| intermitente / esporádico | el resto / menos de `min_articulos_topic` artículos |

*Emerger* = el inicio (primer año con prevalencia ≥ `umbral_inicio` del pico)
llega al menos `anios_previos` años después del comienzo de los datos y antes
apenas había nada (< 10 % del pico). Lo presente desde el primer año no puede
ser emergente. La tendencia (creciente/estable/decreciente) es la pendiente
desde la primera aparición, como cambio por década relativo a la media (±30 %).

**Flujo** (`TopicFlowBuilder`). Topics por ventanas de `flujo.ventana` años,
alineadas con el último año; enlaces entre ventanas consecutivas con Jaccard ≥
`umbral_jaccard` medido **sobre el vocabulario común** a ambas ventanas (un
concepto que aún no existía no indica ruptura).

**Citas** (`CitationNetwork`). Por topic: citas internas, artículos más
citados y fracción de los posteriores a los tres primeros años que citan a
alguno de esos pioneros. Solo cuentan los artículos con referencias extraídas.
