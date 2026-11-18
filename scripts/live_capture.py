#!/usr/bin/env python3
"""CLIPFORGE: capture a permitted public live stream, pick an audio-energy highlight,
render a vertical MP4, and optionally send an unposted draft to TikTok.

Uses Streamlink for publicly available streams and FFmpeg for processing.
No Twitch clip API download bypass, no private stream access, no DRM handling.
"""
from __future__ import annotations
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path(os.getenv("CLIPFORGE_OUTPUT", "output"))
DEFAULT_STREAMERS = "kaicenat,xqc,montanablack88,trymacs,papaplatte,caseoh_"
MAX_CAPTURE = 130
MAX_CLIP = 60

def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))

def channels() -> list[str]:
    # A licensed allowlist: customize before enabling unattended processing.
    raw = os.getenv("APPROVED_CHANNELS", "").strip()
    if not raw:
        raise RuntimeError("APPROVED_CHANNELS ist leer. Nur freigegebene Streamer eintragen.")
    found = []
    for part in raw.split(","):
        name = part.strip().lower().lstrip("@")
        if not re.fullmatch(r"[a-z0-9_]{3,25}", name):
            raise ValueError("Ungültiger Kanalname")
        if name not in found:
            found.append(name)
    return found[:12]

def run(command: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=check)

def available(channel: str) -> bool:
    try:
        result = run(["streamlink", "--stream-url", f"https://www.twitch.tv/{channel}", "best"], timeout=20, check=False)
        return result.returncode == 0 and result.stdout.strip().startswith("http")
    except (subprocess.TimeoutExpired, OSError):
        return False

def twitch_game(channel: str) -> str | None:
    """Read current game via official Twitch Helix when API credentials are provided.
    None means game could not be verified; empty string means offline."""
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    from urllib.parse import urlencode
    form = urlencode({"client_id": client_id, "client_secret": client_secret,
                     "grant_type": "client_credentials"}).encode()
    try:
        request = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=form,
                                         method="POST")
        with urllib.request.urlopen(request, timeout=15) as resp:
            token = json.load(resp).get("access_token", "")
        if not token:
            return None
        request = urllib.request.Request(
            "https://api.twitch.tv/helix/streams?" + urlencode({"user_login": channel}),
            headers={"Authorization": "Bearer " + token, "Client-Id": client_id})
        with urllib.request.urlopen(request, timeout=15) as resp:
            payload = json.load(resp)
        streams = payload.get("data", [])
        return streams[0].get("game_name", "") if streams else ""
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None

def capture(channel: str, seconds: int, target: Path) -> None:
    """Streamlink stdout -> ffmpeg, with hard timeouts and process cleanup."""
    source = subprocess.Popen(
        ["streamlink", "--stdout", "--retry-open", "1", f"https://www.twitch.tv/{channel}", "best"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True
    )
    try:
        assert source.stdout is not None
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", "pipe:0", "-t", str(seconds), "-map", "0:v:0", "-map", "0:a?",
                   "-c", "copy", str(target)]
        ffmpeg = subprocess.Popen(command, stdin=source.stdout, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE)
        source.stdout.close()
        try:
            _, stderr = ffmpeg.communicate(timeout=seconds + 45)
        except subprocess.TimeoutExpired:
            ffmpeg.kill()
            ffmpeg.communicate()
            raise RuntimeError("Videoaufnahme wurde wegen Zeitüberschreitung gestoppt")
        if ffmpeg.returncode != 0:
            raise RuntimeError("FFmpeg konnte den Livestream nicht aufnehmen: " +
                               (stderr or b"").decode(errors="replace")[-320:])
    finally:
        if source.poll() is None:
            source.terminate()
            try:
                source.wait(timeout=5)
            except subprocess.TimeoutExpired:
                source.kill()
                source.wait(timeout=5)

def probe_duration(path: Path) -> float:
    result = run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                  str(path)], timeout=15)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0

def audio_score(source: Path, start: float, length: float) -> float:
    """Audio mean volume in dB; energetic moments tend to get higher scores."""
    try:
        result = run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(length),
                      "-i", str(source), "-vn", "-af", "volumedetect",
                      "-f", "null", "-"], timeout=28, check=False)
        match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
        if match:
            return float(match.group(1))
    except (subprocess.TimeoutExpired, OSError):
        pass
    return -100.0

def choose_start(source: Path, duration: float, clip_seconds: int) -> tuple[float, float]:
    length = min(float(clip_seconds), duration)
    if duration <= length + 2:
        return 0.0, -100.0
    max_start = max(0.0, duration - length - 0.5)
    starts = [max_start * i / 4 for i in range(5)]
    scored = [(audio_score(source, start, min(length, 30)), start) for start in starts]
    score, best = max(scored, key=lambda item: item[0])
    return round(best, 1), score

def render_vertical(source: Path, dest: Path, start: float, clip_seconds: int, duration: float) -> None:
    width = env_int("VIDEO_WIDTH", 720, 360, 1080)
    # Force even pixel width for h264
    width = width // 2 * 2
    height = round(width * 16 / 9) // 2 * 2
    # Keep full game visible; blurred sides fill 9:16 rather than stretching/cropping content.
    filt = (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=20:1[back];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front];"
        "[back][front]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start),
           "-i", str(source), "-t", str(min(clip_seconds, duration - start)),
           "-filter_complex", filt, "-map", "[v]", "-map", "0:a?",
           "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "25", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "128k", "-movflags", "+faststart", str(dest)]
    result = run(cmd, timeout=210, check=False)
    if result.returncode or not dest.exists() or dest.stat().st_size < 10_000:
        raise RuntimeError("Rendern fehlgeschlagen: " + result.stderr[-500:])

def api_json(url: str, token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=UTF-8"})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"TikTok API HTTP {exc.code}") from None
    if result.get("error", {}).get("code") != "ok":
        raise RuntimeError("TikTok API: " + str(result.get("error", {}).get("code", "unbekannter Fehler")))
    return result.get("data", {})

def tiktok_access_token() -> str:
    """Refresh and rotate TikTok OAuth tokens on a persistent host, if configured."""
    root = Path(os.getenv("CLIPFORGE_STATE_DIR", "data"))
    token_file = root / "tiktok_token.json"
    stored = {}
    if token_file.exists():
        try:
            stored = json.loads(token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
    if stored.get("access_token") and stored.get("expires_at", 0) > time.time() + 600:
        return stored["access_token"]
    key = os.getenv("TIKTOK_CLIENT_KEY", "")
    secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
    refresh = stored.get("refresh_token") or os.getenv("TIKTOK_REFRESH_TOKEN", "")
    if key and secret and refresh:
        from urllib.parse import urlencode
        data = urlencode({"client_key": key, "client_secret": secret,
                          "grant_type": "refresh_token", "refresh_token": refresh}).encode()
        req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/",
            data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"TikTok Token-Aktualisierung fehlgeschlagen (HTTP {exc.code})") from None
        if not payload.get("access_token") or not payload.get("refresh_token"):
            raise RuntimeError("TikTok Token-Aktualisierung ungueltig: erneute OAuth-Anmeldung noetig")
        root.mkdir(parents=True, exist_ok=True)
        current = {"access_token": payload["access_token"],
                   "refresh_token": payload["refresh_token"],
                   "expires_at": time.time() + int(payload.get("expires_in", 3600)),
                   "open_id": payload.get("open_id", "")}
        new_file = token_file.with_suffix(".tmp")
        new_file.write_text(json.dumps(current), encoding="utf-8")
        os.chmod(new_file, 0o600)
        new_file.replace(token_file)
        return payload["access_token"]
    return os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()

def tiktok_draft(mp4: Path, token: str) -> str:
    """Official Content Posting API inbox video upload. NOT a public post."""
    size = mp4.stat().st_size
    if size > 60 * 1024 * 1024:
        raise RuntimeError("MP4 ist für den sicheren Einzelchunk-Upload zu groß")
    init = api_json("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", token,
        {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                         "chunk_size": size, "total_chunk_count": 1}})
    upload_url = init.get("upload_url", "")
    # TikTok may use regional upload hosts; no arbitrary untrusted redirect.
    from urllib.parse import urlsplit
    parts = urlsplit(upload_url)
    if parts.scheme != "https" or not (
        parts.hostname == "tiktokapis.com" or (parts.hostname or "").endswith(".tiktokapis.com")
    ):
        raise RuntimeError("TikTok lieferte einen unerwarteten Upload-Host")
    data = mp4.read_bytes()
    request = urllib.request.Request(upload_url, data=data, method="PUT",
        headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                 "Content-Range": f"bytes 0-{size-1}/{size}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status not in (200, 201, 202, 204):
                raise RuntimeError("TikTok Upload nicht bestätigt")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"TikTok MP4-Transfer HTTP {exc.code}") from None
    return str(init.get("publish_id", ""))

def write_report(data: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    capture_seconds = env_int("CAPTURE_SECONDS", 105, 45, MAX_CAPTURE)
    clip_seconds = env_int("CLIP_SECONDS", 40, 15, MAX_CLIP)
    target = os.getenv("TARGET_STREAMER", "").strip().lower().lstrip("@")
    approved = channels()
    if target and target not in approved:
        raise RuntimeError("Der ausgewählte Streamer ist nicht in APPROVED_CHANNELS freigegeben")
    now = datetime.now(timezone.utc)
    # Rotate first pick so multiple channels get a turn over the day.
    shift = now.hour % len(approved)
    rotated = approved[shift:] + approved[:shift]
    if target:
        rotated = [target]
    report = {"checked_at": now.isoformat(), "tested_channels": rotated,
              "status": "no_live_stream", "uploaded_to_tiktok": False}
    channel, game = None, None
    allowed_games = [g.strip().lower() for g in os.getenv("ALLOWED_GAMES", "Grand Theft Auto VI").split(",") if g.strip()]
    for candidate in rotated:
        if not available(candidate):
            continue
        candidate_game = twitch_game(candidate)
        if candidate_game is not None and candidate_game.lower() not in allowed_games:
            print(f"Ueberspringe {candidate}: spielt '{candidate_game or 'kein Spiel'}'.")
            continue
        channel, game = candidate, candidate_game
        break
    if channel is None:
        print("Keiner der freigegebenen Streamer sendet gerade das gesuchte Spiel bzw. ist erreichbar.")
        report["status"] = "no_approved_live_gta_stream"
        write_report(report)
        return 0
    if game is None:
        print("Hinweis: Twitch-Spielkategorie mangels API-Zugang nicht geprueft.")
    raw = OUTPUT / "live_recording.mkv"
    clip = OUTPUT / f"clipforge_{channel}_{now.strftime('%Y%m%d_%H%M%S')}.mp4"
    print(f"Nehme {channel} für maximal {capture_seconds} Sekunden auf.")
    capture(channel, capture_seconds, raw)
    duration = probe_duration(raw)
    if duration < 20:
        raise RuntimeError("Streamaufnahme zu kurz für einen brauchbaren Clip")
    start, energy_db = choose_start(raw, duration, clip_seconds)
    print(f"Clipfenster ab {start:.1f}s (Audio-Energie {energy_db:.1f} dB)")
    render_vertical(raw, clip, start, clip_seconds, duration)
    raw.unlink(missing_ok=True)  # do not keep the full capture in the artifact
    report.update(status="mp4_ready", streamer=channel, mp4_filename=clip.name,
                  mp4_bytes=clip.stat().st_size, clip_start_seconds=start,
                  audio_score_db=energy_db, clip_length_seconds=min(clip_seconds, duration-start),
                  source=f"https://www.twitch.tv/{channel}", game_name=game, format="vertical_mp4")
    token = tiktok_access_token()
    mode = os.getenv("TIKTOK_UPLOAD_MODE", "draft").lower()
    if mode == "draft" and token and (game is not None or os.getenv("ALLOW_UNVERIFIED_GAME_UPLOAD", "false").lower() == "true"):
        try:
            publish_id = tiktok_draft(clip, token)
            report.update(uploaded_to_tiktok=True, tiktok_status="inbox_pending",
                          tiktok_publish_id=publish_id)
            print("TikTok Inbox-Entwurf übertragen; Veröffentlichung muss im TikTok-Konto erfolgen.")
        except Exception as exc:
            report.update(tiktok_status="failed", tiktok_error=str(exc))
            print("TikTok Entwurf fehlgeschlagen: " + str(exc), file=sys.stderr)
    else:
        report["tiktok_status"] = "not_configured_or_game_unverified"
    write_report(report)
    print(f"MP4 fertig: {clip.name}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("CLIPFORGE Fehler: " + str(exc), file=sys.stderr)
        write_report({"status": "error", "reason": str(exc),
                      "checked_at": datetime.now(timezone.utc).isoformat()})
        sys.exit(1)
