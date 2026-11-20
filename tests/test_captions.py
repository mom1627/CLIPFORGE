import io
import subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
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
        if not captions._has_ass():
            self.skipTest("FFmpeg hat kein libass")
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "a.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=720x1280:d=4:r=30",
                            "-f", "lavfi", "-i", "sine=d=4", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            ass = Path(t) / "a.ass"; ass.write_text(captions.build_ass(self.words, "Das hat niemand kommen sehen", 720, 1280, 4), encoding="utf-8")
            out = Path(t) / "o.mp4"
            r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "a.mp4", "-vf", "ass=a.ass", str(out)], cwd=t, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.stat().st_size > 5000)

    def test_burn_in_without_ass_respects_caption_intervals(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as t:
            source = Path(t) / "input.mp4"
            output = Path(t) / "output.mp4"
            subprocess.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=320x568:d=4:r=30",
                "-f", "lavfi", "-i", "sine=d=4", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(source),
            ], check=True)
            with patch.object(captions, "_has_ass", return_value=False):
                captions.burn_captions(
                    source, output, self.words, "Ein Hook", hook_seconds=0.6,
                    split=True, hook_y_override=90, subtitle_y_override=370, master_seconds=4,
                )
            self.assertEqual(captions.probe(output), (320, 568, 4.0))

            def frame(second):
                pixels = subprocess.check_output([
                    "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(output),
                    "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1",
                ])
                return Image.open(io.BytesIO(pixels)).convert("RGB")

            self.assertIsNotNone(frame(0.3).crop((0, 70, 320, 200)).getbbox())
            self.assertIsNone(frame(1.5).crop((0, 70, 320, 200)).getbbox())
            self.assertIsNotNone(frame(1.5).crop((0, 350, 320, 490)).getbbox())
            self.assertIsNone(frame(2.4).getbbox())

    def test_three_line_png_hook_fits_above_subtitles(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as t:
            work = Path(t)
            captions._write_overlay_track(
                work, [], "Warte bis zum Schluss und schau genau hin", 720, 1280, 60,
                dict(split=True, hook_seconds=2.8, hook_y_override=380, subtitle_y_override=585),
            )
            with Image.open(work / "overlay-0000.png") as image:
                self.assertLess(image.getbbox()[3], 585)

if __name__ == "__main__":
    unittest.main()
