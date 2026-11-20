"""Steuerung: Streamerliste, Live-Pruefung, Live-Worker, VOD-Auftraege, Clip-Liste."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import live_capture as lc  # noqa: E402

from live import LiveWorker  # noqa: E402

HOME = Path(os.getenv("CLIPFORGE_HOME", Path.home() / "CLIPFORGE"))
NAME = re.compile(r"^[a-z0-9_]{3,25}$")
DEFAULTS = {"channels": [], "auto_watch": True, "max_parallel": 2, "spike_db": 7, "chat_ratio": 2.5,
            "min_gap": 120, "pre_seconds": 38, "captions": True, "max_clips_per_stream": 20,
            "vod_hours": 48, "vod_max_clips": 5, "vod_title_filter": ""}


def load_env(path: Path):
    """Einfache .env (KEY=VALUE) -> os.environ, ohne Werte auszugeben."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Manager:
    def __init__(self, home: Path = HOME):
        self.home = home
        self.clips_dir = home / "clips"
        self.work_dir = home / "work"
        self.cfg_path = home / "config.json"
        for d in (self.clips_dir, self.work_dir):
            d.mkdir(parents=True, exist_ok=True)
        load_env(ROOT / ".env")
        load_env(home / ".env")
        self.cfg = {**DEFAULTS, **(json.loads(self.cfg_path.read_text()) if self.cfg_path.exists() else {})}
        self.workers: dict[str, LiveWorker] = {}
        self.live: dict[str, bool] = {}
        self.vod_job = {"state": "bereit", "log": "", "started": None}
        self.lock = threading.Lock()
        self.running = True
        self.poller = threading.Thread(target=self._poll_loop, daemon=True)

    # ---------- Konfiguration ----------
    def save(self):
        self.cfg_path.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_channels(self, names: list[str]) -> list[str]:
        clean = []
        for n in names:
            n = n.strip().lower().lstrip("@").rstrip("/")
            if "twitch.tv/" in n:
                n = n.split("twitch.tv/")[-1].split("/")[0].split("?")[0]
            if not n:
                continue
            if not NAME.match(n):
                raise ValueError(f"Ungültiger Twitch-Login: {n!r} (nur a-z, 0-9, _ – z. B. kaicenat statt 'Kai Cenat')")
            if n not in clean:
                clean.append(n)
        self.cfg["channels"] = clean
        self.save()
        return clean

    def update_settings(self, data: dict):
        for k, v in data.items():
            if k in DEFAULTS and k != "channels":
                self.cfg[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else bool(v)
        self.save()

    # ---------- Live ----------
    def _settings(self):
        return {k: self.cfg[k] for k in DEFAULTS}

    def start_watch(self, channel: str):
        with self.lock:
            w = self.workers.get(channel)
            if w and w.is_alive():
                return False
            if sum(1 for x in self.workers.values() if x.is_alive()) >= int(self.cfg["max_parallel"]):
                raise RuntimeError(f"Maximal {self.cfg['max_parallel']} Streams gleichzeitig")
            w = LiveWorker(channel, self.clips_dir, self.work_dir, self._settings())
            self.workers[channel] = w
            w.start()
            return True

    def stop_watch(self, channel: str):
        w = self.workers.get(channel)
        if w:
            w.stop()

    def _poll_loop(self):
        while self.running:
            for ch in list(self.cfg["channels"]):
                if not self.running:
                    break
                try:
                    self.live[ch] = lc.available(ch)
                except Exception:
                    self.live[ch] = False
                w = self.workers.get(ch)
                if self.cfg.get("auto_watch") and self.live[ch] and not (w and w.is_alive()):
                    try:
                        self.start_watch(ch)
                    except RuntimeError:
                        pass
            time.sleep(60)

    def start(self):
        self.poller.start()

    # ---------- VODs ----------
    def run_vods(self, channels: list[str] | None = None):
        if self.vod_job["state"] == "läuft":
            raise RuntimeError("Ein VOD-Auftrag läuft bereits")
        chans = channels or self.cfg["channels"]
        if not chans:
            raise RuntimeError("Keine Streamer eingetragen")
        if not os.getenv("TWITCH_CLIENT_ID") or not os.getenv("TWITCH_CLIENT_SECRET"):
            raise RuntimeError("TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET fehlen in der .env")
        env = {**os.environ, "CLIPFORGE_LOCAL": "1", "CLIPFORGE_OUTPUT": str(self.clips_dir),
               "APPROVED_CHANNELS": ",".join(self.cfg["channels"]), "VOD_STREAMERS": ",".join(chans),
               "VOD_HOURS": str(self.cfg["vod_hours"]), "MAX_CLIPS": str(self.cfg["vod_max_clips"]),
               "TITLE_FILTER": self.cfg["vod_title_filter"], "VIDEO_FIT": "split",
               "SCAN_WINDOWS": "2", "SCAN_SECONDS": "240"}
        self.vod_job = {"state": "läuft", "log": "", "started": time.strftime("%H:%M")}

        def job():
            p = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts/vod_clips.py")], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT))
            for line in p.stdout:
                self.vod_job["log"] = (self.vod_job["log"] + line)[-4000:]
            p.wait()
            self._write_vod_meta()
            self.vod_job["state"] = "fertig" if p.returncode == 0 else f"beendet (Code {p.returncode})"
        threading.Thread(target=job, daemon=True).start()

    def _write_vod_meta(self):
        rep = self.clips_dir / "vod_report.json"
        if not rep.exists():
            return
        try:
            data = json.loads(rep.read_text(encoding="utf-8"))
        except ValueError:
            return
        for c in data.get("clips", []):
            f = self.clips_dir / c.get("file", "")
            if f.exists():
                meta = {"file": f.name, "channel": c.get("streamer", ""), "source": "vod",
                        "reason": "VOD-Highlight", "hook": c.get("hook", ""), "vod_link": c.get("vod_link", ""),
                        "created": c.get("vod_timestamp", "")}
                f.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- Clips ----------
    def clips(self) -> list[dict]:
        out = []
        for f in sorted(self.clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = {}
            j = f.with_suffix(".json")
            if j.exists():
                try:
                    meta = json.loads(j.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            out.append({"file": f.name, "size_mb": round(f.stat().st_size / 1e6, 1),
                        "time": time.strftime("%d.%m. %H:%M", time.localtime(f.stat().st_mtime)), **meta})
        return out

    def delete_clip(self, name: str):
        if "/" in name or not name.endswith(".mp4"):
            raise ValueError("Ungültiger Dateiname")
        (self.clips_dir / name).unlink(missing_ok=True)
        (self.clips_dir / name).with_suffix(".json").unlink(missing_ok=True)

    def state(self) -> dict:
        return {"channels": [{"name": c, "live": self.live.get(c), **({"worker": self.workers[c].status()}
                              if c in self.workers else {})} for c in self.cfg["channels"]],
                "settings": {k: v for k, v in self.cfg.items() if k != "channels"},
                "vod": self.vod_job, "clips": self.clips(),
                "twitch_keys": bool(os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET"))}
