/* Modelos pequeños que corren en el propio equipo, sin enviar nada a ningún servidor.
 *
 * Qué hay aquí:
 *   mirar  — identifica lo que aparece en una foto (CLIP, solo la parte de imagen)
 *   oir    — convierte voz en texto sin internet (Whisper tiny)
 *
 * Por qué pesan poco:
 *   1. Están cuantizados: los números del modelo se guardan en 8 bits en vez de 32,
 *      así ocupa ~4 veces menos y cabe en un equipo modesto.
 *   2. De CLIP solo se descarga el lado de las imágenes (87 MB). El lado del texto
 *      (62 MB más) solo hace falta para traducir las etiquetas a números, y eso ya está
 *      hecho: los vectores vienen calculados en data/vision_labels_emb.json.
 *      Solo se descarga si alguien edita las etiquetas y hay que recalcularlas.
 *
 * Se descargan una vez (conviene hacerlo donde haya buena señal) y quedan guardados
 * en el navegador; después funcionan sin conexión.
 *
 * El motor (la librería y su archivo .wasm) va en static/vendor y lo sirve este mismo equipo.
 * Traerlo de internet no servía: sin conexión no se podía ni arrancar, por muy guardados
 * que estuvieran los modelos.
 */
// La app puede vivir en la raíz o dentro de una carpeta; las rutas se calculan desde
// la de este propio archivo, así funciona en los dos casos.
const AQUI = new URL('.', import.meta.url).href;          // …/static/
const RAIZ = new URL('../', import.meta.url).href;        // …/ (la app)
const LIB = AQUI + 'vendor/transformers.min.js';
const VENDOR = AQUI + 'vendor/';

export const MODELOS = {
  mirar: {id: 'Xenova/clip-vit-base-patch32', dtype: 'q8', mb: 87,
          nombre: 'Identificar fotos',
          que: 'Dice qué se ve en una foto: un lugar, una planta, un letrero, basura en el sendero…',
          req: ['onnx/vision_model_quantized.onnx', 'preprocessor_config.json', 'config.json']},
  oir:   {id: 'Xenova/whisper-tiny', dtype: 'q8', mb: 42,
          nombre: 'Escuchar sin internet',
          que: 'Convierte voz en texto en el propio equipo. El micrófono normal necesita internet; este no.',
          req: ['onnx/encoder_model_quantized.onnx', 'onnx/decoder_model_merged_quantized.onnx',
                'preprocessor_config.json', 'tokenizer.json', 'config.json']},
  texto: {id: 'Xenova/clip-vit-base-patch32', dtype: 'q8', mb: 62,
          nombre: 'Recalcular etiquetas',
          que: 'Solo hace falta si editas las etiquetas de la cámara en data/vision_labels.json.',
          req: ['onnx/text_model_quantized.onnx', 'tokenizer.json', 'config.json']},
};

// Whisper quiere el nombre del idioma escrito, no el código.
const WL = {es:'spanish', en:'english', fr:'french', pt:'portuguese', de:'german', it:'italian',
  zh:'chinese', ja:'japanese', ko:'korean', ar:'arabic', ru:'russian', hi:'hindi',
  nl:'dutch', tr:'turkish', pl:'polish', th:'thai', el:'greek', he:'hebrew'};

let T = null;                       // la librería, se carga la primera vez que hace falta
const cargado = {};                 // modelos ya listos en memoria
const cargando = {};                // cargas en marcha, para no arrancar la misma dos veces
let catalogo = null, vectores = null;
let recalculando = false;

async function lib() {
  if (!T) {
    T = await import(/* @vite-ignore */ LIB);
    T.env.backends.onnx.wasm.wasmPaths = VENDOR;   // el .wasm también sale de este equipo
  }
  return T;
}

/* ---------- Qué hay descargado ya ----------
 * Se mira lo que el navegador tiene guardado para poder avisar del peso antes de gastar
 * los datos de alguien. Solo cuenta como guardado si están TODOS los archivos que el
 * modelo necesita: con una descarga a medias, decir "listo" dejaría al usuario sin forma
 * de reintentar y el fallo aparecería después, ya sin internet. */
export async function estado() {
  const out = {};
  for (const k in MODELOS) out[k] = {...MODELOS[k], listo: k in cargado, guardado: false};
  if (!('caches' in self)) return out;
  let urls = [];
  try {
    const c = await caches.open('transformers-cache');
    urls = (await c.keys()).map(r => r.url);
  } catch { return out; }
  for (const k in MODELOS) {
    const m = MODELOS[k];
    out[k].guardado = m.req.every(f => urls.some(u => u.includes(m.id) && u.endsWith(f)));
  }
  return out;
}

// Con varios modelos a la vez el navegador se queda sin memoria, así que se suelta el anterior.
async function soltarOtros(menos) {
  for (const k in cargado) {
    if (k === menos) continue;
    try { await cargado[k].modelo?.dispose?.(); } catch {}
    delete cargado[k];
  }
}

const avance = (cb) => cb ? (p) => {
  if (p.status === 'progress' && p.total) cb({pct: Math.round(p.loaded / p.total * 100), archivo: p.file});
  else if (p.status === 'done') cb({pct: 100, archivo: p.file});
} : undefined;

// Carga serializada: si ya hay una en marcha para esta clave se espera a esa, y nunca
// se solapan dos modelos distintos (es lo que agota la memoria del navegador).
function unaVez(k, fn) {
  if (cargado[k]) return Promise.resolve(cargado[k]);
  if (cargando[k]) return cargando[k];
  const p = (async () => {
    const otras = Object.values(cargando).filter(x => x !== p);
    if (otras.length) await Promise.allSettled(otras);
    if (cargado[k]) return cargado[k];
    await soltarOtros(k);
    return await fn();
  })().finally(() => { delete cargando[k]; });
  cargando[k] = p;
  return p;
}

/* ---------- Mirar: identificar una foto ---------- */
export async function cargarMirar(cb) {
  return unaVez('mirar', async () => {
    const t = await lib();
    const m = MODELOS.mirar;
    let modelo = null;
    try {
      const [mod, proc] = await Promise.all([
        t.CLIPVisionModelWithProjection.from_pretrained(m.id, {dtype: m.dtype, progress_callback: avance(cb)}),
        t.AutoProcessor.from_pretrained(m.id),
      ]);
      modelo = mod;
      if (!catalogo) catalogo = await pedirCatalogo();
      if (!vectores) vectores = await cargarVectores();
      cargado.mirar = {modelo, proc};
      return cargado.mirar;
    } catch (e) {
      // Si algo falló después de crear la sesión hay que soltarla: son ~87 MB que
      // nadie volvería a referenciar y al tercer intento tumbarían la pestaña.
      try { await modelo?.dispose?.(); } catch {}
      throw e;
    }
  });
}

async function pedirCatalogo() {
  const r = await fetch(RAIZ+'api/vision-labels');
  if (!r.ok) throw new Error('No se pudieron leer las etiquetas. Revisa data/vision_labels.json.');
  return await r.json();
}

const cuantasEtiquetas = (cat) => cat.grupos.reduce((a, g) => a + g.labels.length, 0);

/** Si las etiquetas y sus vectores siguen correspondiéndose. Lo usa la pantalla para
 *  avisar y ofrecer el botón de recalcular. */
export async function estadoEtiquetas() {
  const cat = await pedirCatalogo();
  const n = cuantasEtiquetas(cat);
  const r = await fetch(RAIZ+'api/vision-embeddings');
  if (!r.ok) return {n, estado: 'faltan'};
  const emb = await r.json();
  return {n, estado: emb.firma === cat.firma && emb.n === n ? 'al-dia' : 'desfasado'};
}

async function cargarVectores() {
  const r = await fetch(RAIZ+'api/vision-embeddings');
  if (!r.ok) throw new Error('Faltan los vectores de las etiquetas. Pulsa "Recalcular".');
  const d = await r.json();
  const bin = atob(d.datos), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  // bits=8 son los archivos generados antes de pasar a 16; se siguen leyendo.
  const q = (d.bits || 8) === 16 ? new Int16Array(bytes.buffer) : new Int8Array(bytes.buffer);
  // Se comprueba la cuenta además de la firma: si sobran etiquetas se leería fuera del
  // array y los porcentajes saldrían como NaN, sin que nada avisara.
  const n = cuantasEtiquetas(catalogo);
  const desfasado = d.firma !== catalogo.firma || d.n !== n;
  if (q.length < d.n * d.dim) throw new Error('Los vectores están incompletos. Pulsa "Recalcular".');
  // nb (la norma de cada fila) se calcula al comparar, así que la escala se cancela sola.
  return {...d, q, desfasado, usables: Math.min(d.n, n)};
}

/** Devuelve las etiquetas más parecidas a la imagen, de mayor a menor.
 *  `grupo` limita la comparación a una categoría: con menos opciones parecidas acierta más. */
export async function mirar(imagen, grupo = null, cuantas = 3) {
  const {modelo, proc} = await cargarMirar();
  const t = await lib();
  const img = imagen instanceof Blob ? await t.RawImage.fromBlob(imagen) : await t.RawImage.fromURL(imagen);
  const {pixel_values} = await proc(img);
  const emb = (await modelo({pixel_values})).image_embeds;
  const v = Array.from(await emb.data);
  let n = 0; for (const z of v) n += z * z; n = Math.sqrt(n) || 1;
  const iv = v.map(z => z / n);

  // Las etiquetas están en el mismo orden que en el catálogo; se recorre en paralelo.
  // Solo hasta `usables`: más allá no hay vector que comparar.
  const D = vectores.dim, planas = [];
  for (const g of catalogo.grupos) for (const lb of g.labels) planas.push({grupo: g.id, ...lb});

  const sims = [];
  for (let i = 0; i < Math.min(planas.length, vectores.usables); i++) {
    if (grupo && planas[i].grupo !== grupo) continue;
    let dot = 0, nb = 0;
    for (let j = 0; j < D; j++) { const b = vectores.q[i * D + j]; dot += iv[j] * b; nb += b * b; }
    // Al dividir por la norma de la fila, la escala con que se cuantizó se cancela sola.
    if (nb) sims.push({...planas[i], sim: dot / Math.sqrt(nb)});
  }
  sims.sort((a, b) => b.sim - a.sim);
  const top = sims.slice(0, cuantas);
  if (!top.length) return {desfasado: vectores.desfasado, resultados: []};
  // Softmax sobre los candidatos para dar un porcentaje legible (temperatura como la de CLIP).
  const max = top[0].sim, exp = top.map(s => Math.exp((s.sim - max) * 100));
  const suma = exp.reduce((a, b) => a + b, 0) || 1;
  return {desfasado: vectores.desfasado, resultados: top.map((s, i) => ({...s, pct: exp[i] / suma}))};
}

/* ---------- Oír: voz a texto sin internet ---------- */
export async function cargarOir(cb) {
  return unaVez('oir', async () => {
    const t = await lib();
    const m = MODELOS.oir;
    const modelo = await t.pipeline('automatic-speech-recognition', m.id,
      {dtype: m.dtype, progress_callback: avance(cb)});
    cargado.oir = {modelo};
    return cargado.oir;
  });
}

/** Graba del micrófono hasta que se llame a parar(). Devuelve {audio, parar}.
 *  parar() funciona también mientras el navegador aún está pidiendo permiso: si no,
 *  el micro se quedaría abierto sin que nadie pudiera cerrarlo. */
export function grabar() {
  let rec = null, stream = null, cancelado = false;
  const trozos = [];
  const cerrar = () => stream && stream.getTracks().forEach(t => t.stop());
  const audio = (async () => {
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
    if (cancelado) { cerrar(); return new Blob([], {type: 'audio/webm'}); }
    rec = new MediaRecorder(stream);
    rec.ondataavailable = e => e.data.size && trozos.push(e.data);
    const fin = new Promise(res => { rec.onstop = () => { cerrar(); res(new Blob(trozos, {type: rec.mimeType})); }; });
    rec.start();
    return fin;
  })();
  audio.catch(cerrar);   // permiso denegado o fallo: no dejar el stream abierto
  return {audio, parar: () => {
    cancelado = true;
    if (rec && rec.state !== 'inactive') rec.stop(); else cerrar();
  }};
}

/** Transcribe un audio grabado. Todo ocurre en el equipo: el audio no sale de aquí. */
export async function oir(blob, lang = 'es') {
  const {modelo} = await cargarOir();
  if (!blob || blob.size < 1024) return '';
  // Whisper quiere una sola pista a 16 kHz; el AudioContext se encarga de remuestrear.
  const ctx = new (self.AudioContext || self.webkitAudioContext)({sampleRate: 16000});
  let audio;
  try {
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    audio = buf.getChannelData(0);
    if (buf.numberOfChannels > 1) {   // a mono, promediando
      const b = buf.getChannelData(1), m = new Float32Array(audio.length);
      for (let i = 0; i < audio.length; i++) m[i] = (audio[i] + b[i]) / 2;
      audio = m;
    }
  } finally { ctx.close(); }
  if (audio.length < 1600) return '';          // menos de 0,1 s: no hubo nada
  const r = await modelo(audio, {language: WL[lang] || 'spanish', task: 'transcribe'});
  return (r.text || '').trim();
}

/* ---------- Recalcular las etiquetas ----------
 * Solo hace falta tras editar data/vision_labels.json (p. ej. para añadir términos de la zona).
 * Descarga el lado de texto de CLIP, convierte cada etiqueta en un vector, lo cuantiza a 8 bits
 * y lo guarda en el servidor para que los demás equipos no tengan que descargar nada de esto. */
export async function recalcular(cb) {
  if (recalculando) throw new Error('Ya se están recalculando.');
  recalculando = true;
  let modelo = null;
  try {
    await soltarOtros(null);
    const t = await lib();
    const m = MODELOS.texto;
    const cat = await pedirCatalogo();          // no se toca el catálogo en uso hasta que salga bien
    const planas = [];
    for (const g of cat.grupos) for (const lb of g.labels) planas.push(cat.plantilla.replace('{}', lb.en));
    if (!planas.length) throw new Error('No hay ninguna etiqueta que calcular.');

    const tok = await t.AutoTokenizer.from_pretrained(m.id);
    modelo = await t.CLIPTextModelWithProjection.from_pretrained(m.id,
      {dtype: m.dtype, progress_callback: avance(cb)});
    const salida = await modelo(tok(planas, {padding: true, truncation: true}));
    const datos = await salida.text_embeds.data;
    const N = planas.length, D = salida.text_embeds.dims[1];

    // A enteros de 16 bits: el archivo pasa de ~450 KB a ~61 KB. Cada fila usa toda la
    // escala disponible; al leer se divide por su norma, así que la escala se cancela
    // y no hay que guardarla. (Una escala común para todas perdía precisión: la fijaba
    // el valor más extremo de todo el conjunto.)
    // Con 8 bits el archivo era la mitad, pero el error quedaba del mismo orden que la
    // diferencia entre etiquetas parecidas y llegaba a reordenarlas; 30 KB no valen eso.
    const TOPE = 32767, q = new Int16Array(N * D);
    for (let i = 0; i < N; i++) {
      const fila = datos.slice(i * D, (i + 1) * D);
      let pico = 0;
      for (const z of fila) pico = Math.max(pico, Math.abs(z));
      const k = TOPE / (pico || 1);
      for (let j = 0; j < D; j++) q[i * D + j] = Math.max(-TOPE, Math.min(TOPE, Math.round(fila[j] * k)));
    }

    const u8 = new Uint8Array(q.buffer);
    let bin = '';
    for (let i = 0; i < u8.length; i += 8192) bin += String.fromCharCode(...u8.subarray(i, i + 8192));
    const cuerpo = {modelo: m.id, plantilla: cat.plantilla, dim: D, escala: TOPE, bits: 16, n: N,
                    firma: cat.firma, datos: btoa(bin)};
    const r = await fetch(RAIZ+'api/vision-embeddings',
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cuerpo)});
    if (!r.ok) throw new Error('No se pudieron guardar los vectores.');
    catalogo = cat; vectores = null; delete cargado.mirar;   // se releerán actualizados
    return {n: N, dim: D};
  } catch (e) {
    // Que un fallo a medias no deje el catálogo nuevo con los vectores viejos: así la
    // app seguiría mostrando resultados desplazados y sin avisar.
    catalogo = null; vectores = null; delete cargado.mirar;
    throw e;
  } finally {
    try { await modelo?.dispose?.(); } catch {}
    recalculando = false;
  }
}

export async function olvidar() {
  await soltarOtros(null);
  try { await caches.delete('transformers-cache'); } catch {}
  catalogo = null; vectores = null;
}
