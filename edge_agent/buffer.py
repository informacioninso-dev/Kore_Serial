"""Buffer offline en disco.

La razon de existir del agente es aguantar un corte de red sin perder lo que
paso en planta. Por eso el buffer es SQLite y no una lista en memoria: si el
PC se reinicia a media jornada, las lecturas siguen ahi.
"""

import json
import os
import sqlite3
import threading


SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    external_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pending_created_idx ON pending (created_at);
"""


class SignalBuffer:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            # Un error de sqlite aqui no le dice nada a quien instala en planta.
            raise RuntimeError(
                f"No existe la carpeta del buffer: {folder}. "
                "Corrige 'buffer_path' en la configuracion del agente."
            )
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def add(self, external_id, payload, created_at):
        """Guarda una lectura. El external_id evita duplicarla al reintentar."""
        with self._lock:
            self._connection.execute(
                "INSERT OR IGNORE INTO pending (external_id, payload, created_at) VALUES (?, ?, ?)",
                (external_id, json.dumps(payload), created_at),
            )
            self._connection.commit()

    def take(self, limit):
        """Devuelve las lecturas mas viejas primero, sin sacarlas del buffer.

        Solo se borran cuando el servidor confirma que las recibio: si el
        proceso muere entre el envio y la confirmacion, se reenvian y el
        servidor las descarta por idempotencia.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT external_id, payload FROM pending ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
        return [(row[0], json.loads(row[1])) for row in rows]

    def drop(self, external_ids):
        if not external_ids:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in external_ids)
            cursor = self._connection.execute(
                f"DELETE FROM pending WHERE external_id IN ({placeholders})", tuple(external_ids)
            )
            self._connection.commit()
            return cursor.rowcount

    def mark_attempt(self, external_ids):
        if not external_ids:
            return
        with self._lock:
            placeholders = ",".join("?" for _ in external_ids)
            self._connection.execute(
                f"UPDATE pending SET attempts = attempts + 1 WHERE external_id IN ({placeholders})",
                tuple(external_ids),
            )
            self._connection.commit()

    def count(self):
        with self._lock:
            return self._connection.execute("SELECT COUNT(*) FROM pending").fetchone()[0]

    def clear(self):
        with self._lock:
            cursor = self._connection.execute("DELETE FROM pending")
            self._connection.commit()
            return cursor.rowcount

    def close(self):
        with self._lock:
            self._connection.close()
