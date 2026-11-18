"""Run the CLIPFORGE capture engine on a persistent, approved host."""
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from live_capture import main as run_capture

running = True

def stop(*_):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def prune_videos(output: Path, max_days: int, max_bytes: int):
    output.mkdir(parents=True, exist_ok=True)
    videos = sorted(output.glob("clipforge_*.mp4"), key=lambda p: p.stat().st_mtime)
    cutoff = time.time() - max_days * 86400
    for video in videos:
        if video.stat().st_mtime < cutoff:
            video.unlink(missing_ok=True)
    videos = sorted(output.glob("clipforge_*.mp4"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in videos)
    for video in videos:
        if total <= max_bytes:
            break
        total -= video.stat().st_size
        video.unlink(missing_ok=True)

def loop():
    folder = Path(os.getenv("CLIPFORGE_OUTPUT", "/data/clips"))
    interval = max(30, int(os.getenv("CAPTURE_INTERVAL_MINUTES", "120"))) * 60
    daily_limit = max(1, min(12, int(os.getenv("MAX_CLIPS_PER_DAY", "8"))))
    state = Path(os.getenv("CLIPFORGE_STATE_DIR", "/data")) / "capture_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    print("CLIPFORGE Cloud-Recorder gestartet; Intervall:", interval // 60, "Minuten", flush=True)
    while running:
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            saved = json.loads(state.read_text()) if state.exists() else {}
        except (ValueError, OSError):
            saved = {}
        count = saved.get("count", 0) if saved.get("date") == today else 0
        before = set(folder.glob("clipforge_*.mp4"))
        if count < daily_limit:
            try:
                run_capture()
            except Exception as e:
                print("Aufnahmefehler:", str(e), flush=True)
            after = set(folder.glob("clipforge_*.mp4"))
            if after - before:
                count += 1
        temp = state.with_suffix(".tmp")
        temp.write_text(json.dumps({"date": today, "count": count}))
        temp.replace(state)
        prune_videos(folder, max_days=7, max_bytes=2 * 1024**3)
        # Signal-aware sleep instead of a tight loop.
        deadline = time.monotonic() + interval
        while running and time.monotonic() < deadline:
            time.sleep(min(10, max(0.1, deadline - time.monotonic())))

if __name__ == "__main__":
    loop()
