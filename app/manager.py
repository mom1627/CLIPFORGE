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
from tiktok import TikTok, TikTokError  # noqa: E402
import publisher  # noqa: E402

HOME = Path(os.getenv("CLIPFORGE_HOME", Path.home() / "CLIPFORGE"))
NAME = re.compile(r"^[a-z0-9_]{3,25}$")
DEFAULTS = {"channels": [], "auto_watch": True, "max_parallel": 6, "spike_db": 7, "chat_ratio": 2.5,
            "min_gap": 120, "pre_seconds": 38, "captions": True, "max_clips_per_stream": 20,
            "vod_hours": 48, "vod_max_clips": 5, "vod_title_filter": "", "tiktok_auto": False, "cams": {}, "auto_publish": False, "max_posts_per_day": 15, "post_gap_minutes": 60,
            "caption_tags": publisher.DEFAULT_TAGS}


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
    def __init__(self, home: Path = HOME, port: int = 8787):
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
        self.tiktok = TikTok(home, f"http://localhost:{port}/tiktok/callback")
        self.uploads: dict[str, str] = {}

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

    CAM_PRESETS = {"unten-rechts": [0.727, 0.60, 0.26, 0.40], "unten-links": [0.0, 0.60, 0.26, 0.40],
                   "oben-rechts": [0.727, 0.0, 0.26, 0.40], "oben-links": [0.0, 0.0, 0.26, 0.40], "keine": "none"}

    def set_cam(self, channel: str, value):
        """value: Preset-Name, 'keine' oder [x,y,w,h] als Anteile (0..1) des Streambilds."""
        if isinstance(value, str):
            if value not in self.CAM_PRESETS:
                raise ValueError("Unbekannte Facecam-Position")
            value = self.CAM_PRESETS[value]
        elif not (isinstance(value, list) and len(value) == 4 and all(0 <= float(v) <= 1 for v in value)):
            raise ValueError("Facecam: [x, y, Breite, Höhe] als Werte zwischen 0 und 1")
        self.cfg.setdefault("cams", {})[channel] = value
        self.save()
        w = self.workers.get(channel)
        if w:
            w.settings.setdefault("cams", {})[channel] = value

    def update_settings(self, data: dict):
        for k, v in data.items():
            if k in DEFAULTS and k not in ("channels", "cams"):
                self.cfg[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else bool(v)
        self.save()

    # ---------- Live ----------
    def _settings(self):
        return {k: (dict(self.cfg[k]) if isinstance(self.cfg[k], dict) else self.cfg[k]) for k in DEFAULTS}

    def start_watch(self, channel: str):
        with self.lock:
            w = self.workers.get(channel)
            if w and w.is_alive():
                return False
            if sum(1 for x in self.workers.values() if x.is_alive()) >= int(self.cfg["max_parallel"]):
                raise RuntimeError(f"Maximal {self.cfg['max_parallel']} Streams gleichzeitig")
            w = LiveWorker(channel, self.clips_dir, self.work_dir, self._settings(), on_clip=self._new_clip)
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
                failed = w is not None and not w.is_alive() and str(w.state).startswith("Fehler")
                if self.cfg.get("auto_watch") and self.live[ch] and not (w and w.is_alive()) and not failed:
                    try:
                        self.start_watch(ch)
                    except RuntimeError:
                        pass
            try:
                self._auto_post_tick()
            except Exception as exc:  # Posten darf die Überwachung nie stoppen
                print("Auto-Posten:", exc)
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
            for name in self._write_vod_meta():
                self._new_clip({"file": name})
            self.vod_job["state"] = "fertig" if p.returncode == 0 else f"beendet (Code {p.returncode})"
        threading.Thread(target=job, daemon=True).start()

    def _write_vod_meta(self) -> list[str]:
        rep = self.clips_dir / "vod_report.json"
        made = []
        if not rep.exists():
            return made
        try:
            data = json.loads(rep.read_text(encoding="utf-8"))
        except ValueError:
            return made
        for c in data.get("clips", []):
            f = self.clips_dir / c.get("file", "")
            if f.exists():
                meta = {"file": f.name, "channel": c.get("streamer", ""), "source": "vod",
                        "reason": "VOD-Highlight", "hook": c.get("hook", ""), "vod_link": c.get("vod_link", ""),
                        "created": c.get("vod_timestamp", "")}
                f.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                made.append(f.name)
        return made

    # ---------- TikTok ----------
    def _new_clip(self, meta: dict):
        if self.cfg.get("auto_publish") and publisher.configured():
            self._auto_post_tick()  # postet sofort, wenn Tageslimit und Abstand es erlauben, sonst später
        elif self.cfg.get("tiktok_auto") and self.tiktok.connected():
            self.upload_tiktok(meta["file"])

    # ---------- Öffentlich posten (Buffer) ----------
    def _metas(self) -> list[dict]:
        out = []
        for j in self.clips_dir.glob("*.json"):
            try:
                m = json.loads(j.read_text(encoding="utf-8"))
            except ValueError:
                continue
            m.setdefault("file", j.with_suffix(".mp4").name)
            out.append(m)
        return out

    def _post_times(self) -> list[float]:
        t = []
        for m in self._metas():
            try:
                t.append(time.mktime(time.strptime(str(m.get("posted_at", ""))[:16], "%Y-%m-%d %H:%M")))
            except ValueError:
                pass
        return t

    def _posts_today(self) -> int:
        return sum(1 for x in self._post_times() if time.time() - x < 86400)  # rollierende 24 h wie bei TikTok

    def _auto_post_tick(self):
        """Postet den stärksten noch nicht geposteten Clip, wenn Limit (24 h) und Mindestabstand es erlauben."""
        if not (self.cfg.get("auto_publish") and publisher.configured()):
            return
        if any(v == "wird gepostet" for v in self.uploads.values()):
            return
        times = self._post_times()
        if sum(1 for x in times if time.time() - x < 86400) >= int(self.cfg.get("max_posts_per_day", 15)):
            return
        if times and time.time() - max(times) < 60 * float(self.cfg.get("post_gap_minutes", 60)):
            return
        cands = [m for m in self._metas() if not m.get("posted_at") and not str(m.get("tiktok", "")).startswith("Fehler")
                 and (self.clips_dir / m["file"]).exists()
                 and time.time() - (self.clips_dir / m["file"]).stat().st_mtime < 12 * 3600]
        if not cands:
            return
        best = max(cands, key=lambda m: (float(m.get("strength") or 1), (self.clips_dir / m["file"]).stat().st_mtime))
        self.publish(best["file"])

    def set_publisher(self, data: dict) -> dict:
        """Buffer/Cloudinary-Einstellungen in ~/CLIPFORGE/.env speichern (Schlüssel gibt der Nutzer selbst ein,
        er wird nie zurückgegeben oder geloggt) und die Verbindung prüfen."""
        allowed = {"buffer_api_key": "BUFFER_API_KEY", "cloudinary_cloud_name": "CLOUDINARY_CLOUD_NAME",
                   "cloudinary_upload_preset": "CLOUDINARY_UPLOAD_PRESET"}
        new = {env: str(data[k]).strip() for k, env in allowed.items() if str(data.get(k, "")).strip()}
        for v in new.values():
            if any(c in v for c in "\r\n=") or len(v) > 300:
                raise ValueError("Ungültiger Wert")
        envf = self.home / ".env"
        lines = envf.read_text(encoding="utf-8").splitlines() if envf.exists() else []
        done = set()
        for i, ln in enumerate(lines):
            k = ln.split("=", 1)[0].strip()
            if k in new:
                lines[i] = f"{k}={new[k]}"; done.add(k)
        lines += [f"{k}={v}" for k, v in new.items() if k not in done]
        envf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(envf, 0o600)
        except OSError:
            pass
        os.environ.update(new)
        if not publisher.configured():
            return {"ok": False, "message": "Noch fehlt: " + ", ".join(publisher.missing())}
        try:
            publisher.tiktok_channel()
        except publisher.PublishError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "Buffer verbunden, TikTok-Kanal gefunden ✓"}

    def caption_for(self, name: str) -> str:
        meta = {}
        j = (self.clips_dir / name).with_suffix(".json")
        if j.exists():
            try:
                meta = json.loads(j.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return publisher.build_caption(meta.get("channel", ""), meta.get("hook", ""), self.cfg.get("caption_tags"))

    def publish(self, name: str, caption: str | None = None):
        if "/" in name or not name.endswith(".mp4") or not (self.clips_dir / name).exists():
            raise ValueError("Clip nicht gefunden")
        if not publisher.configured():
            raise RuntimeError("Fehlt in ~/CLIPFORGE/.env: " + ", ".join(publisher.missing()))
        if self.uploads.get(name) == "wird gepostet":
            return
        text = (caption or self.caption_for(name)).strip()
        self.uploads[name] = "wird gepostet"

        def job():
            try:
                r = publisher.publish(self.clips_dir / name, text)
                self.uploads[name] = "geplant ✓ (Buffer)"
                self._set_meta(name, tiktok="geplant ✓ (Buffer)", posted_at=time.strftime("%Y-%m-%d %H:%M"),
                               caption=text, buffer_post=r.get("post_id"))
            except (publisher.PublishError, OSError) as exc:
                self.uploads[name] = f"Fehler: {exc}"[:160]
                self._set_meta(name, tiktok=f"Fehler: {exc}"[:160])
        threading.Thread(target=job, daemon=True).start()

    def _set_meta(self, name: str, **kv):
        j = (self.clips_dir / name).with_suffix(".json")
        meta = {}
        if j.exists():
            try:
                meta = json.loads(j.read_text(encoding="utf-8"))
            except ValueError:
                pass
        meta.update(kv)
        j.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def upload_tiktok(self, name: str):
        if "/" in name or not name.endswith(".mp4") or not (self.clips_dir / name).exists():
            raise ValueError("Clip nicht gefunden")
        if self.uploads.get(name) == "lädt hoch":
            return
        self.uploads[name] = "lädt hoch"

        def job():
            try:
                r = self.tiktok.upload_draft(self.clips_dir / name)
                txt = "in TikTok-Inbox" if r["status"] == "SEND_TO_USER_INBOX" else r["status"]
                self.uploads[name] = txt
                self._set_meta(name, tiktok=txt, tiktok_publish_id=r["publish_id"])
            except (TikTokError, OSError) as exc:
                self.uploads[name] = f"Fehler: {exc}"[:160]
        threading.Thread(target=job, daemon=True).start()

    # ---------- Clips ----------
    def clips(self) -> list[dict]:
        out = []
        for f in sorted(self.clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.stem.endswith("_cap") or (not f.with_suffix(".json").exists() and time.time() - f.stat().st_mtime < 300):
                continue  # Clip wird gerade noch fertig bearbeitet
            meta = {}
            j = f.with_suffix(".json")
            if j.exists():
                try:
                    meta = json.loads(j.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            row = {"file": f.name, "size_mb": round(f.stat().st_size / 1e6, 1),
                   "time": time.strftime("%d.%m. %H:%M", time.localtime(f.stat().st_mtime)), **meta}
            if f.name in self.uploads:
                row["tiktok"] = self.uploads[f.name]
            out.append(row)
        return out

    def delete_clip(self, name: str):
        if "/" in name or not name.endswith(".mp4"):
            raise ValueError("Ungültiger Dateiname")
        (self.clips_dir / name).unlink(missing_ok=True)
        (self.clips_dir / name).with_suffix(".json").unlink(missing_ok=True)

    def state(self) -> dict:
        return {"channels": [{"name": c, "live": self.live.get(c), "cam": self.cfg.get("cams", {}).get(c), **({"worker": self.workers[c].status()}
                              if c in self.workers else {})} for c in self.cfg["channels"]],
                "settings": {k: v for k, v in self.cfg.items() if k != "channels"},
                "vod": self.vod_job, "clips": self.clips(),
                "twitch_keys": bool(os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET")),
                "tiktok": {"configured": self.tiktok.configured(), "connected": self.tiktok.connected()},
                "publisher": {"configured": publisher.configured(), "posts_today": self._posts_today(), "missing": publisher.missing()}}
