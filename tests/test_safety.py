"""Nacktheits-Filter: echte Standbilder aus echtem MP4, Erkenner ersetzt (NudeNet läuft nur in GitHub)."""
import subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import safety


class SafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory(); cls.mp4 = Path(cls.t.name) / "c.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=10:duration=10",
                        "-c:v", "libx264", "-preset", "ultrafast", str(cls.mp4)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.t.cleanup()

    def test_clean_clip_is_safe(self):
        seen = []
        ok, why = safety.check(self.mp4, detect=lambda p: seen.append(p) or [{"class": "FACE_MALE", "score": 0.9}])
        self.assertTrue(ok); self.assertGreaterEqual(len(seen), 18)  # 10 s x (ganz + Gameplay)

    def test_two_exposed_frames_unsafe(self):
        ok, why = safety.check(self.mp4, detect=lambda p: [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.8}])
        self.assertFalse(ok); self.assertIn("Nacktheit", why)

    def test_single_or_weak_hit_stays_safe(self):
        calls = iter(range(100))
        one = lambda p: [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.9}] if next(calls) == 0 else []
        self.assertTrue(safety.check(self.mp4, detect=one)[0])
        # Männerbrust wird oft als Frauenbrust bis ~0,63 erkannt -> darf nicht blockieren
        self.assertTrue(safety.check(self.mp4, detect=lambda p: [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.63}])[0])
        # Po zählt nicht (schlägt auch bei normalen Gameplay-Szenen an)
        self.assertTrue(safety.check(self.mp4, detect=lambda p: [{"class": "BUTTOCKS_EXPOSED", "score": 0.9}])[0])

    def test_single_genitalia_hit_blocks(self):
        calls = iter(range(100))
        one = lambda p: [{"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.4}] if next(calls) == 5 else []
        self.assertFalse(safety.check(self.mp4, detect=one)[0])

    def test_missing_nudenet_blocks_posting(self):
        def boom(p): raise ImportError("no nudenet")
        ok, why = safety.check(self.mp4, detect=boom)
        self.assertFalse(ok); self.assertIn("nicht installiert", why)


if __name__ == "__main__":
    unittest.main()
