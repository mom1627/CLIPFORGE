"""Aktive Clipping-Kampagne (config/campaigns/<name>.json, Auswahl CAMPAIGN=<name>): Logo, Pflicht-Hashtags, Pflicht-Spiel.

Beispiel config/campaigns/<name>.json (Auswahl mit CAMPAIGN=<name>):
  {"active": true, "name": "GTA VI Logo", "logo": "config/campaign/logo.png",
   "logo_pos": "top-right", "logo_width": 0.22, "hashtags": "#clipup #gta6", "game": "Grand Theft Auto VI"}
Ist "active" false oder fehlt die Datei, ändert sich nichts.
"""
from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load() -> dict:
    """Kampagne über CAMPAIGN=<name> (config/campaigns/<name>.json) oder CAMPAIGN_FILE wählen.
    Ohne Angabe ist keine Kampagne aktiv – so landet nie ein fremdes Logo im falschen Clip."""
    name = os.getenv("CAMPAIGN", "").strip().lower()
    default = ROOT / "config/campaigns" / f"{name}.json" if name else ROOT / "config/campaigns/_none.json"
    p = Path(os.getenv("CAMPAIGN_FILE", default))
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


def title() -> str:
    """Fester, sachlicher Titel (Kampagnen mit Verbot irreführender Titel)."""
    return str(load().get("title", "")).strip()


def channels() -> list[str]:
    return [str(c).lower() for c in load().get("channels", [])]


def hashtags() -> str:
    return str(load().get("hashtags", "")).strip()


def game() -> str:
    return str(load().get("game", "")).strip()


def subtitle_y(height: int, default: int) -> int:
    """Untertitel über das Logo schieben, damit es nie verdeckt wird (Kampagnen-Regel)."""
    c = load()
    if logo_path() and str(c.get("logo_pos", "")).startswith("bottom"):
        return min(default, int(height * 0.66))
    return default


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
    if pos.startswith("top"):
        y = m
    elif pos == "center":
        y = (height - logo.height) // 2
    else:  # unten bündig wie im Kampagnen-Beispiel
        y = height - logo.height - int(height * 0.004)
        if pos == "bottom-right":
            x = width - logo.width - int(width * 0.01)
    img.alpha_composite(logo, (x, y))
