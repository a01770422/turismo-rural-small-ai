<?php
/* Acceso a la base de datos de la demo.
 *
 * Sin base configurada la demo no se rompe: Conversar, Mirar y Explorar no la necesitan.
 * Solo se apagan los mensajes y las reseñas, y la pantalla lo dice en vez de fallar.
 */
declare(strict_types=1);

function bd(): ?PDO {
    static $pdo = false;              // false = aún no se ha intentado; null = no hay
    if ($pdo !== false) return $pdo;
    $pdo = null;
    $cfg = @include __DIR__ . '/config.php';
    if (!is_array($cfg) || empty($cfg['base'])) return null;
    try {
        $dsn = "mysql:host={$cfg['servidor']};dbname={$cfg['base']};charset=utf8mb4";
        $pdo = new PDO($dsn, (string)$cfg['usuario'], (string)$cfg['contrasena'], [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
        prepararTablas($pdo);
    } catch (Throwable $e) {
        error_log('solum: no se pudo abrir la base: ' . $e->getMessage());
        $pdo = null;                  // la demo sigue, sin mensajes ni reseñas
    }
    return $pdo;
}

/** Crea las tablas la primera vez. Se hace una sola vez por hora, no en cada petición. */
function prepararTablas(PDO $pdo): void {
    $marca = sys_get_temp_dir() . '/solum_tablas_' . md5(__DIR__);
    if (is_file($marca) && time() - (int)filemtime($marca) < 3600) return;
    $sql = (string)@file_get_contents(__DIR__ . '/_esquema.sql');
    foreach (array_filter(array_map('trim', explode(';', $sql))) as $sentencia) {
        if (!str_starts_with(strtoupper($sentencia), 'CREATE')) continue;
        try { $pdo->exec($sentencia); } catch (Throwable $e) {
            error_log('solum: esquema: ' . $e->getMessage());
        }
    }
    @touch($marca);
}

/* ---------- Reseñas ---------- */

function reseñasDe(string $placeId): array {
    $pdo = bd();
    if (!$pdo) return ['n' => 0, 'avg' => null, 'reviews' => [], 'sin_base' => true];
    $q = $pdo->prepare('SELECT id, author, rating, text, created_at FROM reviews
                        WHERE place_id = ? AND status = \'published\'
                        ORDER BY id DESC LIMIT 50');
    $q->execute([$placeId]);
    $filas = $q->fetchAll();
    $n = count($filas);
    $avg = $n ? round(array_sum(array_column($filas, 'rating')) / $n, 1) : null;
    return ['n' => $n, 'avg' => $avg, 'reviews' => $filas];
}

/** Devuelve el id de la reseña, o un mensaje de por qué no se pudo. */
function guardarReseña(string $placeId, string $autor, int $estrellas, string $texto): array {
    $pdo = bd();
    if (!$pdo) return ['error' => 'Las reseñas necesitan base de datos y esta demo no la tiene configurada.'];
    $autor = trim($autor);
    $texto = trim($texto);
    if (mb_strlen($autor) < 2 || mb_strlen($autor) > 30 || mb_strlen($texto) < 10 || mb_strlen($texto) > 500
        || $estrellas < 1 || $estrellas > 5) {
        return ['error' => 'Revisa los campos: nombre (2-30) y reseña (10-500 caracteres).'];
    }
    // Filtro mínimo contra spam, igual que en la app real: nada de enlaces.
    if (preg_match('~https?://|www\.~i', $texto)) {
        return ['error' => 'No se permiten enlaces en las reseñas.'];
    }
    // Y nada de repetir desde la misma IP en el mismo minuto.
    $q = $pdo->prepare('SELECT COUNT(*) FROM reviews WHERE place_id = ? AND created_at > (NOW() - INTERVAL 1 MINUTE)');
    $q->execute([$placeId]);
    if ((int)$q->fetchColumn() > 2) return ['error' => 'Demasiadas reseñas seguidas. Espera un momento.'];

    $ins = $pdo->prepare('INSERT INTO reviews (place_id, author, rating, text, lang) VALUES (?,?,?,?,?)');
    $ins->execute([$placeId, $autor, $estrellas, $texto, 'es']);
    return ['id' => (int)$pdo->lastInsertId()];
}

/* ---------- Mensajes de visitantes ---------- */

function guardarMensaje(string $chatId, string $nombre, string $lang, string $texto, ?string $traducido): array {
    $pdo = bd();
    if (!$pdo) return ['error' => 'El chat necesita base de datos y esta demo no la tiene configurada.'];
    $texto = trim($texto);
    if ($texto === '' || mb_strlen($texto) > 500) return ['error' => 'Mensaje vacío o demasiado largo.'];
    $ins = $pdo->prepare('INSERT INTO messages (channel, chat_id, name, lang, original_text, translated_text, status)
                          VALUES (\'web\', ?, ?, ?, ?, ?, \'pending\')');
    $ins->execute([$chatId, mb_substr(trim($nombre), 0, 30), $lang, $texto, $traducido]);
    return ['id' => (int)$pdo->lastInsertId()];
}

/** La conversación de un visitante: lo que escribió y lo que le respondieron. */
function conversacion(string $chatId): array {
    $pdo = bd();
    if (!$pdo) return ['sin_base' => true, 'messages' => []];
    $q = $pdo->prepare('SELECT id, original_text, translated_text, host_text, final_response, status, created_at
                        FROM messages WHERE channel = \'web\' AND chat_id = ? ORDER BY id');
    $q->execute([$chatId]);
    return ['messages' => $q->fetchAll()];
}
