"""Facecam-Erkennung: stabile Gesichtsposition = Webcam, bewegte Gesichter (Spielfiguren) zählen nicht."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import facecam as f


class FacecamTest(unittest.TestCase):
    def test_stable_face_bottom_right(self):
        cam = (0.85, 0.70, 0.05, 0.09)           # Webcam-Gesicht unten rechts, immer gleich
        game = [(0.2 + i * 0.07, 0.3, 0.06, 0.1) for i in range(6)]  # Spielfigur wandert
        per = [[cam, game[i]] for i in range(6)]
        box = f.cam_from_faces(per)
        self.assertIsNotNone(box)
        x, y, w, h = box
        self.assertTrue(x <= 0.85 <= x + w and y <= 0.70 <= y + h)  # Gesicht liegt im Ausschnitt
        self.assertLessEqual(x + w, 1.0); self.assertLessEqual(y + h, 1.0)
        self.assertAlmostEqual((w * 16 / 9) / h, 16 / 9 * 1.06, delta=0.05)  # Seitenverhältnis oberer Teil

    def test_no_stable_face(self):
        per = [[(0.1 * i, 0.3, 0.05, 0.08)] for i in range(6)]
        self.assertIsNone(f.cam_from_faces(per))

    def test_fullscreen_face_is_not_a_facecam(self):
        per = [[(0.35, 0.2, 0.3, 0.5)] for _ in range(6)]
        self.assertIsNone(f.cam_from_faces(per))


if __name__ == "__main__":
    unittest.main()
