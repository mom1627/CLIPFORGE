"""Prüft, ob im Spielbereich eines fertigen Clips wirklich Gameplay läuft.

Aussortiert werden: (1) Standbilder wie Ladebildschirm, Dashboard, Menü (kaum Bewegung) und
(2) Szenen, in denen der Streamer groß im Spielbereich zu sehen ist (IRL, Just Chatting,
Vollbild-Facecam). Gesichter erkennt NudeNet (FACE_MALE/FACE_FEMALE), das ohnehin installiert ist.
"""
from __future__ import annotations
import os, subprocess, tempfile
from pathlib import Path

SAMPLES = int(os.getenv("GAMEPLAY_SAMPLES", "10"))
MIN_MOTION = float(os.getenv("GAMEPLAY_MIN_MOTION", "6"))   # mittlere Pixeländerung (0..255)
FACE_SHARE = float(os.getenv("GAMEPLAY_FACE_SHARE", "0.04"))  # Gesichtsfläche / Bildfläche
FACE_FRAMES = float(os.getenv("GAMEPLAY_FACE_FRAMES", "0.5"))  # Anteil der Bilder mit großem Gesicht


def _crops(mp4: Path, outdir: Path) -> list[Path]:
    # mittlerer Spielbereich (unter Titel/Zitat, über Untertiteln und Logo)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps={SAMPLES}/60,crop=iw:ih*0.28:0:ih*0.40,scale=480:-2",
                    str(outdir / "g_%02d.png")], check=False, timeout=120)
    return sorted(outdir.glob("g_*.png"))


def motion(images: list[Path]) -> float:
    from PIL import Image, ImageChops, ImageStat
    if len(images) < 2:
        return 0.0
    diffs = []
    prev = Image.open(images[0]).convert("L").resize((160, 90))
    for p in images[1:]:
        cur = Image.open(p).convert("L").resize((160, 90))
        diffs.append(ImageStat.Stat(ImageChops.difference(prev, cur)).mean[0])
        prev = cur
    diffs.sort()
    return diffs[len(diffs) // 2]


def big_face_share(images: list[Path], detect) -> float:
    from PIL import Image
    hits = 0
    for p in images:
        w, h = Image.open(p).size
        for d in detect(p):
            if str(d.get("class", "")).startswith("FACE") and float(d.get("score", 0)) >= 0.5:
                bw, bh = (d.get("box") or [0, 0, 0, 0])[2:4]
                if bw * bh / float(w * h) >= FACE_SHARE:
                    hits += 1
                    break
    return hits / max(1, len(images))


def check(mp4: Path, detect=None) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="gp_") as t:
        imgs = _crops(mp4, Path(t))
        if len(imgs) < 3:
            return True, "zu wenige Bilder, nicht geprüft"
        m = motion(imgs)
        if m < MIN_MOTION:
            return False, f"kaum Bewegung ({m:.1f}) – Menü/Ladebildschirm/Dashboard"
        if detect is None:
            try:
                import safety
                detect = safety._detect
            except ImportError:
                return True, f"Bewegung {m:.1f}, Gesichtsprüfung nicht verfügbar"
        try:
            share = big_face_share(imgs, detect)
        except ImportError:
            return True, f"Bewegung {m:.1f}, Gesichtsprüfung nicht verfügbar"
        if share >= FACE_FRAMES:
            return False, f"Streamer statt Gameplay im Spielbereich ({share:.0%} der Bilder)"
        return True, f"Gameplay ok (Bewegung {m:.1f})"


CAM_FRAMES = float(os.getenv("CAM_FACE_FRAMES", "0.4"))  # Anteil der Bilder, in denen oben ein Gesicht sein muss


def _top_crops(mp4: Path, outdir: Path) -> list[Path]:
    # oberer Webcam-Bereich (über dem Hook an der Naht)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps={SAMPLES}/60,crop=iw:ih*0.32:0:0", str(outdir / "t_%02d.png")],
                   check=False, timeout=120)
    return sorted(outdir.glob("t_*.png"))


def face_frames(images: list[Path], detect) -> float:
    hits = sum(any(str(d.get("class", "")).startswith("FACE") for d in detect(p)) for p in images)
    return hits / max(1, len(images))


def cam_check(mp4: Path, detect=None) -> tuple[bool, str]:
    """Sitzt der Streamer wirklich oben in der Webcam-Fläche? Sonst ist die Platzierung falsch
    (z. B. Webcam-Ausschnitt zeigt Spiel/Overlay und der Streamer landet unten im Spielbereich)."""
    if detect is None:
        try:
            import facecam, cv2  # noqa: F401
            detect = facecam.detect_cv
        except ImportError:
            return True, "Webcam-Prüfung nicht verfügbar"
    with tempfile.TemporaryDirectory(prefix="cam_") as t:
        imgs = _top_crops(mp4, Path(t))
        if len(imgs) < 3:
            return True, "zu wenige Bilder, nicht geprüft"
        share = face_frames(imgs, detect)
        if share < CAM_FRAMES:
            return False, f"kein Streamer oben in der Webcam ({share:.0%} der Bilder)"
        return True, f"Webcam ok ({share:.0%})"


def full_check(mp4: Path) -> tuple[bool, str]:
    """Alle Pflicht-Prüfungen für einen fertigen Clip: Gameplay unten, Streamer oben."""
    ok, why = check(mp4)
    if not ok:
        return ok, why
    ok2, why2 = cam_check(mp4)
    return ok2, f"{why}; {why2}"
