"""Live-Ueberwachung eines Kanals: Stream laufend aufnehmen, Chat mitlesen, bei Chat- oder Ton-Spitze
einen 60-s-Clip (Facecam oben, Gameplay unten, Hook, Untertitel) lokal speichern."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import captions  # noqa: E402
import monitor  # noqa: E402

from chat import ChatReader, ChatSpikes  # noqa: E402

REACT_S = 5  # Zuschauer reagieren im Chat ein paar Sekunden nach dem Moment


class LiveWorker(threading.Thread):
    def __init__(self, channel: str, clips_dir: Path, work_dir: Path, settings: dict, on_clip=None):
        super().__init__(daemon=True)
        self.channel, self.clips_dir, self.settings = channel, clips_dir, settings
        self.folder = work_dir / f"rec_{channel}"
        self.on_clip = on_clip
        self.running = True
        self.state = "startet"
        self.clips = 0
        self.last_reason = ""
        self.spikes = ChatSpikes(ratio=float(settings.get("chat_ratio", 2.5)),
                                 min_gap=int(settings.get("min_gap", 120)))
        self.chat = ChatReader(channel, self.spikes)
        self.started = time.time()

    def stop(self):
        self.running = False

    def status(self) -> dict:
        return {"channel": self.channel, "state": self.state, "clips": self.clips,
                "chat_connected": self.chat.connected, "chat_messages": self.chat.messages,
                "chat_rate": self.spikes.rate(time.time()), "last": self.last_reason,
                "since": datetime.fromtimestamp(self.started).strftime("%H:%M")}

    def _make_clip(self, end: int, reason: str, strength: float):
        pre = int(self.settings.get("pre_seconds", 38))
        self.state = "schneidet Clip"
        cam = self.settings.get("cams", {}).get(self.channel)
        fit = "blur" if cam == "none" else "split"
        mp4 = monitor.build_clip(self.folder, end, pre, 0, self.clips_dir, self.channel,
                                 cam_box=cam if isinstance(cam, list) else None, fit=fit)
        if not mp4:
            self.state = "nimmt auf"
            return
        if self.settings.get("captions", True):
            self.state = "Untertitel"
            mp4 = captions.add_captions(mp4, self.channel, f"{end}", split=(fit == "split"))
            mp4.with_suffix(".ass").unlink(missing_ok=True)
        meta = {"file": mp4.name, "channel": self.channel, "source": "live", "reason": reason,
                "strength": strength, "created": datetime.now().isoformat(timespec="seconds")}
        mp4.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.clips += 1
        self.last_reason = f"{reason} ({strength}x)"
        self.state = "nimmt auf"
        if self.on_clip:
            self.on_clip(meta)

    def run(self):
        if self.folder.exists():
            shutil.rmtree(self.folder, ignore_errors=True)
        self.chat.start()
        try:
            src, ff = monitor.start_recorder(self.channel, self.folder)
        except OSError as exc:
            self.chat.stop()
            self.state = f"Fehler: {exc}"[:140]
            self.running = False
            return
        t0 = None
        det = monitor.Detector(spike_db=float(self.settings.get("spike_db", 7)),
                               min_gap=int(self.settings.get("min_gap", 120)))
        done, pending = 0, []  # pending: (end_second, reason, strength)
        max_clips = int(self.settings.get("max_clips_per_stream", 20))
        self.state = "nimmt auf"
        try:
            while self.running and self.clips < max_clips:
                time.sleep(2)
                if ff.poll() is not None:
                    self.state = "Stream beendet"
                    break
                segs = sorted(self.folder.glob("seg_*.ts"))
                if t0 is None and segs:
                    t0 = segs[0].stat().st_ctime  # Wanduhrzeit von Aufnahmesekunde 0
                if t0 is None:
                    continue
                # 1) Chat-Spitze (Hauptsignal)
                hit = self.spikes.check(time.time())
                if hit:
                    end = int(hit[0] - t0 - REACT_S)
                    if end > 20:
                        pending.append((end, "Chat-Spitze", hit[1]))
                # 2) Ton-Spitze (zweites Signal)
                complete = segs[:-1]
                while done < len(complete):
                    vals = monitor.per_second_db(complete[done])
                    done += 1
                    for end in det.feed(vals):
                        if all(abs(end - p[0]) > 60 for p in pending):
                            pending.append((end, "Ton-Spitze", 1.0))
                recorded = done * monitor.SEG
                pre = int(self.settings.get("pre_seconds", 38))
                for item in sorted(pending):
                    if recorded >= monitor.clip_range(item[0], pre)[1]:
                        pending.remove(item)
                        try:
                            self._make_clip(*item)
                        except Exception as exc:  # ein kaputter Clip beendet nicht die ganze Ueberwachung
                            self.last_reason = f"Clip übersprungen: {str(exc)[:80]}"
                            self.state = "nimmt auf"
                for old in segs[:max(0, done - 14)]:  # Puffer ~7 Minuten
                    old.unlink(missing_ok=True)
        except Exception as exc:  # Fehler sichtbar machen, App laeuft weiter
            self.state = f"Fehler: {str(exc)[:120]}"
        finally:
            self.chat.stop()
            monitor.stop(ff, src)
            shutil.rmtree(self.folder, ignore_errors=True)
            if not self.state.startswith("Fehler"):
                self.state = "beendet" if not self.running else self.state
