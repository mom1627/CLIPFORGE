"""Untertitel ohne libass (Mac/Homebrew): Pillow-PNGs + overlay."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import captions  # noqa: E402


class OverlayTest(unittest.TestCase):
    def test_frames_and_list(self):
        with tempfile.TemporaryDirectory() as t:
            words = [(1.0, 1.4, "hallo"), (1.5, 1.9, "welt"), (10.0, 10.5, "ende")]
            lst = captions.build_overlay_frames(words, "Warte bis zum Ende", 540, 960, 20.0, Path(t) / "ov", split=True)
            txt = lst.read_text()
            durs = [float(l.split()[1]) for l in txt.splitlines() if l.startswith("duration")]
            self.assertAlmostEqual(sum(durs), 20.0, places=2)
            self.assertTrue(len(list((Path(t) / "ov").glob("*.png"))) >= 3)

    def test_burn_keeps_length(self):
        with tempfile.TemporaryDirectory() as t:
            mp4 = Path(t) / "c.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=6",
                            "-f", "lavfi", "-i", "sine=d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-shortest", str(mp4)], check=True)
            os.environ["CAPTION_RENDERER"] = "pillow"
            orig = captions.transcribe
            captions.transcribe = lambda p: ([(0.5, 1.0, "test")], "de")
            try:
                captions.add_captions(mp4, "trymacs", "s", split=True)
            finally:
                captions.transcribe = orig; os.environ.pop("CAPTION_RENDERER")
            n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(n, "180")
            self.assertFalse((Path(t) / "c_ov").exists())


if __name__ == "__main__":
    unittest.main()
