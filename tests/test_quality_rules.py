"""Regeln gegen schlechte Clips: nur GTA, Streamer oben, nur die besten 3 in der App."""
import os, sys, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class StrictGameTest(unittest.TestCase):
    def setUp(self):
        os.environ["STRICT_GAME"] = "Grand Theft Auto VI"

    def tearDown(self):
        os.environ.pop("STRICT_GAME", None)

    def test_only_gta(self):
        import monitor
        allowed = ["grand theft auto vi"]
        self.assertTrue(monitor.game_ok("Grand Theft Auto VI", allowed))
        self.assertFalse(monitor.game_ok("Just Chatting", allowed))
        self.assertFalse(monitor.game_ok(None, allowed))  # unbekannt zählt nicht als GTA

    def test_pick_live_skips_just_chatting(self):
        import monitor
        live = {"hasanabi": {"viewers": 90000, "game": "Just Chatting"},
                "xqc": {"viewers": 20000, "game": "Grand Theft Auto VI"}}
        self.assertEqual(monitor.pick_live(live, ["grand theft auto vi"], {}, 0, 0), "xqc")

    def test_category_switch_stops_clip(self):
        import monitor
        with mock.patch.object(monitor.lc, "live_streams", return_value={"hasanabi": {"viewers": 1, "game": "Just Chatting"}}):
            self.assertFalse(monitor.still_in_game("hasanabi", ["grand theft auto vi"]))
        with mock.patch.object(monitor.lc, "live_streams", return_value=None):
            self.assertFalse(monitor.still_in_game("hasanabi", ["grand theft auto vi"]))
        with mock.patch.object(monitor.lc, "live_streams", return_value={"xqc": {"viewers": 1, "game": "Grand Theft Auto VI"}}):
            self.assertTrue(monitor.still_in_game("xqc", ["grand theft auto vi"]))


class CamCheckTest(unittest.TestCase):
    def test_face_frames(self):
        import gameplay_check
        imgs = [Path(f"{i}.png") for i in range(10)]
        face = lambda p: [{"class": "FACE"}] if int(p.stem) % 2 else []
        self.assertAlmostEqual(gameplay_check.face_frames(imgs, face), 0.5)
        self.assertEqual(gameplay_check.face_frames(imgs, lambda p: []), 0.0)


class BestOnlyTest(unittest.TestCase):
    def test_keeps_best_three_recent(self):
        import update_index
        now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        iso = lambda h: (now - timedelta(hours=h)).isoformat()
        idx = {f"c{i}.mp4": {"file": f"c{i}.mp4", "quality": q, "score": 0, "added": iso(h)}
               for i, (q, h) in enumerate([(2.0, 1), (5.0, 2), (3.0, 3), (9.0, 40), (4.0, 5)])}
        kept, drop = update_index.best_only(idx, 3, 24, now)
        self.assertEqual(sorted(kept), ["c1.mp4", "c2.mp4", "c4.mp4"])  # c3 ist alt (40 h), trotz 9.0
        self.assertEqual(sorted(drop), ["c0.mp4", "c3.mp4"])

    def test_fills_with_newest_when_few_recent(self):
        import update_index
        now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        idx = {"a.mp4": {"file": "a.mp4", "added": (now - timedelta(hours=50)).isoformat()},
               "b.mp4": {"file": "b.mp4", "added": (now - timedelta(hours=30)).isoformat()},
               "c.mp4": {"file": "c.mp4", "added": (now - timedelta(hours=60)).isoformat()},
               "d.mp4": {"file": "d.mp4", "added": (now - timedelta(hours=70)).isoformat()}}
        kept, drop = update_index.best_only(idx, 3, 24, now)
        self.assertEqual(sorted(kept), ["a.mp4", "b.mp4", "c.mp4"])
        self.assertEqual(drop, ["d.mp4"])


if __name__ == "__main__":
    unittest.main()


class HookQualityTest(unittest.TestCase):
    def test_banal_and_unsure_hooks_rejected(self):
        import captions
        captions.PROBS.clear()
        for txt in ("ok. how you doing?", "yeah. i'll do my best."):
            words = [(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate(txt.split())]
            self.assertEqual(captions.quote_hook(words, 1.0), "", txt)
        words = [(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("ok. it should really burn a holy pocket!".split())]
        for w in words:
            captions.PROBS[(round(w[0], 2), w[2])] = 0.3 if w[2] == "holy" else 0.95
        self.assertEqual(captions.quote_hook(words, 1.0), "")
        captions.PROBS.clear()

    def test_good_hook_kept(self):
        import captions
        captions.PROBS.clear()
        words = [(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("okay. no way you did that bro?".split())]
        self.assertEqual(captions.quote_hook(words, 1.0), "NO WAY YOU DID THAT BRO?")


class BrightnessTest(unittest.TestCase):
    def test_dark_rejected(self):
        import tempfile, gameplay_check
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            ps = []
            for i, v in enumerate((20, 30, 25)):
                p = Path(t) / f"{i}.png"; Image.new("L", (10, 10), v).save(p); ps.append(p)
            self.assertLess(gameplay_check.brightness(ps), gameplay_check.MIN_BRIGHT)
