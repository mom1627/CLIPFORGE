"""Automatische Facecam-Erkennung: Wo im Stream sitzt die Webcam des Streamers?

Zieht mehrere Standbilder aus dem Quellvideo, sucht Gesichter (NudeNet FACE_*), und nimmt die Stelle,
an der in mehreren Bildern ein Gesicht an (fast) derselben Position ist – das ist die Facecam.
Gesichter von Spielfiguren bewegen sich und fallen dadurch heraus. Ergebnis: [x, y, w, h] als
Anteile des Bildes (wie config/cams.json) oder None, wenn keine Facecam gefunden wurde.
"""
from __future__ import annotations
import os, subprocess, tempfile
from pathlib import Path

SAMPLES = int(os.getenv("FACECAM_SAMPLES", "8"))
MIN_HITS = int(os.getenv("FACECAM_MIN_HITS", "4"))  # Hälfte der Bilder: sonst Fehltreffer (Spielfiguren, Overlays)
TOL = float(os.getenv("FACECAM_TOL", "0.06"))          # max. Abstand der Gesichtsmitten (Anteil der Bildbreite)
MAX_FACE = float(os.getenv("FACECAM_MAX_FACE", "0.12"))  # größere Gesichter = Vollbild-Kamera, keine Facecam


def frames(src: Path, outdir: Path, start: float = 0.0, length: float = 60.0) -> list[Path]:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-t", str(length),
                    "-i", str(src), "-vf", f"fps={SAMPLES}/{max(1.0, length)},scale=1280:-2",
                    str(outdir / "f_%02d.jpg")], check=False, timeout=180)
    return sorted(outdir.glob("f_*.jpg"))


def faces(images: list[Path], detect) -> list[list[tuple[float, float, float, float]]]:
    from PIL import Image
    out = []
    for p in images:
        W, H = Image.open(p).size
        boxes = []
        for d in detect(p):
            if str(d.get("class", "")).startswith("FACE") and float(d.get("score", 0)) >= 0.45:
                x, y, w, h = (d.get("box") or [0, 0, 0, 0])[:4]
                if w > 0 and h > 0:
                    boxes.append((x / W, y / H, w / W, h / H))
        out.append(boxes)
    return out


def cam_from_faces(per_frame, aspect: float = 16 / 9 * 1.06) -> list[float] | None:
    """Stabilste Gesichtsposition über die Bilder -> Facecam-Ausschnitt (Anteile)."""
    flat = [b for boxes in per_frame for b in boxes if b[2] <= MAX_FACE]
    best, best_hits, best_size = None, 0, 0.0
    for cx0, cy0, w0, h0 in flat:
        c0 = (cx0 + w0 / 2, cy0 + h0 / 2)
        group = [b for b in flat if abs(b[0] + b[2] / 2 - c0[0]) < TOL and abs(b[1] + b[3] / 2 - c0[1]) < TOL * 1.78]
        frames_hit = sum(1 for boxes in per_frame if any(b in group for b in boxes))
        size = sum(b[2] for b in group) / len(group)
        if (frames_hit, size) > (best_hits, best_size):  # öfter gefunden, bei Gleichstand größer (Chat-Emojis sind klein)
            best, best_hits, best_size = group, frames_hit, size
    if not best or best_hits < MIN_HITS:
        return None
    fx = sum(b[0] + b[2] / 2 for b in best) / len(best)
    fy = sum(b[1] + b[3] / 2 for b in best) / len(best)
    fw = sum(b[2] for b in best) / len(best)
    # Facecam = Gesicht mit Kopf und Schultern: etwa 4,5x Gesichtsbreite, Seitenverhältnis wie oberer Bildteil
    cw = min(0.6, max(0.12, fw * 4.5))
    ch = min(0.6, cw * (16 / 9) / aspect)
    x = min(max(0.0, fx - cw / 2), 1 - cw)
    y = min(max(0.0, fy - ch * 0.42), 1 - ch)
    return [round(x, 4), round(y, 4), round(cw, 4), round(ch, 4)]


_cascades = None


def detect_cv(image: Path) -> list[dict]:
    """Gesichter in voller Auflösung (OpenCV Haar, frontal + Profil beidseitig).
    NudeNet verkleinert auf 320 px – kleine Webcam-Gesichter gehen dabei verloren."""
    global _cascades
    import cv2
    if _cascades is None:
        base = cv2.data.haarcascades
        _cascades = [cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml"),
                     cv2.CascadeClassifier(base + "haarcascade_profileface.xml")]
    img = cv2.imread(str(image))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    W = g.shape[1]
    out = []
    for i, c in enumerate(_cascades):
        for flip in ((False, True) if i == 1 else (False,)):
            gg = cv2.flip(g, 1) if flip else g
            for (x, y, w, h) in c.detectMultiScale(gg, 1.1, 6, minSize=(40, 40)):
                x = W - x - w if flip else x
                out.append({"class": "FACE", "score": 0.9, "box": [int(x), int(y), int(w), int(h)]})
    return out


def find(src: Path, start: float = 0.0, length: float = 60.0, detect=None) -> list[float] | None:
    if detect is None:
        try:
            import cv2  # noqa: F401
            detect = detect_cv
        except ImportError:
            try:
                import safety
                detect = safety._detect
            except ImportError:
                return None
    with tempfile.TemporaryDirectory(prefix="fc_") as t:
        imgs = frames(src, Path(t), start, length)
        if len(imgs) < MIN_HITS:
            return None
        try:
            return cam_from_faces(faces(imgs, detect))
        except ImportError:
            return None
