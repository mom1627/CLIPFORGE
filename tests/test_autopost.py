"""Auto-Posten: Tageslimit (rollierend 24 h), Mindestabstand, stärkster Clip zuerst, Schlüssel speichern."""
import json, os, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app")); sys.path.insert(0, str(ROOT / "scripts"))
import manager, publisher  # noqa: E402


class AutoPostTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); home = Path(self.t.name)
        self.m = manager.Manager(home=home)
        self.m.cfg.update(auto_publish=True, max_posts_per_day=2, post_gap_minutes=60)
        self.posted = []
        self.m.publish = lambda name, caption=None: (self.posted.append(name),
                                                     self.m._set_meta(name, posted_at=time.strftime("%Y-%m-%d %H:%M")))
        self.orig = publisher.configured; manager.publisher.configured = lambda: True

    def tearDown(self):
        manager.publisher.configured = self.orig; self.t.cleanup()

    def clip(self, name, strength):
        (self.m.clips_dir / name).write_bytes(b"x")
        (self.m.clips_dir / name).with_suffix(".json").write_text(json.dumps({"file": name, "strength": strength}))

    def test_best_first_gap_and_limit(self):
        self.clip("a.mp4", 2.0); self.clip("b.mp4", 5.0); self.clip("c.mp4", 3.0)
        self.m._auto_post_tick(); self.assertEqual(self.posted, ["b.mp4"])
        self.m._auto_post_tick(); self.assertEqual(self.posted, ["b.mp4"])          # Abstand 60 min
        self.m.cfg["post_gap_minutes"] = 0
        self.m._auto_post_tick(); self.assertEqual(self.posted, ["b.mp4", "c.mp4"])
        self.m._auto_post_tick(); self.assertEqual(self.posted, ["b.mp4", "c.mp4"])  # Limit 2

    def test_set_publisher_writes_env_without_echo(self):
        envf = self.m.home / ".env"; envf.write_text("TWITCH_CLIENT_ID=abc\nBUFFER_API_KEY=\n")
        manager.publisher.configured = self.orig
        for k in ("BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET"):
            os.environ.pop(k, None)
        orig_ch = publisher.tiktok_channel; manager.publisher.tiktok_channel = lambda: "tt9"
        try:
            r = self.m.set_publisher({"buffer_api_key": "buf_x", "cloudinary_cloud_name": "c1",
                                      "cloudinary_upload_preset": "p1"})
        finally:
            manager.publisher.tiktok_channel = orig_ch
            for k in ("BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET"):
                os.environ.pop(k, None)
        self.assertTrue(r["ok"]); self.assertNotIn("buf_x", json.dumps(r))
        txt = envf.read_text()
        self.assertIn("TWITCH_CLIENT_ID=abc", txt); self.assertIn("BUFFER_API_KEY=buf_x", txt)
        self.assertEqual(txt.count("BUFFER_API_KEY="), 1)
        with self.assertRaises(ValueError):
            self.m.set_publisher({"buffer_api_key": "a\nB=1"})


if __name__ == "__main__":
    unittest.main()
