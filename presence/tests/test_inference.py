import unittest

from app.identity import cosine, identify
from app.inference import (ENTERED, HIGH, LEFT, LOW, MEDIUM, STAYED, UNCLEAR, Window, classify, describe,
                           summarize)
from app.tracking import Detection, FaceSample, Observation, Tracker, iou

ZONE = (0.8, 0.0, 1.0, 1.0)
DOOR = (0.85, 0.2, 0.98, 0.9)    # centro dentro de la franja de la puerta
ROOM = (0.3, 0.2, 0.45, 0.9)     # centro en el salón
OPEN, CLOSE = 100.0, 110.0


def obs(t, box):
    return Observation(t, box)


def face(vector, quality=0.01):
    return FaceSample(tuple(vector), quality, b"jpeg")


class ClassifyTests(unittest.TestCase):
    window = Window(OPEN, CLOSE, ZONE)

    def test_entering_person_appears_at_the_door_and_stays_inside(self):
        self.assertEqual(classify(obs(101, DOOR), obs(115, ROOM), self.window).direction, ENTERED)
        self.assertEqual(classify(obs(101, DOOR), obs(115, ROOM), self.window).confidence, HIGH)

    def test_entering_person_who_walks_out_of_frame_before_closing(self):
        verdict = classify(obs(101, DOOR), obs(106, ROOM), self.window)
        self.assertEqual((verdict.direction, verdict.confidence), (ENTERED, MEDIUM))

    def test_leaving_person_crosses_to_the_door_before_it_opens(self):
        verdict = classify(obs(95, ROOM), obs(101, DOOR), self.window)
        self.assertEqual((verdict.direction, verdict.confidence), (LEFT, HIGH))

    def test_leaving_person_first_seen_after_opening(self):
        verdict = classify(obs(100.5, ROOM), obs(103, DOOR), self.window)
        self.assertEqual((verdict.direction, verdict.confidence), (LEFT, MEDIUM))

    def test_someone_who_opens_for_a_delivery_stays(self):
        self.assertEqual(classify(obs(95, ROOM), obs(115, DOOR), self.window).direction, STAYED)

    def test_user_heuristic_as_fallback(self):
        # Visto solo después de cerrar: entró.
        self.assertEqual(classify(obs(112, ROOM), obs(116, ROOM), self.window).direction, ENTERED)
        self.assertEqual(classify(obs(112, ROOM), obs(116, ROOM), self.window).confidence, LOW)
        # Visto en la sala durante la apertura y ya no después de cerrar: salió.
        verdict = classify(obs(101, ROOM), obs(104, ROOM), self.window)
        self.assertEqual((verdict.direction, verdict.confidence), (LEFT, LOW))

    def test_door_left_open_past_the_limit_is_unclear_without_evidence(self):
        window = Window(OPEN, None, ZONE)
        self.assertEqual(classify(obs(101, ROOM), obs(104, ROOM), window).direction, UNCLEAR)
        self.assertEqual(classify(obs(101, DOOR), obs(104, ROOM), window).direction, ENTERED)


class TrackerTests(unittest.TestCase):
    def test_walking_person_is_one_track_and_two_people_are_two(self):
        tracker = Tracker()
        for step in range(8):
            x = 0.9 - step * 0.08
            tracker.update(100 + step * 0.25, [
                Detection((x, 0.2, x + 0.1, 0.9), 0.8),
                Detection((0.05, 0.3, 0.15, 0.9), 0.7),
            ])
        tracks = tracker.tracks()
        self.assertEqual(len(tracks), 2)
        self.assertTrue(all(len(track.observations) == 8 for track in tracks))

    def test_long_gap_starts_a_new_track_and_single_blips_are_dropped(self):
        tracker = Tracker(max_gap=2)
        tracker.update(100, [Detection(ROOM, 0.8)])
        tracker.update(100.5, [Detection(ROOM, 0.8)])
        tracker.update(110, [Detection(ROOM, 0.8)])
        self.assertEqual(len(tracker.tracks()), 1)
        self.assertEqual(len(tracker.tracks(min_observations=1)), 2)

    def test_single_detection_with_a_face_is_kept(self):
        tracker = Tracker()
        tracker.update(100, [Detection(ROOM, 0.8, face((1, 0)))])
        self.assertEqual(len(tracker.tracks()), 1)

    def test_iou(self):
        self.assertAlmostEqual(iou((0, 0, 1, 1), (0, 0, 1, 1)), 1)
        self.assertEqual(iou((0, 0, 0.1, 0.1), (0.5, 0.5, 1, 1)), 0)


class IdentityTests(unittest.TestCase):
    gallery = [(1, (1.0, 0.0, 0.0)), (2, (0.0, 1.0, 0.0))]

    def test_majority_of_faces_decides(self):
        match = identify([(0.9, 0.1, 0), (0.95, 0.05, 0), (0.1, 0.9, 0)], self.gallery, 0.363)
        self.assertEqual(match.person_id, 1)

    def test_below_threshold_is_unknown(self):
        self.assertIsNone(identify([(0.0, 0.0, 1.0)], self.gallery, 0.363).person_id)
        self.assertIsNone(identify([], self.gallery, 0.363).person_id)

    def test_cosine(self):
        self.assertAlmostEqual(cosine((1, 1), (2, 2)), 1)
        self.assertEqual(cosine((0, 0), (1, 1)), 0)


class SummaryTests(unittest.TestCase):
    def test_tracks_of_one_person_merge_and_unknowns_stay_apart(self):
        tracker = Tracker()
        known = face((1.0, 0.0, 0.0))
        # Ana sale: dos trozos de recorrido separados por una oclusión.
        tracker.update(95, [Detection(ROOM, 0.8, known)])
        tracker.update(95.5, [Detection(ROOM, 0.8)])
        tracker.update(99, [Detection(DOOR, 0.8, known)])
        tracker.update(101, [Detection(DOOR, 0.8), Detection((0.4, 0.2, 0.5, 0.9), 0.8)])
        tracker.update(101.5, [Detection((0.4, 0.2, 0.5, 0.9), 0.8)])
        results = summarize(tracker.tracks(), Window(OPEN, CLOSE, ZONE), [(7, (1.0, 0.0, 0.0))], 0.363)
        self.assertEqual([(r.person_id, r.verdict.direction) for r in results], [(7, LEFT), (None, LEFT)])
        self.assertEqual(results[0].verdict.confidence, HIGH)
        self.assertIs(results[0].face, known)
        self.assertIsNone(results[1].face)

    def test_descriptions(self):
        self.assertEqual(describe([("Ana", ENTERED, HIGH), ("Persona desconocida", LEFT, LOW)], "ok"),
                         "🏠 Ana ha entrado; Persona desconocida ha salido (poco seguro)")
        self.assertIn("sigue dentro", describe([("Ana", STAYED, HIGH)], "ok"))
        self.assertIn("no se vio a nadie", describe([], "nobody_seen"))
        self.assertIn("sin vídeo", describe([], "no_video"))


if __name__ == "__main__":
    unittest.main()
