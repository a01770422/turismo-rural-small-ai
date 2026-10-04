<?php
/* Copia este archivo como  config.php  y rellena los cuatro datos de abajo.
 *
 * config.php NO se sube al repositorio ni se incluye en el paquete: lleva la contraseña.
 * Se crea una sola vez directamente en el servidor.
 *
 * Los datos salen de hPanel → Bases de datos → MySQL. Al crear la base, el panel muestra
 * el nombre de la base y del usuario ya con el prefijo de la cuenta (algo como
 * u337980354_solum). La contraseña la eliges tú ahí y la pegas aquí.
 *
 * Si se deja vacío BASE, la demo sigue funcionando: Conversar, Mirar y Explorar no
 * necesitan base de datos. Solo quedan fuera los mensajes y las reseñas.
 */
return [
    'base'       => '',          // p. ej. u337980354_solum
    'usuario'    => '',          // p. ej. u337980354_solum
    'contrasena' => '',          // la que pusiste en hPanel
    'servidor'   => 'localhost', // en Hostinger compartido es localhost
];
