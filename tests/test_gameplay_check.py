"""Gameplay-Prüfung mit echten (synthetischen) Videos; Gesichtserkenner ersetzt."""
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gameplay_check as g


def make(path, src):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src, "-t", "60", "-r", "5",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)


class GameplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory(); d = Path(cls.t.name)
        cls.moving = d / "m.mp4"; make(cls.moving, "testsrc2=size=360x640:rate=5")
        cls.still = d / "s.mp4"; make(cls.still, "color=c=gray:size=360x640:rate=5")

    @classmethod
    def tearDownClass(cls):
        cls.t.cleanup()

    def test_static_screen_rejected(self):
        ok, why = g.check(self.still, detect=lambda p: [])
        self.assertFalse(ok); self.assertIn("Bewegung", why)

    def test_moving_gameplay_ok(self):
        self.assertTrue(g.check(self.moving, detect=lambda p: [])[0])

    def test_big_face_rejected(self):
        face = lambda p: [{"class": "FACE_MALE", "score": 0.9, "box": [100, 20, 200, 150]}]
        ok, why = g.check(self.moving, detect=face)
        self.assertFalse(ok); self.assertIn("Streamer", why)

    def test_small_face_ok(self):
        face = lambda p: [{"class": "FACE_MALE", "score": 0.9, "box": [10, 10, 20, 20]}]
        self.assertTrue(g.check(self.moving, detect=face)[0])


if __name__ == "__main__":
    unittest.main()
