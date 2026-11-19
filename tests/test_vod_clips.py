"""Offline tests for CLIPFORGE VOD extension. No Twitch/YouTube credentials or real recordings."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import vod_clips as vc
import captions
import live_capture as lc


class AllowlistTests(unittest.TestCase):
    def test_existing_allowlist_enforced(self):
        with patch.dict(os.environ, {"APPROVED_CHANNELS": "xqc,papaplatte"}):
            self.assertEqual(vc.allowed_channels("xqc,papaplatte"), ["xqc", "papaplatte"])
            with self.assertRaises(PermissionError):
                vc.allowed_channels("xqc,kaicenat")
            self.assertEqual(vc.allowed_channels(""), ["xqc", "papaplatte"])

    def test_missing_approved_channels_fails_closed(self):
        with patch.dict(os.environ, {"APPROVED_CHANNELS": ""}):
            with self.assertRaises(RuntimeError):
                vc.allowed_channels("xqc")

    def test_unsafe_name_rejected(self):
        with patch.dict(os.environ, {"APPROVED_CHANNELS": "xqc"}):
            with self.assertRaises(ValueError):
                vc.allowed_channels("xqc;exit 0")


class VODListingTests(unittest.TestCase):
    def test_duration_parser(self):
        self.assertEqual(vc.seconds_from_duration("3h0m5s"), 10805)
        self.assertEqual(vc.seconds_from_duration("47m16s"), 2836)
        self.assertEqual(vc.seconds_from_duration("45s"), 45)
        self.assertEqual(vc.seconds_from_duration(""), 0)

    def test_archive_filtered_by_ending_after_cutoff(self):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=5)).isoformat()
        fake = [
            {"id": "12345", "title": "GTA VI", "created_at": start, "duration": "4h30m0s"},
            {"id": "12346", "title": "Old", "created_at": (now - timedelta(days=5)).isoformat(), "duration": "1h0m0s"}
        ]
        def api(endpoint, params, token):
            if endpoint == "users":
                return {"data": [{"id": "98"}]}
            self.assertEqual(params["type"], "archive")
            return {"data": fake}
        with patch.object(vc, "helix_get", side_effect=api):
            latest = vc.list_recent_vods("xqc", "test", now-timedelta(hours=1), 5, "")
        self.assertEqual([x["id"] for x in latest], ["12345"])

    def test_sampled_windows_cover_start_and_end(self):
        windows = vc.scan_windows(7200, 300, 3)
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0], (0, 300))
        self.assertEqual(windows[-1], (6900, 7200))
        self.assertEqual(sum(b-a for a,b in windows), 900)


class RankingTests(unittest.TestCase):
    def test_rising_audio_scores_higher_than_baseline(self):
        values = [-42.0] * 100 + [-16.0] * 8
        self.assertGreater(vc.score_event(values, len(values)), 20.0)

    def test_minimum_two_minute_gap_and_per_vod_limit(self):
        C = vc.Candidate
        rows = [
            C("xqc","123",20,60,12,12,0,"title"),
            C("xqc","123",90,150,11,11,0,"title"),
            C("xqc","123",250,290,10,10,0,"title"),
            C("xqc","123",470,510,8,8,0,"title"),
            C("trymacs","999",70,100,9,9,0,"title")
        ]
        chosen = vc.top_candidates(rows, 5, min_gap=120, per_vod=2)
        self.assertEqual([x.peak_s for x in chosen], [60, 290, 100])

    def test_hook_is_literal_spoken_words_not_template(self):
        words = [(i*0.3, i*0.3+0.2, w) for i,w in enumerate(
            ["No", "way!", "Did", "you", "see", "that?", "This", "is", "crazy!", "really"])]
        hook = vc.hook_from_speech(words)
        full = " ".join(w[2] for w in words)
        self.assertIn(hook, full)
        self.assertLessEqual(len(hook.split()), 8)
        with self.assertRaises(RuntimeError):
            vc.hook_from_speech([])

    def test_chat_peak_bonus_when_replay_available(self):
        offsets = list(range(0,180,20)) + [100]*40
        self.assertGreater(vc.chat_bonus(sorted(offsets),100),0)
        self.assertEqual(vc.chat_bonus([],100),0)


class LayoutAndVerificationTests(unittest.TestCase):
    def test_caption_positions_seam(self):
        ass = captions.build_ass([(0.1,0.3,"Hallo")],"HALLO",720,1280,60,
                split=True,hook_y_override=380,subtitle_y_override=580)
        self.assertIn(r"\pos(360,380)",ass)
        self.assertIn(r"\pos(360,580)",ass)

    def test_four_by_five_gameplay_region(self):
        seen = {}
        with tempfile.TemporaryDirectory() as folder:
            dest = pathlib.Path(folder)/"clip.mp4"
            def fake_run(command, **kw):
                seen["cmd"] = command
                dest.write_bytes(b"a" * 11000)
                return SimpleNamespace(returncode=0,stderr="")
            with patch.dict(os.environ, {"VIDEO_FIT":"split", "GAMEPLAY_ASPECT":"4:5",
                        "VIDEO_WIDTH":"720","CAM_BOX":"0.727,0.60,0.26,0.40"}):
                with patch.object(lc, "run", side_effect=fake_run):
                    lc.render_vertical(pathlib.Path(folder)/"dummy.ts",dest,0,60,70)
        arg = seen["cmd"][seen["cmd"].index("-filter_complex")+1]
        self.assertIn("scale=720:380",arg)
        self.assertIn("scale=720:900",arg)

    def test_ffprobe_rejects_wrong_duration(self):
        bad = {"format":{"duration":"59.40"},"streams":[
            {"codec_type":"video","codec_name":"h264","width":720,"height":1280,
             "nb_read_frames":"1800","avg_frame_rate":"30/1"},
            {"codec_type":"audio","codec_name":"aac"}]}
        with patch.object(vc,"cmd",return_value=SimpleNamespace(stdout=json.dumps(bad))):
            with self.assertRaises(RuntimeError):
                vc.verify_mp4(pathlib.Path("x.mp4"),720,1280)

    def test_ffprobe_accepts_real_spec_only(self):
        correct={"format":{"duration":"60.000"},"streams":[
            {"codec_type":"video","codec_name":"h264","width":720,"height":1280,
             "nb_read_frames":"1800","avg_frame_rate":"30/1"},
            {"codec_type":"audio","codec_name":"aac"}]}
        with patch.object(vc,"cmd",return_value=SimpleNamespace(stdout=json.dumps(correct))):
            info=vc.verify_mp4(pathlib.Path("clip.mp4"),720,1280)
        self.assertEqual(info["frames"],1800)


if __name__ == "__main__":
    unittest.main()
