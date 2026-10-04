# Turismo Rural — Small AI

*[Read in English](README.md)*

Una app para que quien atiende un lugar de turismo rural pueda **hablar con visitantes de cualquier idioma, aunque no haya internet**.

Corre en un equipo modesto, sin servidores ni cuentas de pago. Lo que necesita conexión está separado de lo que no, y la app dice en todo momento de dónde salió cada respuesta.

## Qué hace

| | |
|---|---|
| **Conversar** | Traductor cara a cara: cada persona escribe o habla en su idioma y lee en el suyo. Traduce mientras se escribe. 12 idiomas sin internet con frases guardadas |
| **Mirar** | Se toma una foto y el equipo dice qué hay en ella (un mirador, una planta enferma, basura en el sendero). **La foto no sale del equipo** |
| **Explorar** | Lugares reales de la zona descargados de OpenStreetMap para usarlos sin conexión |
| **Mensajes** | Los visitantes escriben desde su teléfono o por Telegram; se guardan y se envían cuando vuelve la señal |

## Cómo se abre

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # en Linux/macOS: .venv/bin/pip
cp .env.example .env
.venv/Scripts/python -m src.main                # en Linux/macOS: .venv/bin/python
```

Luego, en el navegador:

- **http://127.0.0.1:8000** — el panel de quien atiende
- **http://127.0.0.1:8000/chat** — el chat del visitante

Con `HOST=0.0.0.0` en `.env`, los visitantes conectados a la misma wifi pueden abrir el chat desde su teléfono. El panel sigue respondiendo solo en este equipo.

La app se abre en el idioma del navegador y, si no está traducido, en inglés. Se cambia con el selector de la cabecera.

## Los conceptos de "Small AI" en el código

| Concepto | Dónde está |
|---|---|
| **Problema único y acotado** | Ocho intenciones fijas, un dispositivo, sin centro de datos |
| **Sin conexión / en el dispositivo** | Frasario e intenciones en JSON; CLIP y Whisper corriendo en el navegador; caché en disco |
| **Cuantización** | El modelo de imagen va a 8 bits: 87 MB en vez de 578. Los vectores de las etiquetas, a 16 |
| **Guardar y reenviar** | [`src/sync.py`](src/sync.py): los mensajes esperan en SQLite y salen cuando hay señal |
| **Reconocimiento de voz** | El del navegador (necesita internet) y **Whisper en el propio equipo** (no la necesita) |
| **Visión por computadora** | CLIP compara la foto con etiquetas editables en [`data/vision_labels.json`](data/vision_labels.json) |

Comprobado cortando la red por completo: identificar una foto y transcribir voz funcionan con **cero peticiones a internet**.

## Qué sale del equipo y qué no

- **Nunca salen:** las fotos de *Mirar* y el audio del micrófono sin conexión. Se procesan aquí.
- **Sí sale:** el texto que se manda a traducir (MyMemory) y los mensajes por Telegram, si se usa ese canal.
- Los mensajes ya enviados se borran tras `RETENTION_DAYS` (30 días por defecto).
- Las reseñas solo piden un alias. **No están verificadas** y la app lo dice.
- Los mensajes delicados (queja, reembolso, accidente) se marcan ⚠ y la IA no redacta respuesta: contesta una persona.

Los datos de cada instalación (`.env`, la base de datos, los lugares descargados) están fuera de git a propósito.

## Estructura

```
src/api.py          rutas HTTP
src/sync.py         guardar y reenviar
src/utils.py        intenciones, traducción, reseñas (solo librería estándar)
src/places_osm.py   descarga de OpenStreetMap
src/static/ai.js    modelos que corren en el navegador
data/*.json         frases, intenciones, etiquetas y textos de la app: editables sin tocar código
```

Los archivos de `data/` están pensados para que los corrija quien conoce la zona: son texto, no código.

## Pruebas

```bash
.venv/Scripts/python -m pytest -q
```

## Límites conocidos

Están todos en **[DATASETS.md](DATASETS.md)**: de dónde viene cada dato, qué licencia tiene y qué **no** cubre. En resumen:

- Las traducciones a idiomas distintos del español y el inglés las generó una IA y **no las ha revisado un hablante nativo**.
- No hay ninguna lengua indígena ni jerga local: hay que añadirlas con alguien que las hable.
- CLIP se entrenó sobre todo con imágenes de EE. UU. y Europa: acierta menos con paisajes y comida de otras regiones. Es una pista, no un diagnóstico.
- Whisper tiny se equivoca bastante más que el micrófono del navegador.
- Las cifras del problema en `DATASETS.md` siguen marcadas como `TODO`: hay que completarlas con el dato exacto, el país y el año.

## Créditos y licencias

Datos de lugares © colaboradores de **OpenStreetMap** (ODbL). Traducción: **MyMemory**. Clima: **Open-Meteo**. Modelos: **CLIP** (MIT) y **Whisper** (Apache 2.0) vía **Transformers.js** (Apache 2.0), incluido en `src/static/vendor/` para que la app arranque sin conexión.
