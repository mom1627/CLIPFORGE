import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import captions

class CaptionTest(unittest.TestCase):
    words = [(0.1, 0.4, "das"), (0.4, 0.8, "war"), (0.8, 1.2, "krass"), (1.3, 1.6, "oh"), (3.0, 3.4, "nein")]
    def test_grouping(self):
        g = captions.group_words(self.words)
        self.assertEqual([x[2] for x in g], ["DAS WAR KRASS", "OH", "NEIN"])
        self.assertTrue(all(a < b for a, b, _ in g))
    def test_hook_deterministic(self):
        self.assertEqual(captions.pick_hook("xqc", "5", "en"), captions.pick_hook("xqc", "5", "en"))
    def test_burn_in_real_ffmpeg(self):
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "a.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=720x1280:d=4:r=30",
                            "-f", "lavfi", "-i", "sine=d=4", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            ass = Path(t) / "a.ass"; ass.write_text(captions.build_ass(self.words, "Das hat niemand kommen sehen", 720, 1280, 4), encoding="utf-8")
            out = Path(t) / "o.mp4"
            r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "a.mp4", "-vf", "ass=a.ass", str(out)], cwd=t, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.8", "-i", str(out), "-frames:v", "1", "/tmp/cap_test.png"], check=True)
            self.assertTrue(out.stat().st_size > 5000)

if __name__ == "__main__":
    unittest.main()
