"""Nacktheits-Filter vor dem Posten (TikTok löscht Nacktheit und sperrt Konten).

Zieht jede Sekunde ein Standbild (ganzes Bild + nur Gameplay-Teil, weil das Spiel im 9:16-Layout
klein ist) und prüft es mit NudeNet (kostenlos, CPU, kein Upload). Unsicher, wenn in mindestens
MIN_HITS Standbildern eine Klasse über ihrer Schwelle liegt. Schwellen an 17 echten Clips
eingestellt (21.11.): Po/Achsel/Bauch/Füße schlagen auch bei normalen Szenen an und zählen nicht;
Männerbrust wird oft als Frauenbrust erkannt (bis 0,63), daher Brust erst ab 0,7.
Ist NudeNet nicht installiert, gilt jeder Clip als unsicher (lieber nichts posten als etwas Falsches).
"""
from __future__ import annotations
import os, subprocess, tempfile
from pathlib import Path

UNSAFE = {  # Klasse -> Mindest-Wert
    "FEMALE_BREAST_EXPOSED": float(os.getenv("NSFW_BREAST", "0.7")),
    "FEMALE_GENITALIA_EXPOSED": float(os.getenv("NSFW_GENITALIA", "0.35")),
    "MALE_GENITALIA_EXPOSED": float(os.getenv("NSFW_GENITALIA_M", "0.5")),
    "ANUS_EXPOSED": float(os.getenv("NSFW_ANUS", "0.5")),
}
FPS = float(os.getenv("NSFW_FPS", "1"))
MIN_HITS = int(os.getenv("NSFW_MIN_HITS", "2"))
# Intimbereich: ein einziger Treffer reicht (kam an 17 echten Clips nur in der Nacktszene vor)
SINGLE_HIT = {"FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED"}

_detector = None


def _detect(image: Path) -> list[dict]:
    global _detector
    if _detector is None:
        from nudenet import NudeDetector  # erst bei Bedarf laden
        _detector = NudeDetector()
    return _detector.detect(str(image))


def frames(mp4: Path, outdir: Path) -> list[list[Path]]:
    """Pro Sekunde: [ganzes Bild, Gameplay-Teil (untere 60 %, vergrößert)]."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps={FPS},scale=720:-2", str(outdir / "a_%03d.jpg")], check=False, timeout=180)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps={FPS},crop=iw:ih*0.6:0:ih*0.4,scale=-2:1080", str(outdir / "g_%03d.jpg")],
                   check=False, timeout=180)
    return [[a] + ([outdir / ("g" + a.name[1:])] if (outdir / ("g" + a.name[1:])).exists() else [])
            for a in sorted(outdir.glob("a_*.jpg"))]


def check(mp4: Path, detect=None) -> tuple[bool, str]:
    """(sicher?, Grund). detect ist austauschbar für Tests."""
    detect = detect or _detect
    try:
        with tempfile.TemporaryDirectory(prefix="nsfw_") as t:
            imgs = frames(mp4, Path(t))
            if not imgs:
                return False, "keine Standbilder"
            hits = []
            for views in imgs:
                found = {d["class"] for img in views for d in detect(img)
                         if d.get("class") in UNSAFE and float(d.get("score", 0)) >= UNSAFE[d["class"]]}
                if found:
                    hits.append(sorted(found))
                    if len(hits) >= MIN_HITS or found & SINGLE_HIT:
                        return False, f"Nacktheit erkannt ({', '.join(hits[-1])})"
            return True, f"{len(imgs)} Standbilder geprüft, ok"
    except ImportError:
        return False, "Nacktheits-Filter (nudenet) nicht installiert"
