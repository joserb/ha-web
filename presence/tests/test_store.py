import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import build_router
from app.inference import ENTERED, HIGH, LEFT, LOW, PersonResult, Verdict
from app.store import Invalid, NotFound, PresenceStore
from app.tracking import FaceSample, Observation

ANA = (1.0, 0.0, 0.0)
BEA = (0.0, 1.0, 0.0)
THRESHOLD = 0.363
DAY = 86400


def result(direction, embedding=None, person_id=None, t=100.0, snapshot=None):
    face = FaceSample(embedding, 0.01, b"\xff\xd8face") if embedding else None
    return PersonResult(person_id, 0.0, Observation(t, (0, 0, 1, 1)), Observation(t + 5, (0, 0, 1, 1)),
                        Verdict(direction, HIGH), face, snapshot)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PresenceStore(str(Path(self.temp.name) / "presence.sqlite3"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def track_ids(self, event_id):
        return [row[0] for row in self.store.db.execute(
            "SELECT id FROM tracks WHERE event_id = ? ORDER BY id", (event_id,))]

    def test_labelling_teaches_the_gallery_and_reidentifies_other_faces(self):
        first = self.store.record_event(100, 110, 120, "ok", 40, [result(ENTERED, ANA)])
        second = self.store.record_event(200, 210, 220, "ok", 40, [result(LEFT, (0.95, 0.05, 0.0))])
        self.assertEqual(self.store.event_lines(second), [("Persona desconocida", LEFT, HIGH)])

        ana = self.store.add_person("  Ana  ", 1)
        self.store.label_track(self.track_ids(first)[0], ana, THRESHOLD)

        self.assertEqual(self.store.event_lines(second), [("Ana", LEFT, HIGH)])
        people = self.store.people()
        self.assertEqual([(p["name"], p["state"], p["samples"]) for p in people], [("Ana", "away", 1)])
        self.assertEqual(len(self.store.gallery()), 1)

    def test_state_follows_the_latest_event_and_ignored_tracks_do_not_count(self):
        sample = self.store.record_event(50, 60, 70, "ok", 40, [result(ENTERED, ANA)])
        ana = self.store.add_person("Ana", 1)
        self.store.label_track(self.track_ids(sample)[0], ana, THRESHOLD)
        self.store.record_event(100, 110, 120, "ok", 40, [result(LEFT, ANA, ana)])
        latest = self.store.record_event(200, 210, 220, "ok", 40, [result(ENTERED, ANA, ana)])
        self.assertEqual(self.store.people()[0]["state"], "home")
        self.store.ignore_track(self.track_ids(latest)[0], THRESHOLD)
        self.assertEqual(self.store.people()[0]["state"], "away")
        self.assertEqual(self.store.events()[0]["people"], [])

    def test_manual_label_is_not_overwritten_by_the_gallery(self):
        event = self.store.record_event(100, 110, 120, "ok", 40, [result(ENTERED, ANA), result(ENTERED, ANA)])
        ana, bea = self.store.add_person("Ana", 1), self.store.add_person("Bea", 1)
        first, second = self.track_ids(event)
        self.store.label_track(second, bea, THRESHOLD)   # el usuario sabe algo que el modelo no
        self.store.label_track(first, ana, THRESHOLD)
        names = [line[0] for line in self.store.event_lines(event)]
        self.assertEqual(names, ["Ana", "Bea"])

    def test_deleting_a_person_erases_their_samples_and_images(self):
        event = self.store.record_event(100, 110, 120, "ok", 40, [result(ENTERED, ANA, snapshot=b"body")])
        ana = self.store.add_person("Ana", 1)
        track_id = self.track_ids(event)[0]
        self.store.label_track(track_id, ana, THRESHOLD)
        self.store.delete_person(ana, THRESHOLD)
        self.assertEqual(self.store.gallery(), [])
        self.assertEqual(self.store.people(), [])
        self.assertEqual(self.store.event_lines(event), [("Persona desconocida", ENTERED, HIGH)])
        with self.assertRaises(NotFound):
            self.store.track_image(track_id)

    def test_people_seen_from_behind_can_be_labelled_without_teaching_the_gallery(self):
        event = self.store.record_event(100, 110, 120, "ok", 40, [result(LEFT, snapshot=b"back")])
        ana = self.store.add_person("Ana", 1)
        track_id = self.track_ids(event)[0]
        self.assertEqual(self.store.track_image(track_id), b"back")
        self.assertTrue(self.store.events()[0]["people"][0]["has_image"])
        self.store.label_track(track_id, ana, THRESHOLD)
        self.assertEqual(self.store.gallery(), [])
        self.assertEqual(self.store.people()[0]["state"], "away")

    def test_body_snapshot_is_preferred_and_old_tracks_fall_back_to_the_face(self):
        event = self.store.record_event(100, 110, 120, "ok", 40, [
            result(ENTERED, ANA, snapshot=b"body"), result(ENTERED, BEA), result(LEFT)])
        with_body, face_only, nothing = self.track_ids(event)
        self.assertEqual(self.store.track_image(with_body), b"body")
        self.assertEqual(self.store.track_image(face_only), b"\xff\xd8face")
        with self.assertRaises(NotFound):
            self.store.track_image(nothing)
        self.assertEqual([p["has_image"] for p in self.store.events()[0]["people"]], [True, True, False])

    def test_migration_clears_short_faceless_tracks_of_the_old_log(self):
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        event = self.store.record_event(100, 110, 120, "ok", 40, [])
        self.store.db.execute("PRAGMA user_version = 0")
        rows = [(event, 100, 100.4, None), (event, 100, 103, None), (event, 100, 100.2, None)]
        with self.store.db:
            self.store.db.executemany("""INSERT INTO tracks (event_id, first_t, last_t, direction, confidence,
                                         face_id) VALUES (?, ?, ?, 'left', 'low', ?)""", rows)
            face = self.store.db.execute("INSERT INTO faces (event_id, created_at, jpeg, embedding) VALUES (?, 1, x'00', x'00')",
                                         (event,)).lastrowid
            self.store.db.execute("UPDATE tracks SET face_id = ? WHERE last_t = 100.2", (face,))
        self.store.close()
        self.store = PresenceStore(path)
        durations = sorted(row[0] for row in self.store.db.execute("SELECT last_t - first_t FROM tracks"))
        self.assertEqual([round(d, 1) for d in durations], [0.2, 3.0])  # la corta con cara se queda

    def test_names_are_unique_and_bounded(self):
        ana = self.store.add_person("Ana", 1)
        self.assertEqual(self.store.add_person("ana", 1), ana)
        bea = self.store.add_person("Bea", 1)
        with self.assertRaises(Invalid):
            self.store.rename_person(bea, "ANA")
        with self.assertRaises(Invalid):
            self.store.add_person("   ", 1)
        with self.assertRaises(NotFound):
            self.store.rename_person(999, "Carla")

    def test_retention_purges_events_and_unlabelled_faces_but_keeps_samples(self):
        old = self.store.record_event(100, 110, 120, "ok", 40, [result(ENTERED, ANA), result(LEFT, BEA)])
        ana = self.store.add_person("Ana", 1)
        kept = self.track_ids(old)[0]
        self.store.label_track(kept, ana, THRESHOLD)
        recent = self.store.record_event(40 * DAY, 40 * DAY + 5, 40 * DAY + 9, "ok", 4, [result(LEFT, BEA)])

        self.assertEqual(self.store.purge(40 * DAY, 30), 1)
        self.assertEqual([e["id"] for e in self.store.events()], [recent])
        self.assertEqual(len(self.store.gallery()), 1)
        # La muestra de Ana y la cara del evento reciente; la de Bea del viejo, fuera.
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM faces").fetchone()[0], 2)


class ApiTests(unittest.TestCase):
    origin = {"Origin": "http://localhost:8080", "Host": "localhost:8080"}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PresenceStore(str(Path(self.temp.name) / "presence.sqlite3"))
        self.changes = 0
        app = FastAPI()

        def changed():
            self.changes += 1
        app.include_router(build_router(self.store, lambda: {"healthy": True, "enabled": True}, THRESHOLD, changed))
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8080")
        self.event = self.store.record_event(100, 110, 120, "ok", 40, [result(ENTERED, ANA)])
        self.track = self.store.db.execute("SELECT id FROM tracks").fetchone()[0]

    def tearDown(self):
        asyncio.run(self.client.aclose())
        self.store.close()
        self.temp.cleanup()

    def request(self, method, url, **kwargs):
        return asyncio.run(self.client.request(method, url, **kwargs))

    def test_label_with_a_new_name_and_state(self):
        response = self.request("POST", f"/api/presence/tracks/{self.track}/label", json={"name": "Ana"},
                                headers=self.origin)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["people"][0]["name"], "Ana")
        self.assertEqual(body["events"][0]["people"][0]["name"], "Ana")
        self.assertEqual(self.changes, 1)

    def test_mutations_require_the_dashboard_origin_and_json(self):
        foreign = {"Origin": "http://evil.example", "Host": "localhost:8080"}
        self.assertEqual(self.request("POST", f"/api/presence/tracks/{self.track}/ignore", json={},
                                      headers=foreign).status_code, 403)
        # Un formulario de otra web no llega a ejecutarse (el cuerpo no es JSON).
        self.assertIn(self.request("POST", f"/api/presence/tracks/{self.track}/ignore", content="{}",
                                      headers={**self.origin, "Content-Type": "text/plain"}).status_code,
                      (415, 422))
        self.assertEqual(self.changes, 0)

    def test_label_needs_exactly_one_target_and_existing_track(self):
        self.assertEqual(self.request("POST", f"/api/presence/tracks/{self.track}/label", json={},
                                      headers=self.origin).status_code, 422)
        self.assertEqual(self.request("POST", "/api/presence/tracks/999/label", json={"name": "Ana"},
                                      headers=self.origin).status_code, 404)
        self.assertEqual(self.store.people(), [])  # sin trayectoria no se crea a nadie

    def test_track_image_is_never_cached(self):
        response = self.request("GET", f"/api/presence/tracks/{self.track}/image")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["content-type"], "image/jpeg")

    def test_delete_person(self):
        self.request("POST", f"/api/presence/tracks/{self.track}/label", json={"name": "Ana"}, headers=self.origin)
        person = self.store.people()[0]["id"]
        response = self.request("DELETE", f"/api/presence/people/{person}", json={}, headers=self.origin)
        self.assertEqual(response.json()["people"], [])


if __name__ == "__main__":
    unittest.main()
