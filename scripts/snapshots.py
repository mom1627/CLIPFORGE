#!/usr/bin/env python3
"""Ein Standbild je live Streamer (zur Festlegung der Facecam-Position), Upload ins Release 'debug'."""
import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_capture as lc
out = Path("snaps"); out.mkdir(exist_ok=True)
for c in lc.channels():
    if not lc.available(c):
        print("offline:", c); continue
    f = out / f"snap_{c}.jpg"
    r = subprocess.run(f"streamlink --stdout --twitch-disable-ads https://www.twitch.tv/{c} best | timeout 40 ffmpeg -loglevel error -y -i pipe:0 -ss 12 -frames:v 1 {f}", shell=True, capture_output=True, text=True)
    print("snap", c, f.exists())
    if f.exists():
        subprocess.run(["gh", "release", "upload", "debug", str(f), "--clobber", "-R", os.environ["GITHUB_REPOSITORY"]])
