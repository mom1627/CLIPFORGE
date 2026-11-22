"""Aktive Clipping-Kampagne (config/campaign.json): Logo, Pflicht-Hashtags, Pflicht-Spiel.

Beispiel config/campaign.json:
  {"active": true, "name": "GTA VI Logo", "logo": "config/campaign/logo.png",
   "logo_pos": "top-right", "logo_width": 0.22, "hashtags": "#clipup #gta6", "game": "Grand Theft Auto VI"}
Ist "active" false oder fehlt die Datei, ändert sich nichts.
"""
from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load() -> dict:
    p = Path(os.getenv("CAMPAIGN_FILE", ROOT / "config/campaign.json"))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("active") else {}


def logo_path() -> Path | None:
    c = load()
    if not c.get("logo"):
        return None
    p = Path(c["logo"])
    p = p if p.is_absolute() else ROOT / p
    return p if p.is_file() else None


def hashtags() -> str:
    return str(load().get("hashtags", "")).strip()


def game() -> str:
    return str(load().get("game", "")).strip()


def paste_logo(img, width: int, height: int) -> None:
    """Logo (PNG mit Transparenz) auf ein RGBA-Overlay-Bild setzen."""
    p = logo_path()
    if not p:
        return
    from PIL import Image
    c = load()
    logo = Image.open(p).convert("RGBA")
    w = max(40, int(width * float(c.get("logo_width", 0.22))))
    logo = logo.resize((w, max(1, int(logo.height * w / logo.width))), Image.LANCZOS)
    m = int(width * 0.03)
    pos = c.get("logo_pos", "top-right")
    x = {"top-left": m, "bottom-left": m, "center": (width - logo.width) // 2}.get(pos, width - logo.width - m)
    y = m if pos.startswith("top") else (height - logo.height) // 2 if pos == "center" else int(height * 0.70) - logo.height
    img.alpha_composite(logo, (x, y))
