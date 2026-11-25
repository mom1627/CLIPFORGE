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


class BoxStyleTest(unittest.TestCase):
    def test_white_and_red_box_at_seam(self):
        from PIL import Image
        words = [(1.0, 1.4, "das"), (1.4, 1.9, "ist"), (12.0, 12.4, "sie"), (12.4, 12.8, "widern"), (12.8, 13.2, "ihn"), (13.2, 13.5, "an")]
        quote = captions.pick_quote(words, around=12.5)
        self.assertEqual(quote, "sie widern ihn an")
        with tempfile.TemporaryDirectory() as t:
            lst = captions.build_overlay_frames(words, captions.pick_hook("montanablack88", "1", "de"), 720, 1280, 20.0,
                                                Path(t) / "ov", split=True, quote=quote, style="box")
            first = (Path(t) / "ov" / lst.read_text().split("'")[1])
            img = Image.open(first).convert("RGBA")
            col = [img.getpixel((360, y)) for y in range(380, 700)]
            self.assertTrue(any(p[:3] == (255, 255, 255) and p[3] == 255 for p in col))   # weißer Kasten
            self.assertTrue(any(p[:3] == (232, 59, 59) and p[3] == 255 for p in col))     # roter Kasten
            self.assertIn("ffconcat", lst.read_text())

    def test_display_name_in_hook(self):
        self.assertIn("Monte", captions.pick_hook("montanablack88", "seed", "de"))


if __name__ == "__main__":
    unittest.main()


class HookVarietyTest(unittest.TestCase):
    def test_quote_hook_from_speech(self):
        import os, captions
        os.environ.pop("CAMPAIGN", None)
        words = [(10.0 + i * 0.3, 10.25 + i * 0.3, w) for i, w in enumerate("not even a warning bro".split())]
        self.assertEqual(captions.make_hook("xqc", "s", "en", words, 11.0).lower(), "not even a warning bro")

    def test_template_fallback_varies(self):
        import os, captions
        os.environ.pop("CAMPAIGN", None)
        hooks = {captions.make_hook("xqc", f"seed{i}", "en", [], None) for i in range(40)}
        self.assertGreaterEqual(len(hooks), 8)
        self.assertFalse(any("loses his mind" in h for h in hooks))
