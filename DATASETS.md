# DATASETS.md — Datos y límites

## 1. Datos que muestran el problema
| Dato | Fuente | Año |
|---|---|---|
| 2.6 mil millones de personas sin internet; uso de internet 27% en países de bajos ingresos | World Bank – Concept Note Small AI for Development, p.3 | 2024 |
| TODO: propiedad de smartphone mujeres/hombres en **nuestro país** | GSMA Mobile Gender Gap Report | TODO |
| TODO: llegadas/ingresos por turismo de **nuestro país** | UN Tourism / WDI | TODO |
| TODO: señal móvil en la zona | OpenCelliD | TODO |

(No inventar cifras: completar con el dato exacto, país y año.)

## 2. Datos con los que construimos
| Recurso | Tipo | Licencia / tamaño | Qué NO cubre |
|---|---|---|---|
| `data/places.json` | **Sintético**, escrito por el equipo (4 lugares) | Propio, < 2 KB | No son lugares reales; no hay verificación real de certificados |
| `data/intents.json` | Palabras clave y respuestas fijas escritas a mano: 7 intenciones + plantilla de seguimiento, en 12 idiomas (es/en/fr/pt/de/it/zh/ja/ko/ar/ru/hi). Funcionan sin internet; idiomas con otra escritura se detectan por sus letras | Propio, < 40 KB | Las traducciones de zh/ja/ko/ar/ru/hi/it las generó una IA y deben revisarlas hablantes nativos; sin jerga local ni lengua indígena (hay que añadirla con un hablante nativo); no usa aún MASSIVE; los datos de la finca (precio, horario) no se traducen; las traducciones de las plantillas no fueron revisadas por hablantes nativos |
| `data/phrases.json` | Frasario de la pestaña **Conversar**: 17 frases cortas (preguntas del visitante y respuestas de la persona a cargo) en 12 idiomas | Propio, < 20 KB | Traducciones generadas con IA, sin revisión de hablantes nativos; solo traduce sin internet si el texto coincide con una frase guardada. El micrófono del navegador (Chrome) necesita internet |
| `data/ui.json` | Textos del panel en otros idiomas. La **clave es el texto en español tal cual**, así que no hay identificadores que inventar: para añadir un idioma se copia el bloque y se traduce el lado derecho | Propio, 25 KB | Por ahora solo **español e inglés**. El inglés lo escribió una IA sin revisión de hablante nativo. Lo que **no** se traduce (ni debe): los mensajes de los visitantes, las reseñas, los nombres de lugares de OpenStreetMap y los datos que escribe la persona a cargo (precio, horario…). Si se cambia una frase del código sin tocar este archivo, esa frase deja de traducirse: hay una prueba que lo detecta |
| MyMemory (API de traducción) | Servicio externo, no es un dataset | Revisar términos y límite diario | Calidad baja en lenguas con pocos datos; requiere internet |
| Desglose de una traducción (botón **Detalle**) | Otras formas de decirlo que devuelve MyMemory, el significado de cada palabra por separado y cómo suena | Derivado de MyMemory + tablas propias | Se pide solo al abrirlo: desglosar gasta una consulta por palabra (máx. 8, y quedan en caché). **Palabra por palabra es fuera de contexto** y a veces no coincide con la frase entera ("dura" sale como *tough*, no *lasts*). Las alternativas se filtran por parecido, así que muchas frases no tienen ninguna |
| Cómo suena (romanización) | Tablas escritas a mano para ruso, griego, árabe, hebreo e hindi | Propio, < 2 KB | Es una aproximación para poder leerlo en voz alta, no un sistema oficial de transcripción. **No existe para chino, japonés ni coreano**: ahí cada signo es una sílaba o palabra y haría falta un diccionario. El árabe no escribe las vocales cortas, así que sale incompleto (مرحبا → *mrjba*) |
| Open-Meteo (API de clima) | Servicio externo | Revisar términos de uso | Pronóstico de 3 días; requiere internet (con caché) |
| OpenStreetMap vía Overpass | Lugares reales (nombre, tipo, coordenadas, horario si existe) descargados por radio y guardados en `data/osm_places.json` | ODbL (citar © colaboradores de OpenStreetMap) | No trae calificaciones, visitas ni confianza (se muestran como "Sin calificar"/NA); en zonas rurales el mapa suele estar incompleto; nombres sin traducir |
| Nominatim (OpenStreetMap) | Búsqueda de localidades y nombre de la ubicación actual | ODbL; uso moderado (máx. 1 consulta/seg) | Requiere internet; las coordenadas de la zona elegida se envían a Nominatim y Overpass |
| Reseñas de usuarios (se generan en la app, tabla `reviews`) | Texto + calificación 1-5 + alias, guardados en SQLite local | Propias de la app; sin datos personales (solo alias) | **No están verificadas** (no se comprueba que el autor visitó el lugar); solo opinan quienes deciden escribir (sesgo); filtro anti-spam básico (sin enlaces, límite de frecuencia); el análisis de temas usa un léxico pequeño es/en |
| `data/vision_labels.json` | Las 45 cosas que la pestaña **Mirar** sabe reconocer, en 5 grupos. Escritas a mano. Se le pregunta al modelo en inglés (acierta bastante más) y se muestra en español | Propio, < 6 KB | Solo reconoce lo que está en la lista: si fotografías algo que no aparece, contestará lo más parecido, no "no sé". No distingue especies (dice "un ave", no cuál); no lee el texto de los letreros, solo detecta que hay uno. Apenas tiene términos locales y ninguno en lengua indígena (hay que añadirlos con un hablante nativo) |
| `data/vision_labels_emb.json` | Cada etiqueta convertida en 512 números por el lado de texto de CLIP, guardados como enteros de 16 bits. Lo genera la propia app | Derivado del modelo (abajo), 60 KB | Hay que regenerarlo al editar `vision_labels.json`; la app compara la `firma`, avisa y ofrece el botón |

**Para añadir o corregir etiquetas** (no hace falta tocar código ni reiniciar): editar `data/vision_labels.json` → entrar a **Mirar** → *Etiquetas de la cámara* → **Recalcular**. Descarga una vez un modelo de 62 MB que después no vuelve a hacer falta. Es la vía para meter términos de la zona o nombres en otra lengua.

## 2a. En qué idioma se abre la app

El panel se abre en el **idioma del navegador** si está traducido; si no, en **inglés**. Se puede cambiar con el selector de la cabecera y la elección se recuerda. El chat del visitante marca solo el idioma de su teléfono, pero sigue mostrando la lista entera para que elija.

Hay dos idiomas distintos y conviene no confundirlos:

| | Qué es | Quién lo ve |
|---|---|---|
| **Idioma de la app** (selector de la cabecera) | Los textos del panel: botones, avisos, ayudas | La persona a cargo |
| **Idioma de cada lado de Conversar** | En qué se habla y se traduce | Uno la persona a cargo, otro el visitante |

Abrir el panel en inglés deja el lado del visitante en español, y al revés: cada panel está en el idioma de quien lo lee, que es lo que se busca.

## 2b. Modelos que corren en el propio equipo

Se descargan una vez (conviene con buena señal) y quedan guardados en el navegador; después funcionan sin internet. **Ninguna foto ni grabación sale del equipo.**

| Modelo | Para qué | Peso descargado | Licencia | Qué NO hace |
|---|---|---|---|---|
| CLIP ViT-B/32, solo el lado de imagen (`Xenova/clip-vit-base-patch32`, cuantizado a 8 bits) | Pestaña **Mirar**: decir qué hay en una foto | **87 MB** (en vez de 578 MB sin cuantizar). El lado de texto, 62 MB más, **no se descarga**: sus resultados ya vienen en `vision_labels_emb.json` | MIT (modelo) / OpenAI CLIP | Entrenado con imágenes de internet, sobre todo de EE. UU. y Europa: acierta menos con paisajes, comida y objetos de esta región. No es un diagnóstico: ante una hoja enferma da una pista, no un veredicto. No lee texto |
| Whisper tiny (`Xenova/whisper-tiny`, cuantizado a 8 bits) | **Micrófono sin internet** en Conversar | **42 MB** | Apache 2.0 | Es el Whisper más pequeño: se equivoca bastante más que el micrófono del navegador, y mucho más en idiomas con pocos datos de voz. Sin jerga local ni nombres propios de la zona |
| Motor Transformers.js + ONNX Runtime (`src/static/vendor/`) | Ejecuta los dos de arriba | 22 MB **ya incluidos en el proyecto**, los sirve este mismo equipo | Apache 2.0 | No se descarga de internet: si viniera de un CDN, sin conexión no arrancaría por muy guardados que estuvieran los modelos |

Requisitos: un navegador reciente (Chrome/Edge/Firefox) y ~1 GB de RAM libre. Los modelos se cargan de uno en uno; con dos a la vez el navegador se queda sin memoria.

**Qué cuesta la compresión.** El modelo va a 8 bits (87 MB en vez de 578) y los vectores de las etiquetas a 16. Comparado con hacer la misma cuenta sin comprimir nada, los porcentajes se desvían **0,02 puntos** y el orden no cambia. Con los vectores a 8 bits (30 KB menos) la desviación subía a 2,5 puntos y llegaba a intercambiar etiquetas parecidas, así que no compensaba.

**Cuándo no hay que fiarse.** Las etiquetas compiten entre sí, así que siempre gana alguna aunque ninguna encaje. Si las tres primeras salen con porcentajes parecidos, la app lo dice en vez de dar una por buena: significa que la foto se parece casi igual a varias.

**Qué necesita internet y qué no**, una vez descargados los modelos:

| | Sin internet |
|---|---|
| Identificar una foto | ✅ comprobado: 0 peticiones a la red |
| Micrófono de la pestaña Conversar (casilla "sin internet") | ✅ comprobado: 0 peticiones a la red |
| Micrófono normal del navegador | ❌ envía la voz a Google |
| Descargar los modelos la primera vez | ❌ (87 MB y 42 MB, desde huggingface.co) |

## 3. Privacidad y seguridad
- **Dónde están los datos:** SQLite local `data/local_app.db` (fuera de git).
- **Quién puede leerlos:** quien tenga acceso al dispositivo. Si se pierde, depende del bloqueo del equipo.
- **Qué sale del dispositivo:** el texto del turista viaja a MyMemory para traducirse y por Telegram si se usa ese canal. **Las fotos de "Mirar" y el audio del micrófono sin internet no salen nunca:** se procesan aquí. El micrófono normal del navegador sí envía la voz a Google; por eso existe la casilla para usar el de este equipo.
- **Reseñas:** solo se pide un alias; la persona a cargo puede ocultar una reseña (no se borra). La calificación de la reseña es independiente del % de confianza, que solo sube una persona tras revisar certificados.
- **Mensajes delicados** (queja, reembolso, accidente, emergencia): la IA no redacta respuesta; se marca ⚠ para atención personal.
- **Retención:** los mensajes ya enviados se borran tras `RETENTION_DAYS` (30 por defecto).
- **Claves:** solo en `.env` (ignorado por git).
- **Humano en el ciclo:** nada se envía sin aprobación; si la IA no está segura dice "responde tú".
