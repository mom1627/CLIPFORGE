#!/usr/bin/env python3
"""CLIPFORGE VOD-Clips: laedt die neuesten Twitch-VODs freigegebener Streamer (Audio zuerst),
findet die lautesten Momente, schneidet je Moment genau 60 s, rendert 9:16 (Facecam oben/Gameplay unten),
brennt Hook + Whisper-Untertitel ein und haengt die MP4s ans Release 'clips'."""
from __future__ import annotations
import json, math, os, subprocess, sys, array
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_capture as lc, captions, monitor

OUT = Path(os.getenv("CLIPFORGE_OUTPUT", "output")); OUT.mkdir(parents=True, exist_ok=True)


def sh(cmd, timeout=3600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def list_vods(channel: str, n: int, title_filter: str):
    r = sh(["yt-dlp", "--flat-playlist", "--playlist-end", "12", "--print", "%(id)s|%(duration)s|%(title)s",
            f"https://www.twitch.tv/{channel}/videos?filter=archives&sort=time"], timeout=120)
    out = []
    for line in r.stdout.splitlines():
        p = line.split("|", 2)
        if len(p) == 3 and (not title_filter or title_filter.lower() in p[2].lower()):
            out.append((p[0], p[2]))
    if r.returncode and not out:
        print(f"{channel}: VOD-Liste nicht lesbar: {r.stderr[-200:]}")
    return out[:n]


def audio_levels(vod_url: str, path: Path):
    r = sh(["yt-dlp", "-f", "Audio_Only/worstaudio/worst", "-o", str(path), "--no-part", vod_url], timeout=3000)
    if r.returncode or not path.exists():
        print("Audio-Download fehlgeschlagen:", r.stderr[-300:]); return None
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], stdout=subprocess.PIPE)
    vals = []
    while True:
        b = p.stdout.read(16000)
        if len(b) < 16000: break
        a = array.array("h"); a.frombytes(b)
        rms = (sum(x * x for x in a) / len(a)) ** 0.5
        vals.append(20 * math.log10(max(rms, 1.0) / 32768))
    p.wait(); return vals


def main() -> int:
    chans = lc.channels(); per = int(os.getenv("VODS_PER_STREAMER", "1")); tf = os.getenv("TITLE_FILTER", "gta")
    max_clips = int(os.getenv("MAX_CLIPS", "5")); pre = int(os.getenv("PRE_SECONDS", "38")); made = []
    cams = json.loads((Path(__file__).resolve().parent.parent / "config/cams.json").read_text())
    for ch in chans:
        for vid, title in list_vods(ch, per, tf):
            if len(made) >= max_clips: break
            url = f"https://www.twitch.tv/videos/{vid}"
            print(f"VOD {ch} {vid}: {title}", flush=True)
            vals = audio_levels(url, OUT / f"a_{vid}.m4a")
            if not vals: continue
            det = monitor.Detector(spike_db=float(os.getenv("SPIKE_DB", "6")), min_gap=int(os.getenv("MIN_GAP", "150")))
            hits = det.feed(vals)
            # lauteste zuerst
            win = monitor.env_f("WINDOW_SECONDS", 8)
            hits.sort(key=lambda e: -sum(vals[e - int(win):e]) / win)
            print(f"{len(vals)//60} min Audio, {len(hits)} Highlights", flush=True)
            for end in hits:
                if len(made) >= max_clips: break
                start = max(0, end - int(win) - pre)
                raw = OUT / f"raw_{vid}_{start}.mp4"
                r = sh(["yt-dlp", "-f", "best[height<=720]/best", "--download-sections", f"*{start}-{start+62}", "--force-keyframes-at-cuts",
                        "-o", str(raw), url], timeout=900)
                if r.returncode or not raw.exists():
                    print("Ausschnitt fehlgeschlagen:", r.stderr[-300:]); continue
                dest = OUT / f"clipforge_{ch}_vod{vid}_{start}s.mp4"
                os.environ["CAM_BOX"] = ",".join(str(v) for v in cams.get(ch, cams["default"]))
                dur = lc.probe_duration(raw)
                lc.render_vertical(raw, dest, 0.0, monitor.CLIP_LEN, dur + 5)
                raw.unlink(missing_ok=True)
                dest = captions.add_captions(dest, ch, f"{vid}{start}")
                ok = monitor.publish(dest)
                made.append({"file": dest.name, "channel": ch, "vod": url, "start_s": start, "title": title, "published": ok})
                print(f"MP4 fertig: {dest.name} (veroeffentlicht={ok})", flush=True)
            (OUT / f"a_{vid}.m4a").unlink(missing_ok=True)
    (OUT / "vod_report.json").write_text(json.dumps(made, ensure_ascii=False, indent=2))
    print(f"{len(made)} Clips erzeugt")
    return 0 if made else 2


if __name__ == "__main__":
    sys.exit(main())
