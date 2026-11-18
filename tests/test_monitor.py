import math, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import monitor

class DetectorTest(unittest.TestCase):
    def test_spike_detected_once(self):
        d = monitor.Detector(spike_db=7, min_gap=120)
        vals = [-40.0] * 200 + [-18.0] * 12 + [-40.0] * 100
        hits = d.feed(vals)
        self.assertEqual(len(hits), 1)
        self.assertTrue(200 <= hits[0] <= 215)

    def test_constant_loud_stream_no_hits(self):
        d = monitor.Detector()
        self.assertEqual(d.feed([-20.0] * 600), [])

    def test_silence_floor(self):
        d = monitor.Detector()
        self.assertEqual(d.feed([-60.0] * 200 + [-45.0] * 12 + [-60.0] * 50), [])

class AudioTest(unittest.TestCase):
    def test_per_second_db_from_real_ffmpeg(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "s.ts"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                            "-f", "lavfi", "-i", "color=c=black:s=320x180:d=4", "-shortest", "-c:v", "mpeg2video", "-c:a", "mp2", str(f)], check=True)
            v = monitor.per_second_db(f)
            self.assertGreaterEqual(len(v), 3)
            self.assertTrue(all(-30 < x < 0 for x in v))

if __name__ == "__main__":
    unittest.main()
