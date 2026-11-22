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
MIN_HITS = int(os.getenv("FACECAM_MIN_HITS", "3"))
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
    best, best_hits = None, 0
    for cx0, cy0, w0, h0 in flat:
        c0 = (cx0 + w0 / 2, cy0 + h0 / 2)
        group = [b for b in flat if abs(b[0] + b[2] / 2 - c0[0]) < TOL and abs(b[1] + b[3] / 2 - c0[1]) < TOL * 1.78]
        frames_hit = sum(1 for boxes in per_frame if any(b in group for b in boxes))
        if frames_hit > best_hits:
            best, best_hits = group, frames_hit
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


def find(src: Path, start: float = 0.0, length: float = 60.0, detect=None) -> list[float] | None:
    if detect is None:
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
