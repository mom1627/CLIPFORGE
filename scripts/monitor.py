#!/usr/bin/env python3
"""CLIPFORGE Monitor: watches approved public Twitch streams for up to MONITOR_MINUTES,
records continuously in short segments, detects loud/exciting moments (audio spikes versus
a rolling baseline) WHILE the stream is live, renders each as a vertical 9:16 MP4 and
publishes it as a GitHub Release asset (downloadable on the iPhone).

Only Streamlink (public streams) + FFmpeg. No Twitch clip API, no private streams.
"""
from __future__ import annotations
import array, json, os, shutil, statistics, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_capture as lc
import post_best
import captions  # reuse channel allowlist, availability check, game check, renderer

SEG = 30  # seconds per recorded segment


def env_f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


class Detector:
    """Per-second loudness (dB) -> highlight end-times. Pure logic, unit-testable."""
    def __init__(self, spike_db=7.0, floor_db=-38.0, window=8, min_gap=120, baseline_s=300, warmup=60):
        self.db, self.spike, self.floor, self.w = [], spike_db, floor_db, window
        self.gap, self.base_s, self.warm, self.last = min_gap, baseline_s, warmup, -10**9
        self.strength = {}  # Treffer-Sekunde -> dB über dem normalen Pegel (für "beste Clips")

    def feed(self, values):
        """Append per-second dB values; return list of window-end seconds that are highlights."""
        hits = []
        for v in values:
            self.db.append(v)
            n = len(self.db)
            if n < self.warm or n < self.w:
                continue
            base = statistics.median(self.db[max(0, n - self.base_s - self.w):n - self.w])
            mean = sum(self.db[n - self.w:n]) / self.w
            if mean > base + self.spike and mean > self.floor and n - self.last >= self.gap:
                # extend to the loudest point of this burst: wait until it stops rising
                self.last = n
                self.strength[n] = round(mean - base, 2)
                hits.append(n)
        return hits


def per_second_db(path: Path) -> list[float]:
    """RMS dB for each second of a segment, via 8 kHz mono PCM piped from FFmpeg."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn",
                        "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, timeout=60)
    a = array.array("h"); a.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    out = []
    for i in range(0, len(a) - 7999, 8000):
        chunk = a[i:i + 8000]
        rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5
        out.append(20 * __import__("math").log10(max(rms, 1.0) / 32768))
    return out


def start_recorder(channel: str, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    src = subprocess.Popen(["streamlink", "--stdout", "--retry-open", "1", "--twitch-disable-ads",
                            f"https://www.twitch.tv/{channel}", "best"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:0",
                           "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-f", "segment",
                           "-segment_time", str(SEG), "-reset_timestamps", "1",
                           str(folder / "seg_%05d.ts")],
                          stdin=src.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    src.stdout.close()
    return src, ff


def stop(*procs):
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()


CLIP_LEN = 60  # Clips sind immer genau 60 s lang


def clip_range(end_s: int, pre: int):
    """Genau CLIP_LEN Sekunden: 'pre' s vor Beginn des Highlight-Fensters, Rest danach."""
    start = max(0, end_s - int(env_f("WINDOW_SECONDS", 8)) - pre)
    return start, start + CLIP_LEN


def clip_offset(dur: float, off: float):
    """Start im zusammengefuegten Material, damit der Clip immer volle CLIP_LEN Sekunden hat.
    Fehlt hinten Material (Luecke), wird der Start nach vorn verschoben; reicht es gar nicht: None."""
    if dur < CLIP_LEN - 0.5:
        return None
    return float(min(off, max(0.0, dur - CLIP_LEN)))


def build_clip(folder: Path, end_s: int, pre: int, post: int, dest_dir: Path, channel: str,
               cam_box: list | None = None, fit: str | None = None):
    """Cut exactly 60 s from consecutive segments and render 9:16."""
    start_abs, stop_abs = clip_range(end_s, pre)
    first, last = start_abs // SEG, (stop_abs - 1) // SEG
    segs = [folder / f"seg_{i:05d}.ts" for i in range(first, last + 1)]
    if not all(s.exists() for s in segs):
        return None
    # Vorheriges Material mitnehmen (falls noch im Puffer), damit bei einer Luecke hinten
    # der Start nach vorn rutschen kann und der Clip trotzdem volle 60 s hat.
    for _ in range(CLIP_LEN // SEG):
        prev = folder / f"seg_{first - 1:05d}.ts"
        if first == 0 or not prev.exists():
            break
        first -= 1
        segs.insert(0, prev)
    lst = folder / "concat.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    joined = folder / f"joined_{end_s}.ts"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(joined)], capture_output=True, text=True, timeout=120)
    if r.returncode:
        return None
    dur = lc.probe_duration(joined)
    off = start_abs - first * SEG
    off = clip_offset(dur, off)
    if off is None:  # Aufnahme zu kurz/Luecke -> kein Clip statt kuerzerem Clip
        joined.unlink(missing_ok=True)
        return None
    length = CLIP_LEN
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"clipforge_{channel}_{stamp}.mp4"
    cams = json.loads(Path(__file__).resolve().parent.parent.joinpath('config/cams.json').read_text())
    box = cam_box or cams.get(channel, cams['default'])
    lc.render_vertical(joined, dest, float(off), length, off + length + 5, cam_box=box, fit=fit)
    joined.unlink(missing_ok=True)
    return dest


def write_report(out: Path, report: dict) -> None:
    (out / "monitor_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


def publish(mp4: Path) -> bool:
    repo, tag = os.getenv("GITHUB_REPOSITORY", ""), os.getenv("RELEASE_TAG", "clips")
    if not repo or not shutil.which("gh"):
        return False
    r = subprocess.run(["gh", "release", "upload", tag, str(mp4), "--clobber", "-R", repo],
                       capture_output=True, text=True, timeout=180)
    if r.returncode:
        print("Release-Upload fehlgeschlagen:", r.stderr[-300:], file=sys.stderr)
    return r.returncode == 0


def main() -> int:
    out = Path(os.getenv("CLIPFORGE_OUTPUT", "output")); out.mkdir(parents=True, exist_ok=True)
    budget = time.time() + env_f("MONITOR_MINUTES", 330) * 60
    pre, post = int(env_f("PRE_SECONDS", 38)), 0
    max_clips = int(env_f("MAX_CLIPS", 12))
    allowed = [g.strip().lower() for g in os.getenv("ALLOWED_GAMES", "*").split(",") if g.strip()]
    import campaign
    if campaign.game():  # aktive Kampagne verlangt ein bestimmtes Spiel (z. B. GTA VI)
        allowed = [campaign.game().lower()]
    channels = lc.channels()
    report = {"started": datetime.now(timezone.utc).isoformat(), "sessions": [], "clips": []}
    clips = 0
    while time.time() < budget and clips < max_clips:
        live = None
        for c in channels:
            if lc.available(c):
                g = lc.twitch_game(c)
                if not lc.game_allowed(g, allowed):
                    continue
                live = c; break
        if not live:
            print("Kein freigegebener Streamer live/passend. Warte 60 s.", flush=True)
            time.sleep(60); continue
        print(f"Live: {live}. Starte Überwachung.", flush=True)
        folder = out / f"rec_{live}"
        if folder.exists():
            shutil.rmtree(folder)
        src, ff = start_recorder(live, folder)
        det, done, pending, session = Detector(spike_db=env_f("SPIKE_DB", 7), min_gap=int(env_f("MIN_GAP", 120))), 0, [], {"channel": live, "clips": 0}
        try:
            while time.time() < budget and clips < max_clips:
                time.sleep(5)
                if ff.poll() is not None:
                    print("Stream beendet/Aufnahme gestoppt.", flush=True); break
                segs = sorted(folder.glob("seg_*.ts"))
                complete = segs[:-1]  # newest file is still being written
                while done < len(complete):
                    vals = per_second_db(complete[done]); done += 1
                    for end in det.feed(vals):
                        pending.append(end)
                        print(f"Highlight erkannt bei {end}s.", flush=True)
                recorded = done * SEG
                for end in list(pending):
                    if recorded >= clip_range(end, pre)[1]:
                        pending.remove(end)
                        mp4 = build_clip(folder, end, pre, post, out, live)
                        if mp4:
                            if os.getenv("CAPTIONS", "1") == "1":
                                mp4 = captions.add_captions(mp4, live, str(end))
                            clips += 1; session["clips"] += 1
                            ok = publish(mp4)
                            report["clips"].append({"file": mp4.name, "channel": live, "second": end,
                                                    "score": det.strength.get(end, 0.0),
                                                    "bytes": mp4.stat().st_size, "published": ok, "posted": ""})
                            if os.getenv("POST_MODE", "end") == "now":
                                status = post_best.post_now(report["clips"][-1], out, report)
                                print(f"Sofort-Post {mp4.name}: {status}", flush=True)
                            write_report(out, report)  # laufend, damit "Beste Clips posten" auch nach Abbruch arbeitet
                            print(f"MP4 fertig: {mp4.name} (veröffentlicht={ok})", flush=True)
                for old in segs[:max(0, done - 12)]:  # rolling buffer ~6 min
                    old.unlink(missing_ok=True)
        finally:
            stop(ff, src)
            shutil.rmtree(folder, ignore_errors=True)
        report["sessions"].append(session)
        time.sleep(20)
    report["finished"] = datetime.now(timezone.utc).isoformat()
    write_report(out, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
