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

**Textos ilegibles.** Algunos PDFs (sobre todo 2000-2009) tienen fuentes mal
codificadas y su texto, y el resumen de su ficha, salen cifrados (desplazados 29
posiciones), con letras duplicadas, sustituidas o perdidas. `TextQuality` mide
la legibilidad como la fracción de palabras del **vocabulario del propio
corpus** (las que aparecen en ≥8 artículos; la distribución es bimodal: limpio
>0,85, roto <0,75), invierte el cifrado línea a línea, deshace la sustitución
aprendiendo la tabla del título limpio de la ficha y, si nada basta, toma el
resumen del cuerpo. Necesita el vocabulario de todo el corpus, así que
`CorpusBuilder` lo aplica **al final** de la ingesta, no por artículo;
`ingest.py --reparar` lo aplica a un corpus ya construido. Sobre el corpus de
2026 repuso 198 resúmenes y 5 cuerpos; quedan 2 irrecuperables.

Dos listas explícitas en `config.json` → `ingestion`: `excluir` (entradas del
listado oficial que no son artículos: tríptico de 1995, páginas de comités) y
`solo_metadatos` (artículos cuyo PDF oficial es otro documento).

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

**El índice vectorial también refresca lo que cambia.** `VectorIndexBuilder`
vuelve a trocear cada artículo (sin embeddings) y compara sus fragmentos con
los guardados: si difieren —un resumen reparado, por ejemplo— re-embebe solo
ese artículo; y quita los que ya no están en el corpus.

**Un solo grafo** (`graph.scope: meta`, construido con `--sin-metadatos`) sirve
al buscador y al análisis temporal: título + resumen + palabras clave, una
llamada al LLM por artículo, sin autores ni año en el texto.

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
   ├─ KnowledgeGraph.related_articles ── expande desde las semillas (a menos de
   │     margen_semilla del mejor) y desde los conceptos más afines a la consulta
   │     └─ filtra los conceptos de las semillas por afinidad con la consulta:
   │        suelo absoluto → corte relativo (media+factor·desv) → tope top-N
   ├─ Ranker  →  s = similitud + bonus · min(1, empuje del grafo / referencia)
   │     (en unidades reales de similitud: sin reescalar por consulta)
   ├─ SurpriseTruncator  →  la lista se corta donde la sorpresa −log p frente a la
   │     cola de los no relevantes (Pareto generalizada) baja del umbral
   └─ aviso de similitud baja  →  si ni el mejor resultado llega a umbral_aviso_similitud
```

**Dos entradas al grafo.** La expansión parte de los conceptos de las
semillas, así que si el texto no encuentra buenas semillas el grafo no puede
ayudar (para "carga cognitiva" las semillas trataban de otra cosa y el concepto
*Carga Cognitiva* nunca entraba). Por eso `KnowledgeGraph.query_entities` añade
una segunda entrada: los conceptos del grafo más afines a la propia consulta,
comparados en el espacio centrado del índice de conceptos. Tanto las semillas
como estos conceptos se eligen con **umbral relativo** (a menos de un margen del
mejor) más un suelo absoluto y un tope, porque las similitudes de este corpus
están comprimidas y un umbral fijo o deja pasar ruido o pierde lo bueno según
la consulta.

**Corte por teoría de valores extremos.** `jenui/search/truncation.py`
implementa *Surprise* (Bahri et al., SIGIR 2023): se ajusta una distribución
de Pareto generalizada a la cola de las puntuaciones no relevantes de los 200
primeros (máxima verosimilitud, forma ≥ 0; selección voraz del umbral de
excesos con Cramér-von Mises) y cada resultado recibe una sorpresa −log p.
Se eligió tras revisar la literatura de truncado (mezclas por EM, inestables
en estos datos; métodos supervisados, sin datos para entrenarlos; umbral
global, que falla con siglas). El reescalado mín-máx anterior se abandonó
porque asigna siempre el máximo al mejor artículo: pierde la similitud
absoluta, que distingue las consultas sin artículos pertinentes (las del banco
superan 0,534; consultas ajenas a JENUI no pasan de 0,487).

**Aviso de similitud baja.** La sorpresa es relativa a cada consulta: en una
consulta ajena a JENUI ("bocadillos de chorizo") siempre hay algún artículo que
destaca un poco sobre los demás. La similitud absoluta del mejor resultado sí
lo distingue —es el predictor de calidad de consulta más simple, basado en la
puntuación máxima—, así que si queda por debajo de `umbral_aviso_similitud`
(0,52: banco ≥ 0,534, consultas ajenas ≤ 0,503) la respuesta lleva un `aviso`.
No se ocultan los resultados: el margen es estrecho y una coincidencia parcial
puede ser útil.

**Normalización (modos minmax y rrf).** La similitud de los buenos resultados se concentra en unas
centésimas (0,66-0,70 en un top-15 típico) mientras que el empuje del grafo va
de 0 a 1: sin normalizar, con `peso_grafo` 0,3 el grafo decide el orden con 5-10
veces más fuerza que el texto. `minmax` reescala la similitud entre los
`candidatos_normalizacion` mejores; `rrf` combina posiciones. El valor por
defecto sigue siendo `ninguna` hasta elegir con el banco de evaluación (§10).

**Corrector ortográfico.** Dos vocabularios: los candidatos salen de títulos,
resúmenes y palabras clave, pero una palabra se da por válida si aparece en el
cuerpo de ≥3 artículos (si no, "delegar" se "corregía" a "desplegar"). Gana el
candidato más parecido, comparado sin tildes; la frecuencia solo desempata.

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

LightRAG solo pasa al LLM los **nombres** de los tipos y trae ejemplos few-shot
ajenos al dominio. `GraphBuilder.extraction_guidance` sustituye
`PROMPTS["entity_extraction_examples"]` por definiciones
(`graph.definiciones_tipos`), criterios (`graph.instrucciones_extraccion`) y
ejemplos de JENUI (`prompts/ejemplos_extraccion.txt`).

**Cómo se hizo la v1.2** (método híbrido: Noy & McGuinness / NeOn + inducción
desde datos, al estilo EDC):

1. *Preguntas de competencia* sobre la evolución temporal de JENUI (metodologías,
   contenidos, evaluación, herramientas, alumnado, contexto, competencias;
   la de "experiencia frente a investigación" es propiedad del artículo y queda
   fuera del grafo).
2. *Reutilización*: dimensiones de la clasificación de Simon y áreas de ACM
   CS2023 para el contenido disciplinar.
3. *Term typing* de las 428 palabras clave de autores con ≥2 artículos: solo el
   0,6 % no encajaba en ningún tipo; las ambigüedades decidieron fusiones
   (asignatura → contenido) y tipos nuevos (`modalidad_docente`).
4. *Extracción abierta* sin tipos sobre 84 artículos por décadas: ≤1,1 % sin
   tipo en todas las épocas.
5. *Piloto A/B* sobre 72 artículos nuevos: metadatos extraídos 12 % → 0,2 %;
   vecinos medianos por artículo 4 → 8; sin copias de los ejemplos del prompt.

Para repetir el proceso con otra ontología, el piloto es lo que decide: un
grafo pequeño por variante en carpetas aparte (`--rag-dir`) y comparar ruido,
conexión y fidelidad.

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

Se resuelve en tres capas:

| Capa | Dónde | Coste | Une |
|---|---|---|---|
| Textual | `AliasResolver`, siempre activa | gratis | mayúsculas, acentos, guiones |
| Manual | `graph.alias_canonicos` | gratis | siglas e inglés: `EEES` ↔ `Espacio Europeo de Educación Superior`, `Flipped Classroom` ↔ `Clase Invertida` |
| Semántica | `SemanticAliasBuilder`, opcional | embeddings | plurales y variantes: `Guías Docentes` ↔ `Guía Docente` |

La semántica genera `data/entity_aliases.json`, que `AliasResolver` aplica al
cargar después de la manual. `ABP` queda fuera de la manual a propósito: en
JENUI es tanto aprendizaje basado en proyectos como en problemas.

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
| `ingestion/text_quality.py` | `TextQuality` | detecta y repara texto ilegible |
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
| `search/truncation.py` | `SurpriseTruncator` | dónde cortar: teoría de valores extremos |
| `search/searcher.py` | `Searcher` | orquesta la búsqueda (y `explain` para /testing) |
| `web/app.py` | `create_app` | API HTTP e interfaz |
| `analysis/concept_source.py` | `ConceptCorpusBuilder` | conceptos por artículo (grafo y/o keywords) |
| `analysis/topic_detector.py` | `TopicDetector` | topics = comunidades de coocurrencia |
| `analysis/topic_evolution.py` | `TopicEvolution` | series, clases y conceptos emergentes |
| `analysis/topic_review.py` | `TopicReview` | revisión manual de los topics (`revision_topics/`) |
| `analysis/topic_flow.py` | `TopicFlowBuilder` | topics por ventanas y sus enlaces |
| `analysis/citation_links.py` | `CitationNetwork` | validación por citas internas |
| `analysis/topic_analysis.py` | `TopicAnalysis` | orquesta el análisis |
| `analysis/report_writer.py` | `ReportWriter` | CSV, JSON e informe HTML |
| `evaluation/judgment_store.py` | `JudgmentStore` | consultas, candidatos y juicios por evaluador |
| `evaluation/metrics.py` | — | nDCG, recall, judged@k, alfa de Krippendorff |

## 9. Análisis temporal de topics

`jenui/analysis/` es un consumidor más del grafo, **independiente del
buscador**: nada en `search/` ni en `web/` lo importa. Respeta los invariantes:
no llama al LLM (solo lee el GraphML) y degrada a palabras clave si no hay grafo.

```
corpus.jsonl ─┐
GraphML ──────┼─> ConceptCorpusBuilder ─> TopicDetector ─> TopicReview ─> TopicEvolution ─┐
alias ────────┘   (ruido, hubs)            (Louvain)     (revisión a mano) (series, clase) ├─> ReportWriter
                                          TopicFlowBuilder ───────────────────────────────┤   (CSV, JSON, HTML)
referencias_jenui.csv ─> CitationNetwork ─────────────────────────────────────────────────┘
```

**Grafo.** Por defecto lee el mismo grafo que el buscador (`analysis.grafo_dir:
rag_storage`), construido con `scope meta` y sin autores ni año
(`GraphBuilder.build(metadata=False)`). Se puede apuntar a otro almacén
(`Paths.with_rag_dir`, opción `--rag-dir` de los scripts); cada almacén
alternativo tiene su propio `entity_aliases.json`, así que fusionar alias en uno
no pisa el otro.

**Conceptos** (`ConceptCorpusBuilder`). Une entidades del grafo y palabras
clave por la clave de `AliasResolver`. `NoiseFilter` descarta por nombre lo
que `EntityTypeFilter` no puede descartar por tipo. Los conceptos en más de
`max_fraccion_concepto` de los artículos (*hubs*) conservan su serie pero no
entran en la detección de comunidades, donde conectarían todo con todo.

**Topics** (`TopicDetector`). Coocurrencia con peso de Salton y Louvain con
semilla fija (reproducible). Un artículo pertenece a un topic si tiene al
menos `min_conceptos_articulo` de sus conceptos.

**Revisión manual** (`TopicReview`). Louvain propone y el investigador
decide: `revision_topics/conceptos.csv` asigna cada concepto a un topic
(mover, quitar, añadir, dividir) y `revision_topics/topics.csv` pone nombre,
grupo, fusiones y descartes. Si existe, se aplica tras la detección y los
topics se reconstruyen con `TopicDetector.topics_from_groups` (mismo orden de
conceptos y misma regla de pertenencia), así que todo lo posterior se calcula
sobre ellos. Una revisión sin cambios reproduce exactamente la detección. La
revisión fija conceptos, no números de topic, y por eso sobrevive a cambios de
parámetros; `meta.revision` del JSON cuantifica la intervención manual
(conceptos movidos, topics fusionados…) para el apartado de método. Está fuera
de `data/` porque es una entrada y se versiona. Plantilla:
`--plantilla-revision`; detección sin revisar: `--sin-revision`.

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

## 10. Evaluación de la búsqueda

Los parámetros del ranking (`peso_grafo`, `normalizacion`,
`max_articulos_por_entidad`…) se eligen con juicios de relevancia, no a ojo.

```
evaluacion/consultas.csv ─> eval_pool.py ─> candidatos.json ─> /evaluar ─> juicios/<evaluador>.csv
   (28 consultas con          (unión del top-10 de     (orden         (0/1/2,        │
    criterio de relevancia)    varias configuraciones)  aleatorio)     a ciegas)      v
                                                                    eval_metrics.py ─> resultados.json
```

- **Consultas**: repartidas por los tipos de la ontología y por estilos (palabras
  clave, pregunta natural, sigla, inglés), cada una con su criterio de
  relevancia.
- **Pooling** (`scripts/eval_pool.py`): por consulta, la unión de los mejores
  resultados de cada configuración, barajada. Es acumulativo: lo nuevo se
  añade al final sin descolocar lo ya juzgado.
- **Juicios** (`/evaluar`): cada evaluador en su propio fichero y sin ver los de
  los demás. El nombre lo declara la página; detrás de un proxy con
  autenticación básica manda la cabecera `X-Remote-User`.
- **Referencia**: la mediana de los evaluadores (`JudgmentStore.consensus`).
- **Truncado** (`scripts/eval_truncado.py`): sobre un mismo ranking juzgado
  hasta 20, compara sorpresa, k fijo, umbral global y sorpresa + suelo por F1
  con validación cruzada dejando una consulta fuera, y mide la abstención en
  12 consultas ajenas (`evaluacion/consultas_ajenas.csv`), que no se juzgan.
- **Métricas** (`scripts/eval_metrics.py`): nDCG@10 con ganancia 2^g−1,
  recall@10 (mediana ≥1), **precisión de la lista completa** (la medida del
  ruido cuando la lista se corta por umbral) y judged@10 (fracción del top-10 con juicio: si baja,
  hay que ampliar el pool antes de comparar). Acuerdo con el alfa de
  Krippendorff ordinal, global y por consulta; una consulta con poco acuerdo
  suele tener un criterio ambiguo.
