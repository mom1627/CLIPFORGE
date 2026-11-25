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

    def test_spike_strength_recorded(self):
        d = monitor.Detector(spike_db=7, min_gap=120)
        hits = d.feed([-40.0] * 200 + [-18.0] * 12 + [-40.0] * 100)
        self.assertGreater(d.strength[hits[0]], 7)

    def test_constant_loud_stream_no_hits(self):
        d = monitor.Detector()
        self.assertEqual(d.feed([-20.0] * 600), [])

    def test_silence_floor(self):
        d = monitor.Detector()
        self.assertEqual(d.feed([-60.0] * 200 + [-45.0] * 12 + [-60.0] * 50), [])

class RangeTest(unittest.TestCase):
    def test_always_60s(self):
        for e in (20, 70, 400):
            a, b = monitor.clip_range(e, 38)
            self.assertEqual(b - a, 60)
            self.assertGreaterEqual(a, 0)

class OffsetTest(unittest.TestCase):
    def test_enough_material_keeps_start(self):
        self.assertEqual(monitor.clip_offset(90.0, 10.0), 10.0)

    def test_gap_at_end_shifts_start_earlier(self):
        self.assertEqual(monitor.clip_offset(65.0, 20.0), 5.0)

    def test_too_short_recording_gives_no_clip(self):
        self.assertIsNone(monitor.clip_offset(50.0, 0.0))

class BuildClipTest(unittest.TestCase):
    def test_real_clip_is_60s_even_with_gap(self):
        """Echte Segmente, das letzte ist zu kurz (Luecke): Ergebnis trotzdem genau 60 s."""
        import os
        os.environ["VIDEO_WIDTH"] = "360"
        os.environ.pop("REQUIRE_FACECAM", None)  # Testbild hat keine Webcam
        with tempfile.TemporaryDirectory() as t:
            rec, out = Path(t) / "rec", Path(t) / "out"; rec.mkdir(); out.mkdir()
            for i, d in enumerate((30, 30, 30, 8)):
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={d}",
                                "-f", "lavfi", "-i", f"sine=frequency=440:duration={d}", "-shortest",
                                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(rec / f"seg_{i:05d}.ts")], check=True)
            # Highlight so, dass das 60-s-Fenster in Segment 3 (nur 8 s statt 30 s) endet
            mp4 = monitor.build_clip(rec, 106, 38, 0, out, "test")
            self.assertIsNotNone(mp4)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                                       capture_output=True, text=True).stdout)
            self.assertAlmostEqual(dur, 60.0, delta=0.5)

class GameFilterTest(unittest.TestCase):
    def test_star_allows_everything(self):
        import live_capture as lc
        for g in ("Just Chatting", "IRL", "Fortnite", "Grand Theft Auto VI"):
            self.assertTrue(lc.game_allowed(g, ["*"]))

    def test_list_still_filters(self):
        import live_capture as lc
        self.assertTrue(lc.game_allowed("Grand Theft Auto VI", ["grand theft auto vi"]))
        self.assertFalse(lc.game_allowed("Fortnite", ["grand theft auto vi"]))

    def test_default_is_everything(self):
        import os, live_capture as lc
        old = os.environ.pop("ALLOWED_GAMES", None)
        try:
            self.assertTrue(lc.game_allowed("Just Chatting"))
        finally:
            if old is not None:
                os.environ["ALLOWED_GAMES"] = old

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


class LiveChoiceTest(unittest.TestCase):
    def test_campaign_auto(self):
        self.assertEqual(monitor.campaign_for("lacy", "Grand Theft Auto VI", "auto"), "lacy")
        self.assertEqual(monitor.campaign_for("xqc", "Grand Theft Auto VI", "auto"), "clipup")
        self.assertEqual(monitor.campaign_for("xqc", "Just Chatting", "auto"), "")
        self.assertEqual(monitor.campaign_for("xqc", "Just Chatting", "clipup"), "clipup")

    def test_pick_most_viewers_then_rotate(self):
        live = {"a": {"viewers": 100, "game": "GTA"}, "b": {"viewers": 900, "game": "GTA"}}
        self.assertEqual(monitor.pick_live(live, ["*"], {}, 1000.0, 600), "b")
        self.assertEqual(monitor.pick_live(live, ["*"], {"b": 900.0}, 1000.0, 600), "a")  # b pausiert
        self.assertEqual(monitor.pick_live({"b": live["b"]}, ["*"], {"b": 900.0}, 1000.0, 600), "b")  # sonst keiner
        self.assertIsNone(monitor.pick_live(live, ["chess"], {}, 1000.0, 600))


class PriorityTest(unittest.TestCase):
    def test_priority_channel_wins(self):
        import os
        os.environ["PRIORITY_CHANNELS"] = "trymacs"
        live = {"trymacs": {"viewers": 400, "game": "GTA"}, "xqc": {"viewers": 1000, "game": "GTA"}}
        self.assertEqual(monitor.pick_live(live, ["*"], {}, 0.0, 600), "trymacs")
        os.environ.pop("PRIORITY_CHANNELS")
