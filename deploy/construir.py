"""Arma la carpeta que se sube al hosting compartido.

Por qué existe: ese hosting solo corre PHP; no puede tener a uvicorn escuchando en un
puerto. Pero casi toda la app vive en el navegador, así que se puede servir como archivos
y dejar en PHP únicamente lo que necesita salir a internet (la traducción).

Qué entra:  Conversar, Mirar y Explorar (solo lectura).
Qué NO:     Mensajes, reseñas y guardar los datos de la finca. Eso necesita el servidor
            Python y su base de datos, y la demo lo dice en pantalla.

Uso:  python deploy/construir.py            (la app local debe estar corriendo)
"""
import json
import os
import shutil
import tempfile
import time
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Fuera del proyecto a propósito: si cae dentro de OneDrive, el sincronizador bloquea la
# carpeta y la reconstrucción acaba mezclando archivos viejos con nuevos.
SALIDA = Path(os.environ.get("SOLUM_DIST") or Path(tempfile.gettempdir()) / "solum-dist")
LOCAL = "http://127.0.0.1:8000"
IDIOMAS = ["es", "en", "fr", "pt", "de", "it", "zh", "ja", "ko", "ar", "ru", "hi"]


def limpiar(carpeta: Path):
    """Deja la carpeta vacía. Se vacía en vez de borrarla porque en Windows no se puede
    eliminar un directorio que algún proceso tenga abierto (el explorador, una terminal
    situada dentro). Si quedaran archivos de una construcción anterior, se acabaría
    subiendo una mezcla de versiones sin notarlo."""
    if not carpeta.exists():
        carpeta.mkdir(parents=True)
        return
    # El antivirus de Windows abre el .wasm de 21 MB para escanearlo justo después de
    # copiarlo, así que el primer intento suele fallar. Se reintenta con pausas crecientes.
    for hijo in carpeta.iterdir():
        for intento in range(6):
            try:
                shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()
                break
            except PermissionError:
                if intento == 5:
                    sys.exit(f"No se pudo borrar {hijo}. Cierra lo que lo tenga abierto y repite.")
                time.sleep(2 * (intento + 1))


def traer(ruta):
    with urllib.request.urlopen(LOCAL + ruta, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


AVISO = (
    '<p class="guide" style="background:var(--warn);padding:10px 14px;border-radius:10px">'
    'Demostración. <b>Conversar</b> y <b>Mirar</b> funcionan de verdad, incluso sin conexión '
    'una vez descargados los modelos. <b>Mensajes</b>, las reseñas y guardar los datos de la '
    'finca no están aquí: necesitan el servidor de la app, que corre en el equipo de quien '
    'atiende.</p>'
)


def ajustar_para_demo(html: Path):
    """Quita lo que no puede funcionar sin el servidor Python y lo dice en pantalla.
    Si algún reemplazo no encaja, se corta: es señal de que el código cambió y la demo
    quedaría a medias sin avisar."""
    s = html.read_text(encoding="utf-8")
    cambios = [
        # La pestaña Mensajes necesita la base de datos. Se OCULTA, no se borra: el código
        # le asigna manejadores por id y, si desaparece, el script entero se corta ahí.
        ('<button class="alt" id="t2">', '<button class="alt" id="t2" hidden>'),
        # Y sus arranques: sin backend solo dejarían un "sin conexión" confuso.
        ("loadOp();loadShare();getTpl('es').then(()=>{renderThread();loadChats()});",
         "loadOp();getTpl('es');"),
        ("setInterval(()=>{if(!document.hidden)loadChats()},4000);", ""),
        ("<main>", "<main>" + AVISO),
    ]
    for viejo, nuevo in cambios:
        if viejo not in s:
            sys.exit(f"construir.py: no encontré en index.html:\n  {viejo[:90]}\n"
                     "El código cambió; hay que actualizar este script.")
        s = s.replace(viejo, nuevo, 1)
    html.write_text(s, encoding="utf-8")


def main():
    try:
        traer("/api/area")
    except Exception:
        sys.exit(f"La app local no responde en {LOCAL}. Arráncala con: python -m src.main")

    limpiar(SALIDA)
    (SALIDA / "api").mkdir(parents=True)

    # --- lo que no cambia: se congela tal como lo devuelve la app real ---
    fijos = {
        "ui": "/api/ui",
        "phrases": "/api/phrases",
        "vision-labels": "/api/vision-labels",
        "vision-embeddings": "/api/vision-embeddings",
        "langs": "/api/langs",
        "operator": "/api/operator",
        "area": "/api/area",
        "places": "/api/places?q=",
    }
    for nombre, ruta in fijos.items():
        (SALIDA / "api" / f"{nombre}.json").write_text(
            json.dumps(traer(ruta), ensure_ascii=False), encoding="utf-8")

    # Las respuestas rápidas dependen del idioma: una por cada uno.
    (SALIDA / "api" / "templates").mkdir()
    for lang in IDIOMAS:
        (SALIDA / "api" / "templates" / f"{lang}.json").write_text(
            json.dumps(traer(f"/api/templates?lang={lang}"), ensure_ascii=False), encoding="utf-8")

    # En la demo no hay chat de visitantes que compartir: el aviso se apaga.
    (SALIDA / "api" / "share.json").write_text('{"url":"","lan":false}', encoding="utf-8")

    # --- archivos del navegador ---
    shutil.copytree(RAIZ / "src" / "static", SALIDA / "static",
                    ignore=shutil.ignore_patterns("chat.html"))
    for f in ("index.html",):
        shutil.move(str(SALIDA / "static" / f), str(SALIDA / f))

    # La portada se sirve como archivo, no por /hero.
    assets = sorted(p for p in (RAIZ / "assets").iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".jfif", ".png", ".webp"})
    if assets:
        shutil.copy(assets[0], SALIDA / "hero")

    # --- lo que sí necesita ejecutarse: traducir ---
    plantillas = RAIZ / "deploy" / "plantillas"
    shutil.copy(plantillas / "api.php", SALIDA / "api" / "index.php")
    shutil.copy(plantillas / "raiz.htaccess", SALIDA / ".htaccess")
    shutil.copy(plantillas / "api.htaccess", SALIDA / "api" / ".htaccess")

    # El frasario y las tablas de pronunciación los necesita el PHP.
    shutil.copy(RAIZ / "data" / "phrases.json", SALIDA / "api" / "_phrases.json")
    sys.path.insert(0, str(RAIZ))
    from src import utils  # noqa: E402  (se importa aquí para no exigirlo si solo se mira la ayuda)
    (SALIDA / "api" / "_roman.json").write_text(
        json.dumps(utils.ROMAN, ensure_ascii=False), encoding="utf-8")

    ajustar_para_demo(SALIDA / "index.html")

    total = sum(p.stat().st_size for p in SALIDA.rglob("*") if p.is_file())
    print(f"Listo: {SALIDA}")
    print(f"  {sum(1 for p in SALIDA.rglob('*') if p.is_file())} archivos, {total/1048576:.1f} MB")


if __name__ == "__main__":
    main()
