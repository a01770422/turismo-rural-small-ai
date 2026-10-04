<?php
/* API mínima de la demo.
 *
 * En el equipo de quien atiende esto lo hace FastAPI (src/api.py). Aquí no se puede: el
 * hosting compartido solo corre PHP. Así que lo que no cambia va como archivos .json ya
 * generados, y este archivo solo atiende lo que tiene que salir a internet: traducir.
 *
 * Lo que NO existe en la demo (necesita el servidor Python y su base de datos):
 * mensajes de visitantes, reseñas y guardar los datos de la finca.
 */
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
require __DIR__ . '/datos.php';

$ruta = trim((string)($_GET['r'] ?? ''), '/');
$AQUI = __DIR__;

function salir(array $d, int $code = 200): never {
    http_response_code($code);
    echo json_encode($d, JSON_UNESCAPED_UNICODE);
    exit;
}

function archivo(string $nombre): never {
    $p = __DIR__ . '/' . $nombre . '.json';
    if (!is_file($p)) salir(['detail' => 'no existe en la demo'], 404);
    header('Cache-Control: no-cache');
    readfile($p);
    exit;
}

/* ---------- lo que es solo lectura ---------- */
$FIJOS = ['ui', 'phrases', 'vision-labels', 'vision-embeddings', 'langs', 'operator', 'area', 'share'];
if (in_array($ruta, $FIJOS, true)) archivo($ruta);

if ($ruta === 'templates') {
    $l = preg_replace('/[^a-z]/', '', strtolower((string)($_GET['lang'] ?? 'es')));
    archivo(is_file("$AQUI/templates/$l.json") ? "templates/$l" : 'templates/es');
}

/* Buscar lugares: coincidencia simple por nombre, descripción y etiquetas.
   El ranking completo (confianza, novedad) vive en el servidor Python; aquí no hace falta. */
if ($ruta === 'places') {
    $todos = json_decode((string)file_get_contents("$AQUI/places.json"), true) ?: [];
    $q = trim((string)($_GET['q'] ?? ''));
    if ($q === '') salir($todos);
    $n = normaliza($q);
    $out = array_values(array_filter($todos, function ($p) use ($n) {
        $heno = normaliza($p['name'] . ' ' . $p['desc'] . ' ' . implode(' ', $p['tags'] ?? []));
        foreach (explode(' ', $n) as $palabra) {
            if ($palabra !== '' && !str_contains($heno, $palabra)) return false;
        }
        return true;
    }));
    salir($out);
}

function normaliza(string $t): string {
    $t = mb_strtolower($t, 'UTF-8');
    $t = strtr($t, ['á'=>'a','é'=>'e','í'=>'i','ó'=>'o','ú'=>'u','ü'=>'u','ñ'=>'n']);
    return trim(preg_replace('/\s+/', ' ', preg_replace('/[^\p{L}\p{N} ]/u', ' ', $t)));
}

/* ---------- traducir ---------- */
$cuerpo = json_decode((string)file_get_contents('php://input'), true) ?: [];
$POST = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST';

/* ---------- reseñas ---------- */
// Mismo formato que la app real, para que el navegador no note la diferencia.
if (preg_match('~^places/([A-Za-z0-9_-]{1,80})/reviews$~', $ruta, $m)) {
    $placeId = $m[1];
    if (!$POST) {
        $d = reseñasDe($placeId);
        salir(['reviews' => $d['reviews'], 'n' => $d['n'], 'avg' => $d['avg'],
               // El análisis de temas usa un léxico que vive en la app completa.
               'summary' => ['n' => $d['n'], 'positivas' => 0, 'negativas' => 0, 'temas' => []],
               'sin_base' => $d['sin_base'] ?? false]);
    }
    $r = guardarReseña($placeId, (string)($cuerpo['author'] ?? ''),
                       (int)($cuerpo['rating'] ?? 0), (string)($cuerpo['text'] ?? ''));
    if (isset($r['error'])) salir(['detail' => $r['error']], 422);
    salir($r);
}

/* ---------- chat del visitante ---------- */
if (preg_match('~^chat/([A-Za-z0-9-]{1,64})$~', $ruta, $m)) {
    $chatId = $m[1];
    if ($POST) {
        $texto = (string)($cuerpo['text'] ?? '');
        $lang  = preg_replace('/[^a-z]/', '', strtolower((string)($cuerpo['lang'] ?? 'es')));
        // Se guarda también en español para que quien atiende lo lea sin traducir a mano.
        $trad = $lang === 'es' ? null : (delFrasario($texto, $lang, 'es') ?? porInternet($texto, $lang, 'es')[0]);
        $r = guardarMensaje($chatId, (string)($cuerpo['name'] ?? ''), $lang, $texto, $trad);
        if (isset($r['error'])) salir(['detail' => $r['error']], 422);
        salir(['ok' => true]);
    }
    $after = (int)($_GET['after'] ?? 0);
    $c = conversacion($chatId);
    if (!empty($c['sin_base'])) salir([]);
    $out = [];
    foreach ($c['messages'] as $f) {
        $id = (int)$f['id'];
        if ($f['original_text']) {
            $out[] = ['id' => $id * 2, 'who' => 'me', 'text' => $f['original_text'], 'at' => $f['created_at']];
        }
        if ($f['final_response'] && $f['status'] === 'synced') {
            $out[] = ['id' => $id * 2 + 1, 'who' => 'host', 'text' => $f['final_response'], 'at' => $f['created_at']];
        }
    }
    salir(array_values(array_filter($out, fn($x) => $x['id'] > $after)));
}

/** Busca la frase en el frasario: instantáneo y sin salir a internet. */
function delFrasario(string $texto, string $src, string $dst): ?string {
    static $frases = null;
    if ($frases === null) {
        $pb = json_decode((string)@file_get_contents(__DIR__ . '/_phrases.json'), true) ?: [];
        $frases = $pb['phrases'] ?? [];
    }
    $n = normaliza($texto);
    foreach ($frases as $f) {
        foreach (($f['t'] ?? []) as $lang => $valor) {
            if (($src === 'auto' || $src === $lang) && normaliza((string)$valor) === $n
                && !empty($f['t'][$dst])) {
                return (string)$f['t'][$dst];
            }
        }
    }
    return null;
}

const MALA = ['INVALID', 'MYMEMORY WARNING', 'QUERY LENGTH LIMIT', 'LANGPAIR', 'PLEASE SELECT'];

function mala(?string $t): bool {
    if ($t === null || $t === '') return true;
    foreach (MALA as $m) if (str_contains(strtoupper($t), $m)) return true;
    return false;
}

/** MyMemory. Devuelve [texto, alternativas]. */
function porInternet(string $texto, string $src, string $dst): array {
    if ($src === $dst || !ctype_alpha($src) || !ctype_alpha($dst)) return [null, []];
    $url = 'https://api.mymemory.translated.net/get?' . http_build_query(
        ['q' => $texto, 'langpair' => "$src|$dst"]);
    $ctx = stream_context_create(['http' => ['timeout' => 8, 'ignore_errors' => true]]);
    $raw = @file_get_contents($url, false, $ctx);
    if ($raw === false) return [null, []];
    $d = json_decode($raw, true) ?: [];
    $principal = $d['responseData']['translatedText'] ?? null;
    if (mala($principal)) return [null, []];
    return [$principal, $d['matches'] ?? []];
}

if ($ruta === 'translate') {
    $texto = (string)($cuerpo['text'] ?? '');
    $src = (string)($cuerpo['src'] ?? 'auto');
    $dst = (string)($cuerpo['dst'] ?? 'es');
    if ($texto === '') salir(['text' => null, 'src' => $src, 'via' => null]);
    if ($hit = delFrasario($texto, $src, $dst)) salir(['text' => $hit, 'src' => $src, 'via' => 'frase']);
    [$out] = porInternet($texto, $src, $dst);
    salir(['text' => $out, 'src' => $src, 'via' => $out !== null ? 'internet' : null]);
}

if ($ruta === 'translate/detail') {
    $texto = (string)($cuerpo['text'] ?? '');
    $src = (string)($cuerpo['src'] ?? 'auto');
    $dst = (string)($cuerpo['dst'] ?? 'es');
    // Se pregunta a MyMemory aunque la frase ya estuviera guardada: de ahí salen las
    // otras formas de decirlo, que es medio sentido de abrir el detalle.
    [$red, $matches] = porInternet($texto, $src, $dst);
    $principal = delFrasario($texto, $src, $dst) ?? $red;

    // Otras formas de decirlo: se quedan las que vienen de una frase casi igual, con un
    // largo parecido y que no son casi la misma. (Igual criterio que en utils.py.)
    $alternativas = [];
    $vistas = [normaliza((string)$principal)];
    $largo = count(explode(' ', (string)($principal ?: $texto)));
    usort($matches, fn($a, $b) => ((float)($b['match'] ?? 0)) <=> ((float)($a['match'] ?? 0)));
    foreach ($matches as $m) {
        $t = trim((string)($m['translation'] ?? ''));
        $n = count(explode(' ', $t));
        if ((float)($m['match'] ?? 0) < 0.85 || mala($t)) continue;
        if ($n < max(1, $largo * 0.6) || $n > max(3, $largo * 1.4)) continue;
        $norm = normaliza($t);
        if (in_array($norm, $vistas, true)) continue;
        foreach ($vistas as $v) if (similar_text($norm, $v) / max(1, max(strlen($norm), strlen($v))) > 0.9) continue 2;
        $vistas[] = $norm;
        $alternativas[] = $t;
        if (count($alternativas) >= 3) break;
    }

    // Palabra por palabra, saltando artículos y preposiciones (sueltos no dicen nada).
    $ATADAS = ['el','la','los','las','un','una','de','del','al','a','y','o','en','que',
               'the','an','of','to','and','or','on','at','is','are'];
    $palabras = [];
    preg_match_all('/[^\W\d_]+/u', $texto, $m);
    $vistasP = [];
    foreach ($m[0] as $w) {
        $bajo = mb_strtolower($w, 'UTF-8');
        if (mb_strlen($w) < 2 || in_array($bajo, $ATADAS, true) || isset($vistasP[$bajo])) continue;
        $vistasP[$bajo] = true;
        $t = delFrasario($w, $src, $dst) ?? porInternet($w, $src, $dst)[0];
        if ($t !== null && normaliza($t) !== normaliza($w)) $palabras[] = ['de' => $w, 'a' => $t];
        if (count($palabras) >= 8) break;
    }

    salir([
        'text' => $principal,
        'src' => $src,
        'alternativas' => $alternativas,
        'palabras' => $palabras,
        'roman_origen' => romaniza($texto, $src),
        'roman_destino' => romaniza((string)$principal, $dst),
    ]);
}

/** Cómo suena, para alfabetos que aquí no se leen. No existe para chino, japonés ni
 *  coreano: ahí cada signo es una sílaba o palabra y haría falta un diccionario. */
function romaniza(string $texto, string $lang): ?string {
    static $tablas = null;
    if ($tablas === null) $tablas = json_decode((string)@file_get_contents(__DIR__ . '/_roman.json'), true) ?: [];
    if (empty($tablas[$lang]) || $texto === '') return null;
    $t = $tablas[$lang];
    $out = '';
    foreach (preg_split('//u', $texto, -1, PREG_SPLIT_NO_EMPTY) as $c) {
        $out .= $t[$c] ?? $t[mb_strtolower($c, 'UTF-8')] ?? $c;
    }
    return ($out !== '' && $out !== $texto) ? $out : null;
}

salir(['detail' => 'esta parte necesita la app completa, no está en la demo'], 404);
