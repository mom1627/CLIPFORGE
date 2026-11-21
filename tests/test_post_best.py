"""Beste Clips am Laufende posten: Auswahl nach Punktzahl, nur 60-s-Clips, Abstand zwischen Posts."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import post_best, publisher, safety


def make_mp4(path: Path, seconds: int):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x112:r=5:d={seconds}",
                    "-f", "lavfi", "-i", f"anullsrc=r=8000:cl=mono", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)], check=True)


class SlotTest(unittest.TestCase):
    def test_next_best_slots_berlin(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime(2026, 11, 21, 22, 30, tzinfo=ZoneInfo("Europe/Berlin"))
        d = post_best.slot_delays(5, now=now, slots="10,12,16,18,20", tz="Europe/Berlin")
        # morgen 10, 12, 16, 18, 20 Uhr
        self.assertEqual(d, [690, 810, 1050, 1170, 1290])

    def test_same_day_and_skip_too_close(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime(2026, 11, 21, 11, 57, tzinfo=ZoneInfo("Europe/Berlin"))
        d = post_best.slot_delays(2, now=now, slots="10,12,16", tz="Europe/Berlin")
        self.assertEqual(d, [243, 1323])  # 12:00 nur 3 min weg -> 16:00, dann morgen 10:00

    def test_empty_slots_old_gap_mode(self):
        self.assertEqual(post_best.slot_delays(3, slots="", gap=60), [3, 63, 123])


class PostBestTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.out = Path(self.t.name)
        clips = []
        for i, (sec, score) in enumerate([(60, 9.1), (60, 14.0), (50, 30.0), (60, 7.5), (60, 11.2), (60, 8.0), (60, 12.9)]):
            name = f"c{i}.mp4"; make_mp4(self.out / name, sec)
            clips.append({"file": name, "channel": "trymacs", "score": score, "posted": ""})
        (self.out / "monitor_report.json").write_text(json.dumps({"clips": clips}))
        self.env = mock.patch.dict(os.environ, {"CLIPFORGE_OUTPUT": str(self.out), "POST_BEST": "5", "MAX_POSTS": "5",
                                                "POST_GAP_MINUTES": "60", "POST_SLOTS": "", "AUTO_PUBLISH": "1", "BUFFER_API_KEY": "x",
                                                "CLOUDINARY_CLOUD_NAME": "x", "CLOUDINARY_UPLOAD_PRESET": "x"})
        self.env.start()
        self.safe = mock.patch.object(safety, "check", return_value=(True, "ok")); self.safe.start()

    def tearDown(self):
        self.safe.stop(); self.env.stop(); self.t.cleanup()

    def test_posts_top5_by_score_skips_50s_clip_with_gap(self):
        calls = []
        def fake(video, caption, dry_run=False, delay_minutes=3):
            calls.append((video.name, delay_minutes)); return {"post_id": f"p{len(calls)}", "due": "x"}
        with mock.patch.object(publisher, "publish", side_effect=fake):
            self.assertEqual(post_best.main(), 0)
        self.assertEqual([c[0] for c in calls], ["c1.mp4", "c6.mp4", "c4.mp4", "c0.mp4", "c5.mp4"])  # c2 (50 s) fehlt
        self.assertEqual([c[1] for c in calls], [3, 63, 123, 183, 243])
        rep = json.loads((self.out / "monitor_report.json").read_text())
        self.assertEqual(sum(1 for c in rep["clips"] if c["posted"]), 5)
        # zweiter Aufruf: MAX_POSTS (5) pro Lauf schon erreicht -> nichts mehr, nichts doppelt
        calls.clear()
        with mock.patch.object(publisher, "publish", side_effect=fake):
            post_best.main()
        self.assertEqual(calls, [])

    def test_unsafe_clip_skipped_next_one_moves_up(self):
        self.safe.stop()
        bad = lambda p: (p.name != "c1.mp4", "Nacktheit erkannt")
        clips = json.loads((self.out / "monitor_report.json").read_text())["clips"]
        best = post_best.pick_best(clips, self.out, 5, check=bad)
        self.assertEqual([c["file"] for c in best], ["c6.mp4", "c4.mp4", "c0.mp4", "c5.mp4", "c3.mp4"])
        self.assertEqual(clips[1]["unsafe"], "Nacktheit erkannt")
        self.safe.start()

    def test_post_now_respects_gap_and_max(self):
        calls = []
        def fake(video, caption, dry_run=False, delay_minutes=3):
            calls.append(delay_minutes); return {"post_id": f"p{len(calls)}", "due": "x"}
        os.environ["MAX_POSTS"] = "2"
        rep = json.loads((self.out / "monitor_report.json").read_text())
        with mock.patch.object(publisher, "publish", side_effect=fake):
            self.assertIn("geplant in 3 min", post_best.post_now(rep["clips"][0], self.out, rep, now=1000.0))
            # 10 min später: nächster Post erst 60 min nach dem ersten
            self.assertIn("geplant in 53 min", post_best.post_now(rep["clips"][1], self.out, rep, now=1600.0))
            self.assertIn("MAX_POSTS", post_best.post_now(rep["clips"][3], self.out, rep, now=1700.0))
        self.assertEqual(calls, [3, 53])

    def test_post_now_skips_50s_clip(self):
        rep = json.loads((self.out / "monitor_report.json").read_text())
        with mock.patch.object(publisher, "publish") as pub:
            self.assertIn("nicht 60 s", post_best.post_now(rep["clips"][2], self.out, rep, now=1000.0))
            pub.assert_not_called()

    def test_preview_only_without_auto_publish(self):
        os.environ["AUTO_PUBLISH"] = "0"
        with mock.patch.object(publisher, "publish") as pub:
            self.assertEqual(post_best.main(), 0)
            pub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
