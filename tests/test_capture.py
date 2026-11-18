"""Offline tests for the free GitHub Actions pipeline."""
import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("live_capture", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "live_capture.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CaptureTest(unittest.TestCase):
    def test_validation_of_licensed_channel_list(self):
        with patch.dict(os.environ, {"APPROVED_CHANNELS": "xqc,Trymacs,xqc"}):
            self.assertEqual(module.channels(), ["xqc", "trymacs"])
        with patch.dict(os.environ, {"APPROVED_CHANNELS": "xqc;rm -rf /"}):
            with self.assertRaises(ValueError):
                module.channels()
        with patch.dict(os.environ, {"APPROVED_CHANNELS": ""}):
            with self.assertRaises(RuntimeError):
                module.channels()

    def test_safe_time_limits(self):
        with patch.dict(os.environ, {"CAPTURE_SECONDS": "900", "CLIP_SECONDS": "70"}):
            self.assertEqual(module.env_int("CAPTURE_SECONDS", 100, 45, 130), 130)
            self.assertEqual(module.env_int("CLIP_SECONDS", 40, 15, 60), 60)

    def test_high_energy_window_is_selected(self):
        with patch.object(module, "audio_score", side_effect=[-40,-35,-12,-30,-33]):
            start, score = module.choose_start(pathlib.Path("dummy.mkv"), 100, 30)
        self.assertAlmostEqual(start, 34.8, places=1)
        self.assertEqual(score, -12)

    def test_no_reencode_beyond_source(self):
        with patch.object(module, "audio_score", return_value=-25.0):
            start, _ = module.choose_start(pathlib.Path("dummy.mkv"), 29, 40)
        self.assertEqual(start, 0.0)

    def test_tiktok_requires_token_and_does_not_publish_directly(self):
        with patch.dict(os.environ, {"TIKTOK_ACCESS_TOKEN": "", "TIKTOK_UPLOAD_MODE": "draft"}):
            self.assertFalse(os.environ["TIKTOK_ACCESS_TOKEN"])
        # The only publishing API URL in the uploader is the official inbox endpoint.
        import inspect
        body = inspect.getsource(module.tiktok_draft)
        self.assertIn("/inbox/video/init/", body)
        self.assertNotIn("/publish/video/init/", body)

if __name__ == "__main__":
    unittest.main()
