#!/usr/bin/env python3
"""CLIPFORGE VOD batch. Reuses the live monitor's detector, renderer and captions.

Only public VOD archives of allowlisted channels. Does not bypass subscriber,
deleted or access-restricted recordings. Bounded sampling is explicitly reported.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import captions
import live_capture as lc
import chat_probe
import monitor

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.getenv("CLIPFORGE_OUTPUT", "output"))
RELEASE = os.getenv("RELEASE_TAG", "clips")


def bounded_int(key: str, default: int, low: int, high: int) -> int:
    try:
        n = int(os.getenv(key, str(default)))
    except ValueError:
        n = default
    return max(low, min(n, high))


def stamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_error(text: str) -> str:
    # Preserve the actionable error without leaking signed CDN URLs or tokens.
    value = (text or "").splitlines()
    value = value[-1] if value else "unbekannter Fehler"
    value = re.sub(r"https?://\S+", "[URL]", value)
    value = re.sub(r"(?i)(authorization|client_secret|access_token|refresh_token|token)\s*[:=]\s*\S+",
                   r"\1=[geschuetzt]", value)
    return value[:350]


def cmd(args: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Zeitlimit bei " + args[0]) from exc
    if result.returncode and check:
        raise RuntimeError(f"{args[0]} Exit {result.returncode}: {clean_error(result.stderr)}")
    return result


def allowed_channels(requested: str) -> list[str]:
    approved = lc.channels()
    if not requested.strip():
        return approved
    names = []
    for raw in requested.split(","):
        name = raw.strip().lower().lstrip("@")
        if not re.fullmatch(r"[a-z0-9_]{3,25}", name):
            raise ValueError("Ungueltiger angeforderter Streamer: " + repr(name))
        if name not in approved:
            raise PermissionError("Streamer nicht in APPROVED_CHANNELS: " + name)
        if name not in names:
            names.append(name)
    return names


def seconds_from_duration(value: str) -> int:
    parts = re.findall(r"(\d+)([hms])", value or "")
    if not parts:
        return 0
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[unit] for n, unit in parts)


def utc_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def helix_token() -> str:
    client = os.getenv("TWITCH_CLIENT_ID", "").strip()
    secret = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
    if not client or not secret:
        raise RuntimeError("TWITCH_CLIENT_ID und TWITCH_CLIENT_SECRET fehlen als GitHub-Secrets")
    data = urllib.parse.urlencode({"client_id": client, "client_secret": secret,
                                   "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Twitch OAuth HTTP " + str(exc.code)) from None
    if not payload.get("access_token"):
        raise RuntimeError("Twitch hat kein OAuth-Zugriffstoken geliefert")
    return payload["access_token"]


def helix_get(endpoint: str, params: dict, token: str) -> dict:
    query = urllib.parse.urlencode(params)
    url = "https://api.twitch.tv/helix/" + endpoint + "?" + query
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Client-Id": os.environ["TWITCH_CLIENT_ID"]
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Twitch Helix {endpoint} HTTP {exc.code}") from None


def list_recent_vods(channel: str, token: str, cutoff: datetime, limit: int,
                     title_filter: str) -> list[dict]:
    users = helix_get("users", {"login": channel}, token).get("data", [])
    if not users:
        raise RuntimeError("Streamer-Konto bei Twitch nicht gefunden")
    result = helix_get("videos", {"user_id": users[0]["id"], "type": "archive",
                                  "sort": "time", "first": 30}, token)
    vods = []
    for row in result.get("data", []):
        try:
            started = utc_time(row["created_at"])
            duration = seconds_from_duration(row.get("duration", ""))
            ended = started + timedelta(seconds=duration)
            title = row.get("title", "")
            vod_id = str(row["id"])
            if not vod_id.isdecimal() or duration < 61:
                continue
            if ended < cutoff:
                continue
            if title_filter and title_filter.lower() not in title.lower():
                continue
            vods.append({"channel": channel, "id": vod_id,
                         "url": "https://www.twitch.tv/videos/" + vod_id,
                         "created_at": started.isoformat(),
                         "duration": duration, "title": title,
                         "game_id": row.get("game_id", "")})
        except (KeyError, ValueError, TypeError):
            continue
    return vods[:limit]


def scan_windows(length: int, seconds: int, count: int) -> list[tuple[int, int]]:
    """Bounded windows across the whole VOD; coverage is reported, not overstated."""
    if length <= 60:
        return []
    seconds = min(seconds, length)
    if length <= seconds:
        return [(0, length)]
    starts = [round((length - seconds) * i / (count - 1))
              for i in range(count)] if count > 1 else [0]
    unique = sorted(set(max(0, min(length - seconds, int(x))) for x in starts))
    return [(s, s + seconds) for s in unique]


def vod_section(vod: dict, begin: int, end: int, folder: Path,
                label: str, high_quality: bool = False) -> Path:
    if begin < 0 or end <= begin:
        raise ValueError("Ungueltiger VOD-Zeitbereich")
    fmt = "best[height<=720]/best" if high_quality else "worst[height<=480]/worst"
    prefix = folder / label
    args = ["yt-dlp", "--no-playlist", "--ignore-config", "--no-progress",
            "--no-warnings", "--retries", "1", "--fragment-retries", "1",
            "--socket-timeout", "25", "-f", fmt,
            "--download-sections", f"*{begin}-{end}",
            "--merge-output-format", "mp4", "-o", str(prefix) + ".%(ext)s"]
    if high_quality:
        args += ["--force-keyframes-at-cuts"]
    cmd(args + [vod["url"]], timeout=720 if high_quality else 480)
    matches = [p for p in folder.glob(label + ".*") if p.suffix in (".mp4", ".mkv", ".webm", ".ts")]
    if not matches:
        raise RuntimeError("yt-dlp beendete sich ohne auswertbare Videodatei")
    return sorted(matches, key=lambda p: p.stat().st_size, reverse=True)[0]


def score_event(db_levels: list[float], end: int, window: int = 8) -> float:
    if end < window or end > len(db_levels):
        return -1e6
    prior = db_levels[max(0, end - 300 - window):end-window]
    if not prior:
        return -1e6
    peak = statistics.mean(db_levels[end-window:end])
    baseline = statistics.median(prior)
    return round(peak - baseline, 2)


def chat_offsets(path: Path) -> list[float]:
    """Optional imported VOD chat replay (Twitch has no standard public Helix replay API)."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw.get("comments", []) if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            return []
        found = []
        for message in records:
            if not isinstance(message, dict):
                continue
            point = message.get("content_offset_seconds", message.get("offset_seconds"))
            if point is not None and isinstance(point, (int, float)) and point >= 0:
                found.append(float(point))
        return sorted(found)
    except (ValueError, OSError):
        return []


def chat_bonus(offsets: list[float], position: float) -> float:
    """Score an unusual 10-second chat peak compared with adjacent messages."""
    if not offsets:
        return 0.0
    from bisect import bisect_left, bisect_right
    burst = bisect_right(offsets, position + 5) - bisect_left(offsets, position - 5)
    before = bisect_right(offsets, position - 25) - bisect_left(offsets, position - 125)
    baseline = before / 10
    return round(min(8.0, max(0.0, (burst - baseline) * 0.25)), 2)


@dataclass
class Candidate:
    channel: str
    vod_id: str
    start_s: int
    peak_s: int
    score: float
    audio_peak_db: float
    chat_boost: float
    vod_title: str


def candidates_for_vod(vod: dict, work: Path, scan_count: int, scan_seconds: int,
                       spike: float, chat: list[float], reports: list[dict]) -> list[Candidate]:
    result = []
    windows = scan_windows(vod["duration"], scan_seconds, scan_count)
    for wi, (start, end) in enumerate(windows):
        try:
            source = vod_section(vod, start, end, work, f"scan_{vod['id']}_{wi}")
            levels = monitor.per_second_db(source)  # reuse tested 8 kHz RMS detector
            det = monitor.Detector(spike_db=spike, min_gap=120)
            hits = det.feed(levels)
            for hit in hits:
                at = start + hit
                offset = max(0, min(vod["duration"] - 60, at - 8 - 38))
                score = score_event(levels, hit)
                bonus = chat_bonus(chat, at)
                result.append(Candidate(vod["channel"], vod["id"], int(offset),
                                        int(at), round(score + bonus, 2), score, bonus,
                                        vod["title"]))
            reports.append({"vod": vod["url"], "window": [start, end],
                            "seconds_decoded": len(levels), "detected": len(hits)})
        except Exception as exc:
            reports.append({"vod": vod["url"], "window": [start, end],
                            "error": clean_error(str(exc))})
        finally:
            for file in work.glob(f"scan_{vod['id']}_{wi}.*"):
                file.unlink(missing_ok=True)
    return result


def top_candidates(all_candidates: list[Candidate], max_total: int,
                   min_gap: int = 120, per_vod: int = 2) -> list[Candidate]:
    ordered = sorted(all_candidates, key=lambda x: (-x.score, x.channel, x.vod_id, x.start_s))
    chosen = []
    for item in ordered:
        same = [x for x in chosen if x.vod_id == item.vod_id]
        if len(same) >= per_vod or any(abs(x.peak_s - item.peak_s) < min_gap for x in same):
            continue
        chosen.append(item)
        if len(chosen) >= max_total:
            break
    return chosen


def hook_from_speech(words: list[tuple[float, float, str]]) -> str:
    """Literal contiguous spoken words, at most eight. Never invent a reaction."""
    real = [(float(start), str(word).strip()) for start, end, word in words
            if word and str(word).strip() and 0 <= float(start) <= 50]
    if not real:
        raise RuntimeError("Keine verstaendliche Sprache: kein erfundener Hook")
    # A short real utterance early in the clip, ideally with natural emphasis.
    first = [word for at, word in real if at <= 15]
    if not first:
        first = [word for at, word in real[:8]]
    segments = []
    for offset in range(0, min(len(first), 20), 4):
        phrase = first[offset:offset+8]
        if phrase:
            punctuation = sum(3 for w in phrase if "!" in w or "?" in w)
            segments.append((punctuation + min(len(phrase), 8) / 10, phrase))
    if not segments:
        raise RuntimeError("Keine gesprochenen Woerter fuer den Hook")
    best = max(segments, key=lambda item: item[0])[1]
    return " ".join(best[:8]).strip()


def verify_mp4(video: Path, width: int, height: int) -> dict:
    info = json.loads(cmd(["ffprobe", "-v", "error", "-count_frames",
                           "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,nb_read_frames,avg_frame_rate",
                           "-of", "json", str(video)], timeout=90).stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    streams = info.get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video"), {})
    a = next((x for x in streams if x.get("codec_type") == "audio"), {})
    frames = int(v.get("nb_read_frames") or 0)
    result = {"duration": duration, "width": v.get("width"),
              "height": v.get("height"), "video_codec": v.get("codec_name"),
              "audio_codec": a.get("codec_name"), "frames": frames,
              "frame_rate": v.get("avg_frame_rate")}
    if not (59.95 <= duration <= 60.05 and frames == 1800
            and v.get("width") == width and v.get("height") == height
            and v.get("codec_name") == "h264" and a.get("codec_name") == "aac"
            and v.get("avg_frame_rate") == "30/1"):
        raise RuntimeError("ffprobe-Pruefung fehlgeschlagen: " + json.dumps(result))
    return result


def produce(candidate: Candidate, vod: dict, folder: Path, cams: dict) -> dict:
    dt = utc_time(vod["created_at"]) + timedelta(seconds=candidate.start_s)
    filename = f"{candidate.channel}_{dt:%Y%m%d}_{dt:%H%M%S}.mp4"
    output = OUT / filename
    with tempfile.TemporaryDirectory(prefix="vod_render_") as td:
        tmp = Path(td)
        section_begin = max(0, candidate.start_s - 3)
        section_end = min(vod["duration"], candidate.start_s + 67)
        source = vod_section(vod, section_begin, section_end, tmp,
                             "source", high_quality=True)
        duration = lc.probe_duration(source)
        offset = candidate.start_s - section_begin
        if duration - offset < 59.5:
            raise RuntimeError(f"VOD-Teilstueck zu kurz ({duration-offset:.2f}s); kein verkuerztes Video")
        os.environ["VIDEO_FIT"] = "split"
        os.environ["GAMEPLAY_ASPECT"] = "4:5"
        os.environ["CAM_BOX"] = ",".join(str(x) for x in cams.get(
            candidate.channel, cams["default"]))
        os.environ["VIDEO_WIDTH"] = str(bounded_int("VIDEO_WIDTH", 720, 720, 1080))
        prelim = tmp / "layout.mp4"
        lc.render_vertical(source, prelim, offset, 60, duration)
        words, language = captions.transcribe(prelim)
        if not words:
            raise RuntimeError("Whisper fand keine echte Sprache: kein Clip mit erfundenen Untertiteln")
        hook = hook_from_speech(words)
        width = int(os.environ["VIDEO_WIDTH"])
        height = int(round(width * 16 / 9)) // 2 * 2
        seam = height - (width * 5 // 4 // 2 * 2)
        subtitle_y = min(height - 220, seam + max(100, int(height * 0.16)))
        ass = captions.build_ass(words, hook, width, height, 60, split=True,
                                 hook_y_override=seam, subtitle_y_override=subtitle_y)
        (tmp / "captions.ass").write_text(ass, encoding="utf-8")
        # Mastering fixes exactly 1800 video frames at 30fps and 60s of audio.
        # Run in temp dir so the ASS filter has an unambiguous local filename.
        subprocess_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(Path(prelim).resolve()), "-vf",
             "ass=captions.ass,tpad=stop_mode=clone:stop_duration=1,fps=30",
             "-af", "apad,atrim=duration=60,asetpts=N/SR/TB",
             "-frames:v", "1800", "-t", "60",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", str(Path(output).resolve())]
        run = subprocess.run(subprocess_cmd, cwd=tmp, capture_output=True, text=True,
                             timeout=480)
        if run.returncode:
            raise RuntimeError("FFmpeg Untertitel/Hook-Render: " + clean_error(run.stderr))
        verified = verify_mp4(output, width, height)
        print("FFPROBE_OK", filename, json.dumps(verified), flush=True)
        return {"file": filename, "streamer": candidate.channel,
                "vod_link": vod["url"], "vod_id": candidate.vod_id,
                "vod_offset_seconds": candidate.start_s,
                "vod_timestamp": dt.isoformat(),
                "hook": hook, "spoken_language": language,
                "score": candidate.score,
                "audio_peak_db": candidate.audio_peak_db,
                "chat_boost": candidate.chat_boost,
                "ffprobe": verified}


def publish_results(records: list[dict]) -> None:
    if not records:
        return
    if os.getenv("CLIPFORGE_LOCAL") == "1":  # Mac-App: Clips bleiben lokal, kein GitHub-Upload
        return
    if not os.getenv("GITHUB_REPOSITORY") or not os.getenv("GH_TOKEN"):
        raise RuntimeError("GitHub-Release-Konfiguration fehlt")
    # Reuse monitor.publish for each verified file.
    for row in records:
        path = OUT / row["file"]
        if not monitor.publish(path):
            raise RuntimeError("Release-Upload fehlgeschlagen: " + path.name)
        row["published"] = True
    existing = []
    try:
        with tempfile.TemporaryDirectory() as td:
            result = cmd(["gh", "release", "download", RELEASE, "-R",
                          os.environ["GITHUB_REPOSITORY"], "-p", "clips.json",
                          "-D", td], timeout=90, check=False)
            old = Path(td) / "clips.json"
            if result.returncode == 0 and old.exists():
                loaded = json.loads(old.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, list) else []
    except (ValueError, OSError):
        existing = []
    index = {row.get("file"): row for row in existing if isinstance(row, dict) and row.get("file")}
    for row in records:
        index[row["file"]] = row
    manifest = OUT / "clips.json"
    manifest.write_text(json.dumps(list(index.values()), ensure_ascii=False, indent=2),
                        encoding="utf-8")
    cmd(["gh", "release", "upload", RELEASE, str(manifest), "--clobber",
         "-R", os.environ["GITHUB_REPOSITORY"]], timeout=120)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    hours = bounded_int("VOD_HOURS", 72, 1, 168)
    max_clips = bounded_int("MAX_CLIPS", 3, 1, 12)
    scan_count = bounded_int("SCAN_WINDOWS", 3, 1, 5)
    scan_seconds = bounded_int("SCAN_SECONDS", 420, 120, 900)
    vod_count = bounded_int("VODS_PER_STREAMER", 2, 1, 5)
    gap = bounded_int("MIN_GAP", 120, 120, 3600)
    title_filter = os.getenv("TITLE_FILTER", "").strip()
    report = {"started_at": stamp_now(), "requested_hours": hours,
              "max_clips": max_clips, "scan_window_seconds": scan_seconds,
              "scan_windows_per_vod": scan_count,
              "coverage_is_sampled": True, "warnings": [], "skip_reasons": [],
              "windows": [], "clips": []}
    success = False
    try:
        channels = allowed_channels(os.getenv("VOD_STREAMERS", ""))
        report["channels"] = channels
        token = helix_token()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        vods = []
        for channel in channels:
            try:
                recent = list_recent_vods(channel, token, cutoff, vod_count, title_filter)
                if not recent:
                    report["skip_reasons"].append({"streamer": channel,
                         "reason": f"Keine oeffentlichen VODs in den letzten {hours} Stunden"})
                vods.extend(recent)
            except Exception as exc:
                report["skip_reasons"].append({"streamer": channel,
                                               "reason": clean_error(str(exc))})
        report["vods_found"] = len(vods)
        cams = json.loads((ROOT / "config/cams.json").read_text(encoding="utf-8"))
        if "default" not in cams:
            raise RuntimeError("config/cams.json benoetigt default")
        candidates = []
        by_id = {vod["id"]: vod for vod in vods}
        with tempfile.TemporaryDirectory(prefix="clipforge_vods_") as td:
            tmp = Path(td)
            for vod in vods:
                if time.monotonic() - started > 30 * 60:
                    report["warnings"].append("Zeitbudget erreicht: weitere VODs ausgelassen")
                    break
                chat_path = Path(os.getenv("CHAT_REPLAY_JSON_DIR", "data/chat")) / (vod["id"] + ".json")
                chat = chat_offsets(chat_path)
                if not chat:
                    report["warnings"].append("Chat-Replay nicht verfuegbar fuer VOD " + vod["id"])
                peaks = [] if chat else chat_probe.chat_peaks(vod["id"], vod["duration"], count=max(4, max_clips))
                if peaks:  # schnell: Chat-Spitzen, nur kurze Ausschnitte laden
                    report["warnings"].append(f"Chat-Spitzen fuer VOD {vod['id']}: {len(peaks)}")
                    for off, ratio in peaks:
                        at = max(8, off - 8)
                        start = int(max(0, min(vod["duration"] - 60, at - 8 - 38)))
                        candidates.append(Candidate(vod["channel"], vod["id"], start, int(at),
                                          round(ratio, 2), 0.0, round(ratio, 2), vod["title"]))
                    continue
                candidates.extend(candidates_for_vod(vod, tmp, scan_count,
                            scan_seconds, float(os.getenv("SPIKE_DB", "6")),
                            chat, report["windows"]))
            selected = top_candidates(candidates, max_clips, min_gap=gap)
            report["candidate_count"] = len(candidates)
            report["selected_count"] = len(selected)
            for chosen in selected:
                try:
                    row = produce(chosen, by_id[chosen.vod_id], tmp, cams)
                    report["clips"].append(row)
                except Exception as exc:
                    report["skip_reasons"].append({"vod": by_id[chosen.vod_id]["url"],
                        "offset": chosen.start_s, "reason": clean_error(str(exc))})
        publish_results(report["clips"])
        report["finished_at"] = stamp_now()
        report["published_count"] = sum(bool(x.get("published")) for x in report["clips"])
        if os.getenv("CLIPFORGE_LOCAL") == "1":
            success = len(report["clips"]) > 0
        else:
            success = report["published_count"] >= min(3, max_clips)
        return 0 if success else 2
    except Exception as exc:
        report["fatal_error"] = clean_error(str(exc))
        print("VOD-FEHLER", report["fatal_error"], file=sys.stderr, flush=True)
        return 2
    finally:
        report["finished_at"] = stamp_now()
        (OUT / "vod_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        print("VOD-REPORT", json.dumps({
            "vods_found": report.get("vods_found", 0),
            "selected": report.get("selected_count", 0),
            "published": sum(bool(x.get("published")) for x in report["clips"]),
            "fatal_error": report.get("fatal_error"),
            "skip_reasons": report["skip_reasons"][:8]}), flush=True)


if __name__ == "__main__":
    sys.exit(main())
