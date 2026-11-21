"""Nacktheits-Filter vor dem Posten (TikTok löscht Nacktheit und sperrt Konten).

Zieht alle FRAME_STEP Sekunden ein Standbild aus dem Clip und prüft es mit NudeNet
(kostenlos, läuft lokal auf der CPU, kein Upload). Ein Clip gilt als unsicher, wenn in
mindestens MIN_HITS Standbildern ein unbedeckter Körperteil erkannt wird.
Ist NudeNet nicht installiert, gilt jeder Clip als unsicher (lieber nichts posten als etwas Falsches).
"""
from __future__ import annotations
import os, subprocess, tempfile
from pathlib import Path

UNSAFE = {"FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED",
          "BUTTOCKS_EXPOSED", "ANUS_EXPOSED"}
FRAME_STEP = float(os.getenv("NSFW_FRAME_STEP", "2"))
MIN_SCORE = float(os.getenv("NSFW_MIN_SCORE", "0.5"))
MIN_HITS = int(os.getenv("NSFW_MIN_HITS", "2"))

_detector = None


def _detect(image: Path) -> list[dict]:
    global _detector
    if _detector is None:
        from nudenet import NudeDetector  # erst bei Bedarf laden
        _detector = NudeDetector()
    return _detector.detect(str(image))


def frames(mp4: Path, outdir: Path) -> list[Path]:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps=1/{FRAME_STEP},scale=640:-2", str(outdir / "f_%03d.jpg")],
                   check=False, timeout=180)
    return sorted(outdir.glob("f_*.jpg"))


def check(mp4: Path, detect=None) -> tuple[bool, str]:
    """(sicher?, Grund). detect ist austauschbar für Tests."""
    detect = detect or _detect
    try:
        with tempfile.TemporaryDirectory(prefix="nsfw_") as t:
            imgs = frames(mp4, Path(t))
            if not imgs:
                return False, "keine Standbilder"
            hits = []
            for img in imgs:
                found = {d["class"] for d in detect(img) if d.get("class") in UNSAFE and float(d.get("score", 0)) >= MIN_SCORE}
                if found:
                    hits.append((img.name, sorted(found)))
                    if len(hits) >= MIN_HITS:
                        return False, f"Nacktheit erkannt ({', '.join(hits[-1][1])})"
            return True, f"{len(imgs)} Standbilder geprüft, ok"
    except ImportError:
        return False, "Nacktheits-Filter (nudenet) nicht installiert"
