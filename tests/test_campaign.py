"""Kampagne: Logo im Overlay, Pflicht-Hashtags in der Beschreibung, Spiel-Vorgabe."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import campaign, captions, publisher


class CampaignTest(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.t = tempfile.TemporaryDirectory(); d = Path(self.t.name)
        Image.new("RGBA", (200, 100), (0, 200, 0, 255)).save(d / "logo.png")
        (d / "c.json").write_text(json.dumps({"active": True, "logo": str(d / "logo.png"), "logo_pos": "top-right",
                                              "logo_width": 0.2, "hashtags": "#clipup #gta6", "game": "Grand Theft Auto VI"}))
        self.env = mock.patch.dict(os.environ, {"CAMPAIGN_FILE": str(d / "c.json")}); self.env.start()

    def tearDown(self):
        self.env.stop(); self.t.cleanup()

    def test_logo_in_every_overlay_frame(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            lst = captions.build_overlay_frames([(1, 1.5, "hey"), (3, 3.5, "wow")], "X ?!", 720, 1280, 10.0, Path(t) / "ov",
                                                split=True, quote="", style="box")
            pngs = sorted((Path(t) / "ov").glob("o*.png"))
            self.assertGreaterEqual(len(pngs), 2)
            for p in pngs:  # Logo oben rechts: grünes Pixel
                self.assertEqual(Image.open(p).convert("RGBA").getpixel((720 - 30 - 60, 30 + 10))[:3], (0, 200, 0))

    def test_required_hashtags_first_and_not_doubled(self):
        cap = publisher.build_caption("lacy", "Hook", tags="#gta6 #fyp")
        tags = cap.split("\n\n")[-1].split()
        self.assertEqual(tags[0], "#clipup")
        self.assertEqual(tags.count("#gta6"), 1)

    def test_game_and_inactive(self):
        self.assertEqual(campaign.game(), "Grand Theft Auto VI")
        Path(os.environ["CAMPAIGN_FILE"]).write_text(json.dumps({"active": False, "hashtags": "#clipup"}))
        self.assertEqual(campaign.hashtags(), ""); self.assertIsNone(campaign.logo_path())


if __name__ == "__main__":
    unittest.main()
