"""FFmpeg end-to-end smoke test using generated color bars, not Twitch media."""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import os

spec=importlib.util.spec_from_file_location("clip_capture", pathlib.Path(__file__).resolve().parents[1]/"scripts"/"live_capture.py")
capture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class RenderingSmokeTest(unittest.TestCase):
    def test_mp4_portrait_render(self):
        with tempfile.TemporaryDirectory() as directory:
            raw=pathlib.Path(directory)/"sample.mkv"
            mp4=pathlib.Path(directory)/"clip.mp4"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=640x360:rate=15",
                "-f","lavfi","-i","sine=frequency=500:sample_rate=44100",
                "-t","3","-c:v","mpeg4","-q:v","8","-c:a","aac",str(raw)],check=True,timeout=30)
            with patch.dict(os.environ,{"VIDEO_WIDTH":"360"}):
                capture.render_vertical(raw,mp4,0,2,3)
            self.assertGreater(mp4.stat().st_size,10000)
            result=subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                "-show_entries","stream=width,height","-of","json",str(mp4)],
                capture_output=True,text=True,check=True)
            meta=json.loads(result.stdout)["streams"][0]
            self.assertEqual((meta["width"],meta["height"]),(360,640))

if __name__ == "__main__":
    unittest.main()
