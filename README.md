# Turismo Rural — Small AI

*[Leer en español](README.es.md)*

An app that lets someone running a rural tourism site **talk with visitors in any language, even with no internet**.

It runs on a modest device, with no servers and no paid accounts. What needs a connection is kept strictly separate from what doesn't, and the app always tells you where each answer came from.

## What it does

| | |
|---|---|
| **Talk** | A face-to-face translator: each person writes or speaks in their own language and reads in theirs. It translates as you type. 12 languages work offline from a built-in phrasebook |
| **Look** | Take a photo and the device tells you what's in it (a viewpoint, a diseased plant, litter on the trail). **The photo never leaves the device** |
| **Explore** | Real nearby places pulled from OpenStreetMap and saved for offline use |
| **Messages** | Visitors write from their phone or over Telegram; messages are stored and sent when the signal comes back |

## Running it

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
cp .env.example .env
.venv/Scripts/python -m src.main                # Linux/macOS: .venv/bin/python
```

Then, in the browser:

- **http://127.0.0.1:8000** — the host's panel
- **http://127.0.0.1:8000/chat** — the visitor's chat

With `HOST=0.0.0.0` in `.env`, visitors on the same wifi can open the chat from their phone. The panel still answers only on this device.

The interface opens in the browser's language and falls back to English. You can change it from the selector in the header.

## Where the "Small AI" ideas live in the code

| Idea | Where it is |
|---|---|
| **One well-defined problem** | Eight fixed intents, one device, no datacenter |
| **Offline / on-device** | Phrasebook and intents as JSON; CLIP and Whisper running in the browser; cache on disk |
| **Quantization** | The image model runs at 8 bits: 87 MB instead of 578. The label vectors at 16 |
| **Store-and-forward** | [`src/sync.py`](src/sync.py): messages wait in SQLite and go out when there's signal |
| **Speech recognition** | The browser's (needs internet) and **Whisper on the device itself** (doesn't) |
| **Computer vision** | CLIP compares the photo against labels you can edit in [`data/vision_labels.json`](data/vision_labels.json) |

Verified with the network fully cut: identifying a photo and transcribing speech both run with **zero network requests**.

### The part worth a closer look

CLIP ships as 578 MB. Two decisions bring it down to **87 MB**.

Quantizing to 8 bits is the obvious one. The other is that CLIP has two halves — one reads images, the other reads text — and the text half only exists to turn labels into vectors. That can be done once, ahead of time. So the precomputed vectors ship as a 60 KB file and the text half, another 62 MB, is never downloaded.

Measured cost of that compression: **0.02 percentage points** of drift against running it uncompressed, with no change in ranking.

## What leaves the device and what doesn't

- **Never leaves:** the photos in *Look* and the audio from the offline microphone. Both are processed here.
- **Does leave:** text sent out for translation (MyMemory), and messages over Telegram if that channel is in use.
- Sent messages are deleted after `RETENTION_DAYS` (30 by default).
- Reviews only ask for an alias. They are **not verified**, and the app says so.
- Sensitive messages (complaints, refunds, accidents) are flagged ⚠ and the AI writes no reply: a person answers.

Per-installation data (`.env`, the database, downloaded places) is deliberately kept out of git.

## Layout

```
src/api.py          HTTP routes
src/sync.py         store-and-forward
src/utils.py        intents, translation, reviews (standard library only)
src/places_osm.py   OpenStreetMap download
src/static/ai.js    models that run in the browser
data/*.json         phrases, intents, labels and interface text: editable without touching code
deploy/             builds the static+PHP demo for shared hosting
```

The files under `data/` are meant to be corrected by whoever knows the area: they're text, not code.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

## Known limits

All of them are in **[DATASETS.md](DATASETS.md)**: where every piece of data comes from, its licence, and what it does **not** cover. In short:

- Translations into languages other than Spanish and English were produced by an AI and have **not been reviewed by a native speaker**.
- There is no indigenous language and no local slang yet. Adding them takes a speaker, not an AI.
- CLIP was trained mostly on images from the US and Europe, so it is weaker on landscapes and food from other regions. It gives a hint, not a diagnosis.
- Whisper tiny makes considerably more mistakes than the browser's microphone.
- The problem figures in `DATASETS.md` are still marked `TODO`: they need the exact number, country and year.

## Credits and licences

Place data © **OpenStreetMap** contributors (ODbL). Translation: **MyMemory**. Weather: **Open-Meteo**. Models: **CLIP** (MIT) and **Whisper** (Apache 2.0) via **Transformers.js** (Apache 2.0), vendored in `src/static/vendor/` so the app starts with no connection.
