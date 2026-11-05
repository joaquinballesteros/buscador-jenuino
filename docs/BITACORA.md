# Bitácora

Registro de decisiones y cambios importantes, con su porqué. Lo más reciente,
arriba. El detalle técnico está en [ARCHITECTURE.md](ARCHITECTURE.md) y el uso
en el [README](../README.md).

---

## 2026-11-05 · Máquina virtual del SCI: `jenui.uma.es`

El SCI ha creado `jenui.uma.es` (Rocky Linux 9, solo IPv6, salida por proxy,
certificado SSL de GEANT/HARICA hasta mayo de 2027). Preparada para servir el
buscador, **sin git** (decisión del usuario: los ficheros de datos son grandes):

- Copia con `scripts/desplegar.sh` (nuevo): huellas SHA-256 a ambos lados y
  `tar` por SSH solo de lo cambiado; nunca envía ni pisa los juicios de
  `/evaluar`; `--traer-juicios` los trae. Primer envío: 97 ficheros, 349 MB, 28 s.
- Instalado: Python 3.12 + `.venv` con las dependencias, nginx con el
  certificado del SCI y página de mantenimiento, `jenui.service` (instalado,
  **sin habilitar**). Verificado desde fuera por IPv4: `http` → `https`,
  certificado válido.
- Corregido de paso: la clave privada del certificado era legible por todos
  (`644` → `600`).

**Bloqueos:**

1. **Memoria**: 1,6 GB, de los que el agente de seguridad corporativo
   (SentinelOne) ocupa ~520 MB. El buscador necesita ~1,5 GB más (bge-m3 +
   índice): hay que pedir al CAU subir a 4 GB.
2. ~~Ollama~~: lo instaló el usuario con el instalador oficial (el clasificador
   de permisos no dejó ejecutarlo de forma automática). Ollama 0.40.14, solo en
   `127.0.0.1:11434`, con el proxy del SCI en su servicio. `bge-m3` descargado
   con el **mismo digest** que el índice (`7907646426…`); un embedding de
   prueba coincide con el local hasta la quinta cifra decimal.

Cuando el SCI amplíe la memoria, arrancar es `systemctl enable --now jenui`.

Pendiente detectado: `static/temas.html` llama a `/api/topics`, que no existe
en la aplicación (llegó así con el commit `64d2002`).

---

## 2026-11-05 · Buscar sin salir al exterior

- **Embeddings de búsqueda en local** (`providers.embeddings.provider: ollama`,
  `bge-m3`): una consulta tarda 25-45 ms en CPU y la búsqueda completa
  0,08-0,15 s. Comprobado con el servidor GPU inaccesible a propósito: busca
  igual. Nada sale al exterior: el LLM solo interviene al construir el grafo.
- `providers.ollama.keep_alive: -1` mantiene bge-m3 cargado (antes Ollama lo
  descargaba a los 5 min y la primera búsqueda tardaba segundos).
- Para construir con la GPU: `JENUI_EMBED_PROVIDER=openai python scripts/...`
  (mismo modelo vía LiteLLM, vectores idénticos, índice compatible).
- Consecuencia: el buscador se puede desplegar en una máquina virtual del SCI
  sin acceso al servidor GPU (que tiene IP privada). Guía en
  [DEPLOY.md](DEPLOY.md#servidor-virtual-del-sci-universidad-de-málaga). La UMA
  da nombres `*.uma.es` y certificados SSL a través del CAU.

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

### Grafo completo (noche del 4 al 5)

- **Construcción**: 1920/1920 artículos en 389 min, sin fallos. 7.772 nodos,
  13.101 aristas; `other`/`unknown` 0,4 %. Todos los artículos tienen
  entidades (mediana 8). Ficheros versionados: 26 MB (el grafo anterior,
  ~250 MB).
- **Alias**: 228 fusiones semánticas; revisadas las menos seguras, solo una
  discutible (*Programación de Microprocesadores* → *de Microcontroladores*).
- **Análisis temporal**: ahora cubre **1920 artículos de 1997 a 2026** (antes
  812, de 2011 a 2026). Resolución de Louvain subida a 3.0: a 1.0 mezclaba la IA
  como asignatura (1997) con la IA generativa (2023). Resultado: 38 topics;
  emergentes consolidados como IA generativa (2023), clase invertida (2016),
  gamificación y brecha de género (2014), integración continua y Scrum
  (2012); en declive, EEES (pico 2007) o wikis (2009).
- **Referencias**: regeneradas para todo el corpus (antes solo 2021-2025):
  18.453 referencias, 2.175 citas internas identificadas.
- **Candidatos para evaluar**: 343 (12 por consulta), de 6 configuraciones,
  incluidas `max_articulos_por_entidad` 30 y 90.

### Fallos encontrados y corregidos esta noche

| Fallo | Efecto | Arreglo |
|---|---|---|
| **El análisis temporal no era reproducible** | misma configuración y semilla daban 36, 38 o 40 topics: el grafo de coocurrencia se recorría en el orden de un `set`, que cambia en cada proceso | recorrido ordenado; comprobado con `PYTHONHASHSEED` 1, 2 y 3: salidas idénticas |
| Corrector ortográfico | "delegar" → "desplegar"; "univesitario" → "universitaria"; "evaluasion" → "evaluation" | vocabulario del cuerpo para dar palabras por buenas; gana el candidato más parecido sin tildes |
| Nombres de entidad mostrados | "Primero Curso", "Evaluación Continuada" en "Relacionado por" | gana la forma curada o la más usada, no la más larga |
| Instituciones como conceptos | dos artículos se relacionaban por ser de la misma universidad | `search.patrones_entidad_descartados` (121 nodos) |
| `max_articulos_por_entidad` = 12 | con 1920 artículos ignora *Brecha de Género* (27), *ChatGPT* (20), *Aprendizaje Basado en Problemas* (20) | **sin cambiar**: se decide con el banco (configuraciones 30 y 90 ya en el pool) |

Señal cualitativa antes de evaluar: para la consulta *ABP*, solo texto pone
primero un artículo que no trata de ABP; con grafo + `minmax` + límite 30, los
5 primeros son de ABP.

### Pendiente

1. **Pasar el enlace a los evaluadores**: `http://150.214.108.91/evaluar`
   (todo listo: 28 consultas, 343 candidatos). Después
   `python scripts/eval_metrics.py` y barridos, por ejemplo
   `--barrido max_articulos_por_entidad=12,30,90 peso_grafo=0.15,0.3,0.5 --fijo normalizacion=minmax`,
   para fijar los parámetros en `config.json`.
2. Fusionar la rama `ontologia-v1.2` en `main`.
3. Opcional: `OLLAMA_NUM_PARALLEL` en el servidor; revisar la configuración
   *tutor-socratico* de nginx; filtrar en el buscador conceptos genéricos
   frecuentes (*Ingeniería Informática*, *Evaluación*) como ya hace el análisis.
