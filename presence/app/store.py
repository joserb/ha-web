"""Eventos, caras y personas en SQLite. Un solo proceso escribe en él.

Las caras son datos biométricos: se guardan solo en el volumen del VPS, se
sirven solo por la API privada y se purgan a los `PRESENCE_RETENTION_DAYS`
salvo las que el usuario etiquetó como muestra de una persona, que viven hasta
que borre a esa persona.
"""
import sqlite3
import threading
from array import array
from pathlib import Path

from app.identity import Gallery, best_match
from app.inference import ENTERED, LEFT, STAYED
from app.tracking import MIN_SECONDS

NAME_MAX = 40


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def _pack(embedding) -> bytes:
    return array("f", embedding).tobytes()


def _unpack(blob: bytes) -> tuple[float, ...]:
    values = array("f")
    values.frombytes(blob)
    return tuple(values)


def clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= NAME_MAX:
        raise Invalid(f"Name must be 1–{NAME_MAX} characters")
    return name


class PresenceStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # El análisis (hilo propio) y la API (bucle asyncio) comparten conexión;
        # el candado serializa, que para este volumen de escrituras sobra.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, opened_at REAL NOT NULL, closed_at REAL,
                analysed_at REAL NOT NULL, status TEXT NOT NULL, frames INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY,
                event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
                created_at REAL NOT NULL, jpeg BLOB NOT NULL, embedding BLOB NOT NULL,
                -- Muestra de galería: solo por decisión del usuario.
                person_id INTEGER REFERENCES people(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                first_t REAL NOT NULL, last_t REAL NOT NULL,
                direction TEXT NOT NULL, confidence TEXT NOT NULL,
                person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
                identity TEXT NOT NULL DEFAULT 'auto',  -- auto | manual (confirmada por el usuario)
                score REAL NOT NULL DEFAULT 0,
                face_id INTEGER REFERENCES faces(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS tracks_event ON tracks(event_id);
            CREATE INDEX IF NOT EXISTS events_opened ON events(opened_at);
        """)
        self._migrate()

    def _migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        with self.db:
            if version < 1:
                # Imagen de la persona entera: quien sale de espaldas no tiene cara.
                if "snapshot" not in {row[1] for row in self.db.execute("PRAGMA table_info(tracks)")}:
                    self.db.execute("ALTER TABLE tracks ADD COLUMN snapshot BLOB")
                # Limpieza del registro anterior al filtro de ruido: trozos de
                # menos de un segundo sin cara, que salían como «salió» sin imagen.
                self.db.execute(f"""DELETE FROM tracks WHERE face_id IS NULL
                                    AND last_t - first_t < {MIN_SECONDS}""")
                self.db.execute("PRAGMA user_version = 1")
            if version < 2:
                # Archivar: revisado por el usuario y fuera del registro, pero
                # sigue contando para saber quién está en casa.
                for table in ("tracks", "events"):
                    if "archived" not in {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
                # «Ignorar» desaparece: lo que el usuario descartó era una
                # detección que no quería ver, así que pasa a borrarse de verdad.
                ignored = [row[0] for row in self.db.execute("SELECT face_id FROM tracks WHERE identity = 'ignored'")]
                self.db.execute("DELETE FROM tracks WHERE identity = 'ignored'")
                self.db.executemany("DELETE FROM faces WHERE id = ?", [(face,) for face in ignored if face])
                self.db.execute("PRAGMA user_version = 2")

    def close(self):
        self.db.close()

    # --- Escritura desde el análisis ---------------------------------------

    def record_event(self, opened_at: float, closed_at: float | None, analysed_at: float,
                     status: str, frames: int, results: list) -> int:
        """`results` son `inference.PersonResult`."""
        with self.lock, self.db:
            event_id = self.db.execute(
                "INSERT INTO events (opened_at, closed_at, analysed_at, status, frames) VALUES (?, ?, ?, ?, ?)",
                (opened_at, closed_at, analysed_at, status, frames)).lastrowid
            for result in results:
                face_id = None
                if result.face is not None:
                    face_id = self.db.execute(
                        "INSERT INTO faces (event_id, created_at, jpeg, embedding) VALUES (?, ?, ?, ?)",
                        (event_id, analysed_at, result.face.jpeg, _pack(result.face.embedding))).lastrowid
                self.db.execute(
                    """INSERT INTO tracks (event_id, first_t, last_t, direction, confidence, person_id, score, face_id,
                                           snapshot)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, result.first.t, result.last.t, result.verdict.direction,
                     result.verdict.confidence, result.person_id, result.score, face_id, result.snapshot))
        return event_id

    def gallery(self) -> Gallery:
        with self.lock:
            rows = self.db.execute("SELECT person_id, embedding FROM faces WHERE person_id IS NOT NULL").fetchall()
        return [(row["person_id"], _unpack(row["embedding"])) for row in rows]

    def names(self) -> dict[int, str]:
        with self.lock:
            return {row["id"]: row["name"] for row in self.db.execute("SELECT id, name FROM people")}

    # --- Decisiones del usuario --------------------------------------------

    def add_person(self, name: str, now: float) -> int:
        name = clean_name(name)
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
            if row:
                return row["id"]
            return self.db.execute("INSERT INTO people (name, created_at) VALUES (?, ?)", (name, now)).lastrowid

    def rename_person(self, person_id: int, name: str):
        name = clean_name(name)
        with self.lock, self.db:
            clash = self.db.execute("SELECT id FROM people WHERE name = ? AND id != ?", (name, person_id)).fetchone()
            if clash:
                raise Invalid("Another person already has that name")
            if self.db.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id)).rowcount == 0:
                raise NotFound("Person not found")

    def delete_person(self, person_id: int, threshold: float):
        """Borra a la persona y sus muestras; sus apariciones pasan a desconocidas."""
        with self.lock, self.db:
            # Supresión completa: también las imágenes de cuerpo atribuidas.
            self.db.execute("UPDATE tracks SET snapshot = NULL WHERE person_id = ?", (person_id,))
            if self.db.execute("DELETE FROM people WHERE id = ?", (person_id,)).rowcount == 0:
                raise NotFound("Person not found")
            self.db.execute("UPDATE tracks SET identity = 'auto', score = 0 WHERE person_id IS NULL AND identity = 'manual'")
            self._reidentify(threshold)

    def _track(self, track_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT id, face_id FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if row is None:
            raise NotFound("Track not found")
        return row

    def require_track(self, track_id: int):
        with self.lock:
            self._track(track_id)

    def label_track(self, track_id: int, person_id: int, threshold: float):
        """Quién era. Si hay cara, además enseña a la galería; si no (de
        espaldas), solo corrige el evento y el estado de esa persona."""
        with self.lock, self.db:
            track = self._track(track_id)
            if not self.db.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone():
                raise NotFound("Person not found")
            if track["face_id"] is not None:
                self.db.execute("UPDATE faces SET person_id = ? WHERE id = ?", (person_id, track["face_id"]))
            self.db.execute("UPDATE tracks SET person_id = ?, identity = 'manual', score = 1 WHERE id = ?",
                            (person_id, track_id))
            self._reidentify(threshold)

    def archive_track(self, track_id: int, threshold: float):
        """Revisado y correcto: la identidad pasa a confirmada (y su cara, si la
        hay, a la galería) y la fila sale del registro. Sigue contando para
        saber quién está en casa. Una persona desconocida se archiva como tal."""
        with self.lock, self.db:
            track = self.db.execute("SELECT id, face_id, person_id FROM tracks WHERE id = ?", (track_id,)).fetchone()
            if track is None:
                raise NotFound("Track not found")
            if track["person_id"] is not None:
                self.db.execute("UPDATE tracks SET identity = 'manual', score = 1 WHERE id = ?", (track_id,))
                if track["face_id"] is not None:
                    self.db.execute("UPDATE faces SET person_id = ? WHERE id = ?", (track["person_id"], track["face_id"]))
            self.db.execute("UPDATE tracks SET archived = 1 WHERE id = ?", (track_id,))
            self._reidentify(threshold)

    def delete_track(self, track_id: int, threshold: float):
        """Detección errónea o que no interesa: se borran la fila, su imagen y
        su cara, también de la galería, y deja de contar para nadie."""
        with self.lock, self.db:
            track = self._track(track_id)
            self.db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            if track["face_id"] is not None:
                self.db.execute("DELETE FROM faces WHERE id = ?", (track["face_id"],))
            self._reidentify(threshold)

    def archive_event(self, event_id: int):
        """Para eventos sin nadie a la vista, que no tienen filas que archivar."""
        with self.lock, self.db:
            if self.db.execute("UPDATE events SET archived = 1 WHERE id = ?", (event_id,)).rowcount == 0:
                raise NotFound("Event not found")

    def _reidentify(self, threshold: float):
        """Aplica la galería actual a las caras que el usuario no ha decidido."""
        gallery = [(row["person_id"], _unpack(row["embedding"]), row["id"]) for row in self.db.execute(
            "SELECT id, person_id, embedding FROM faces WHERE person_id IS NOT NULL")]
        rows = self.db.execute("""SELECT t.id, f.id AS face_id, f.embedding FROM tracks t
                                  JOIN faces f ON f.id = t.face_id WHERE t.identity = 'auto'""").fetchall()
        for row in rows:
            candidates = [(pid, emb) for pid, emb, fid in gallery if fid != row["face_id"]]
            match = best_match(_unpack(row["embedding"]), candidates, threshold)
            self.db.execute("UPDATE tracks SET person_id = ?, score = ? WHERE id = ?",
                            (match.person_id, match.score, row["id"]))

    # --- Lectura para la API -----------------------------------------------

    def track_image(self, track_id: int) -> bytes:
        """La persona entera si se guardó; si no (eventos antiguos), su cara."""
        with self.lock:
            row = self.db.execute("""SELECT t.snapshot, f.jpeg FROM tracks t
                                     LEFT JOIN faces f ON f.id = t.face_id WHERE t.id = ?""", (track_id,)).fetchone()
        image = row and (row["snapshot"] or row["jpeg"])
        if not image:
            raise NotFound("No image for this track")
        return image

    def people(self) -> list[dict]:
        """Cada persona con su estado, derivado de su último evento.

        Derivarlo en vez de guardarlo hace que corregir una etiqueta corrija
        también quién está en casa.
        """
        with self.lock:
            people = self.db.execute("""
                SELECT p.id, p.name,
                       (SELECT count(*) FROM faces f WHERE f.person_id = p.id) AS samples
                FROM people p ORDER BY p.name""").fetchall()
            result = []
            for person in people:
                last = self.db.execute(f"""
                    SELECT t.direction, t.confidence, e.opened_at, e.id AS event_id FROM tracks t
                    JOIN events e ON e.id = t.event_id
                    WHERE t.person_id = ?
                      AND t.direction IN ('{ENTERED}', '{LEFT}', '{STAYED}')
                    ORDER BY e.opened_at DESC, t.id DESC LIMIT 1""", (person["id"],)).fetchone()
                result.append({
                    "id": person["id"],
                    "name": person["name"],
                    "samples": person["samples"],
                    "state": None if last is None else ("away" if last["direction"] == LEFT else "home"),
                    "since": None if last is None else last["opened_at"],
                    "confidence": None if last is None else last["confidence"],
                })
        return result

    def events(self, limit: int = 20, include_archived: bool = False) -> list[dict]:
        """Eventos pendientes de revisar. Uno sale del registro cuando se
        archiva entero o cuando se han archivado todas sus personas."""
        pending = "" if include_archived else """
            WHERE e.archived = 0 AND (NOT EXISTS (SELECT 1 FROM tracks t WHERE t.event_id = e.id)
                                      OR EXISTS (SELECT 1 FROM tracks t WHERE t.event_id = e.id AND t.archived = 0))"""
        with self.lock:
            events = self.db.execute(f"SELECT e.* FROM events e {pending} ORDER BY e.opened_at DESC LIMIT ?",
                                     (limit,)).fetchall()
            names = self.names()
            result = []
            for event in events:
                tracks = self.db.execute(f"""
                    SELECT t.id, t.first_t, t.last_t, t.direction, t.confidence, t.person_id, t.identity,
                           t.score, t.face_id, t.archived,
                           (t.snapshot IS NOT NULL OR f.jpeg IS NOT NULL) AS has_image
                    FROM tracks t LEFT JOIN faces f ON f.id = t.face_id
                    WHERE t.event_id = ? {"" if include_archived else "AND t.archived = 0"}
                    ORDER BY t.first_t""", (event["id"],)).fetchall()
                result.append({
                    **dict(event),
                    "archived": bool(event["archived"]),
                    "people": [{
                        **dict(track),
                        "archived": bool(track["archived"]),
                        "has_image": bool(track["has_image"]),
                        "name": names.get(track["person_id"]),
                    } for track in tracks],
                })
        return result

    def event_lines(self, event_id: int) -> list[tuple[str, str, str]]:
        """(nombre, dirección, confianza) para el texto del aviso."""
        names = self.names()
        with self.lock:
            rows = self.db.execute("""SELECT person_id, direction, confidence FROM tracks
                                      WHERE event_id = ? ORDER BY first_t""",
                                   (event_id,)).fetchall()
        return [(names.get(row["person_id"], "Persona desconocida"), row["direction"], row["confidence"])
                for row in rows]

    def purge(self, now: float, retention_days: int) -> int:
        cutoff = now - retention_days * 86400
        with self.lock, self.db:
            # Las muestras etiquetadas sobreviven a su evento (ON DELETE SET NULL).
            deleted = self.db.execute("DELETE FROM events WHERE opened_at < ?", (cutoff,)).rowcount
            self.db.execute("DELETE FROM faces WHERE person_id IS NULL AND (event_id IS NULL OR created_at < ?)",
                            (cutoff,))
        return deleted
