# Bitácora

Registro de decisiones y cambios importantes, con su porqué. Lo más reciente,
arriba. El detalle técnico está en [ARCHITECTURE.md](ARCHITECTURE.md) y el uso
en el [README](../README.md).

---

## 2026-11-04 · Ontología v1.2, grafo único, reparación de textos y banco de evaluación

Rama: `ontologia-v1.2` (sin fusionar en `main`).

### Punto de partida

- `topic_evolution.py` fallaba al arrancar: el commit `64d2002` ("corpus
  completed") resolvió mal un merge, borró `Paths.with_rag_dir` y las opciones
  `--rag-dir` / `--sin-metadatos`, y versionó tres `.orig` con marcadores de
  conflicto.
- El grafo del buscador (`rag_storage/graph_chunk_entity_relation.graphml`, de
  julio) solo cubría **181 artículos de 2021-2024**, aunque los `kv_store_*`
  eran del corpus completo. El buscador, por tanto, favorecía esos años.
- Los 203 artículos de 1995-1999 no tenían año (el patrón solo aceptaba 20xx).

### Decisiones

| Decisión | Por qué |
|---|---|
| LLM y embeddings en el servidor con GPU vía LiteLLM (`qwen3.8:27b-q4_K_M`, `bge-m3`) | En la CPU local bge-m3 iba a ~3 fragmentos/s; en el servidor, ~100-130/s. Mismo modelo (digest `7907646426…`), vectores idénticos (coseno 1,0000). |
| `{"think": false}` en cada petición | Qwen3 razonaba en cada llamada. |
| Ontología rediseñada (v1.2) con método híbrido | La anterior tenía un 27 % de entidades en un cajón de sastre (`concepto_educativo`) y LightRAG solo pasaba al LLM los nombres de los tipos. |
| Un solo grafo para buscador y análisis (`scope: meta`, `--sin-metadatos`) | El grafo sirve a los dos usos; validado contra ambos en el piloto; ahorra una construcción de ~6 h. |
| Pesos del ranking elegidos con juicios de relevancia de varias personas (mediana) | Medido: con `peso_grafo` 0,3 el grafo decidía el orden con 5-10 veces más fuerza que el texto, porque la similitud de los buenos resultados varía en centésimas. |
| `/evaluar` abierta, sin contraseña; el evaluador declara su nombre | Decisión del usuario: el enlace solo se pasa a ciertas personas. |

### Ontología v1.2

Ocho tipos: `metodologia_docente`, `contenido_disciplinar`, `evaluacion`,
`herramienta_docente`, `alumnado`, `contexto_institucional`,
`modalidad_docente`, `competencia`. Derivados de 8 preguntas de competencia
(metodologías por época; metodología × contenido; evaluación; herramientas;
problemas del alumnado; contexto institucional y externo; competencias;
experiencia frente a investigación, esta última fuera del grafo por ser
propiedad del artículo).

Validación:

| Prueba | Resultado |
|---|---|
| Term typing de 428 palabras clave de autores | 0,6 % sin tipo |
| Extracción abierta de 84 artículos por décadas | ≤1,1 % sin tipo en cada época |
| Piloto A/B, 72 artículos nuevos (anterior → v1.2) | metadatos 12,0 % → 0,2 %; vecinos medianos 4 → 8; útiles compartidas 7,0 % → 8,1 %; sin copias de los ejemplos |

Además: definiciones, criterios y dos ejemplos de JENUI en el prompt
(`prompts/ejemplos_extraccion.txt`) y una tabla de alias manuales
(`graph.alias_canonicos`: EEES, TFG, IA, *flipped classroom*, COVID…).

### Datos

- **Corpus: 1920 artículos** (antes 1924): se excluyen el tríptico de 1995 y
  tres páginas de comités (`ingestion.excluir`); dos talleres cuyo PDF oficial
  es la página de comités quedan solo con metadatos (`ingestion.solo_metadatos`).
- **Textos ilegibles reparados**: 198 resúmenes y 5 cuerpos (cifrado de 29
  posiciones, letras duplicadas o sustituidas). Quedan 2 irrecuperables:
  `JENUI_2011_032`, `JENUI_2012_002`.
- **Años 1995-1999** rellenados (203 artículos).
- **Índice vectorial** actualizado: 197 artículos re-embebidos.
- **Grafo antiguo y de prueba** apartados (no borrados) en
  `../backup_grafos_20261104/`; incluye la caché de respuestas del LLM antiguo
  (557 MB), que no está en git.

### Código

| Tema | Ficheros |
|---|---|
| Restaurar lo perdido en el merge | `config/paths.py`, `scripts/build_graph.py`, `status.py`, `merge_aliases.py` |
| Proveedor `openai` con `extra_body` | `providers/openai_llm_provider.py` |
| Ontología en el prompt; alias manuales | `indexing/graph_builder.py`, `graph/alias_resolver.py` |
| Reparación de textos | `ingestion/text_quality.py`, `corpus_builder.py`, `ingest.py --reparar` |
| Índice: re-embeber lo que cambia | `indexing/vector_index*.py` |
| Normalización del ranking (`ninguna`/`minmax`/`rrf`) | `search/ranker.py`, `/testing` |
| Corrector ortográfico | `search/spell_corrector.py` ("delegar" ya no se cambia a "desplegar") |
| Evaluación | `evaluation/`, `scripts/eval_pool.py`, `eval_metrics.py`, `/evaluar` |
| `stop.sh` | solo para el servidor de este proyecto |

### Incidentes

- **`stop.sh` mataba procesos ajenos.** Buscaba `server.py` en cualquier línea
  de comandos: paró el servidor Python de la extensión de VS Code (se relanzó
  solo) y la propia shell. Corregido y probado. En esta máquina no hay `lsof`,
  así que la parada por puerto nunca funcionaba.
- **El buscador está publicado en `http://150.214.108.91/`** por el `nginx.conf`
  activo (HTTP, sin contraseña), y ahora también `/evaluar`. La configuración
  `sites-enabled/tutor-socratico` no se carga (el `nginx.conf` no la incluye),
  le falta un `;` tras `server_name` y su certificado no existe. No se ha tocado.
- **Paralelismo del servidor de LLM**: atiende las peticiones de una en una
  (~75 tokens/s con 1, 2, 4 u 8 simultáneas). `OLLAMA_NUM_PARALLEL=4` en el
  servidor podría multiplicar el rendimiento del grafo.

### Pendiente

1. Que los evaluadores juzguen en `http://150.214.108.91/evaluar` y luego
   `python scripts/eval_metrics.py` (y barridos) para fijar `peso_grafo`,
   `normalizacion` y `max_articulos_por_entidad` (este último se calibró con 254
   artículos; ahora hay 1920).
2. Fusionar la rama `ontologia-v1.2` en `main`.
3. Opcional: `OLLAMA_NUM_PARALLEL` en el servidor; revisar la configuración
   *tutor-socratico* de nginx.
