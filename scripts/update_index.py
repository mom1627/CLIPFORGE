#!/usr/bin/env python3
"""Clip-Übersicht für die Handy-App (docs/clips.json, GitHub Pages).

Führt zusammen: bisherige docs/clips.json + Berichte dieses Laufs (output/vod_report.json,
output/monitor_report.json) + alle MP4s im Release "clips". Pro Clip: Link, Streamer, Punktzahl,
Kampagne und fertige Beschreibung (Pflicht-Hashtags der Kampagne inklusive).
"""
from __future__ import annotations
import json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publisher, campaign  # noqa: E402

INDEX = ROOT / "docs/clips.json"
OUT = Path(os.getenv("CLIPFORGE_OUTPUT", "output"))
REPO = os.getenv("GITHUB_REPOSITORY", "mom1627/CLIPFORGE")
TAG = os.getenv("RELEASE_TAG", "clips")


def streamer_of(name: str) -> str:
    m = re.match(r"(?:clipforge_)?(.+?)_\d{8}_\d{6}\.mp4$", name)
    return m.group(1) if m else ""


def release_assets() -> list[dict]:
    try:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/{TAG}"], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout).get("assets", []) if r.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def merge(index: dict, rows: list[dict], assets: dict, camp_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        f = r.get("file")
        if not f:
            continue
        ch = r.get("streamer") or r.get("channel") or streamer_of(f)
        hook = (r.get("hook") or "").split(" | ")[0]
        e = index.get(f, {})
        e.update({"file": f, "streamer": ch, "score": float(r.get("score") or e.get("score") or 0),
                  "campaign": camp_name or e.get("campaign", ""),
                  "caption": publisher.build_caption(ch, hook, tags=os.getenv("CAPTION_TAGS") or None),
                  "source": r.get("vod_link") or e.get("source", ""),
                  "added": e.get("added") or (assets.get(f) or {}).get("created_at") or now})
        if f in assets:
            e["url"], e["bytes"] = assets[f]["browser_download_url"], assets[f]["size"]
        index[f] = e


def main() -> int:
    index = {}
    if INDEX.exists():
        index = {c["file"]: c for c in json.loads(INDEX.read_text(encoding="utf-8")).get("clips", [])}
    assets = {a["name"]: a for a in release_assets() if a["name"].endswith(".mp4")}
    camp = os.getenv("CAMPAIGN", "").strip().lower()
    rows = []
    for rep in ("vod_report.json", "monitor_report.json"):
        p = OUT / rep
        if p.exists():
            rows += json.loads(p.read_text(encoding="utf-8")).get("clips", [])
    merge(index, rows, assets, camp)
    for name, a in assets.items():  # ältere Clips ohne Bericht trotzdem zeigen
        if name not in index:
            index[name] = {"file": name, "streamer": streamer_of(name), "score": 0, "campaign": "",
                           "caption": publisher.build_caption(streamer_of(name)), "source": "",
                           "added": a.get("created_at", ""), "url": a["browser_download_url"], "bytes": a["size"]}
        else:
            index[name].setdefault("url", a["browser_download_url"])
    index = {k: v for k, v in index.items() if k in assets or not assets}  # gelöschte Assets entfernen
    hidden_file = ROOT / "docs/hidden.json"  # nicht zum Hochladen geeignet (Nacktheit, 50 s, kaputte Facecam …)
    hidden = set(json.loads(hidden_file.read_text(encoding="utf-8"))) if hidden_file.exists() else set()
    index = {k: v for k, v in index.items() if k not in hidden}
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "repo": REPO, "clips": sorted(index.values(), key=lambda c: c.get("added", ""),
                                                               reverse=True)}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"Index: {len(index)} Clips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
