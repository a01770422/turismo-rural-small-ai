-- Esquema de la demo en MySQL. Reproduce el de la app real (src/db.py, SQLite) para que
-- no haya dos diseños distintos: los mismos campos, los mismos estados.
--
-- Se ejecuta solo (lo lanza api/index.php la primera vez), pero también se puede pegar
-- tal cual en phpMyAdmin para verlo o rehacerlo a mano.

CREATE TABLE IF NOT EXISTS messages (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  channel         VARCHAR(20)  DEFAULT 'web',
  chat_id         VARCHAR(80),
  name            VARCHAR(30),
  lang            VARCHAR(8),
  original_text   TEXT,
  translated_text TEXT,
  intent          VARCHAR(40),
  confidence      FLOAT,
  needs_human     TINYINT      DEFAULT 0,
  proposed_response TEXT,
  host_text       TEXT,
  final_response  TEXT,
  final_is_es     TINYINT      DEFAULT 0,
  -- entrante: pending | answered | synced   ·   saliente: approved | synced
  status          VARCHAR(12)  DEFAULT 'pending',
  created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_chat (channel, chat_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reviews (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  place_id   VARCHAR(80) NOT NULL,
  author     VARCHAR(30) NOT NULL,
  rating     TINYINT     NOT NULL,
  text       TEXT        NOT NULL,
  lang       VARCHAR(8),
  -- published | hidden. Ocultar no borra: queda el registro.
  status     VARCHAR(12) DEFAULT 'published',
  created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_place (place_id, status),
  CONSTRAINT rating_1_a_5 CHECK (rating BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ajustes sueltos (los datos de la finca, por ejemplo).
CREATE TABLE IF NOT EXISTS meta (
  k VARCHAR(64) PRIMARY KEY,
  v TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
