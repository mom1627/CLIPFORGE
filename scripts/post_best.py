#!/usr/bin/env python3
"""Am Ende eines Cloud-Laufs: die besten Clips (höchste Punktzahl) öffentlich über Buffer posten.

Liest output/monitor_report.json (schreibt monitor.py laufend), nimmt nur Clips mit genau 60 s,
sortiert nach Punktzahl (Ton-Ausschlag in dB über dem normalen Pegel) und plant die besten
POST_BEST (Standard 5) mit POST_GAP_MINUTES Abstand ein. Ohne AUTO_PUBLISH=1 oder ohne
Zugangsdaten wird nur angezeigt, was gepostet würde.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publisher

CLIP_LEN = 60.0


def duration(mp4: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def pick_best(clips: list[dict], out: Path, n: int) -> list[dict]:
    """Die n besten noch nicht geposteten Clips mit genau 60 s, beste zuerst."""
    ok = [c for c in clips if not c.get("posted") and (out / c["file"]).exists()
          and abs(duration(out / c["file"]) - CLIP_LEN) <= 0.5]
    return sorted(ok, key=lambda c: float(c.get("score") or 0), reverse=True)[:max(0, n)]


def main() -> int:
    out = Path(os.getenv("CLIPFORGE_OUTPUT", "output"))
    rep_path = out / "monitor_report.json"
    if not rep_path.exists():
        print("Kein Bericht – in diesem Lauf entstanden keine Clips.")
        return 0
    report = json.loads(rep_path.read_text())
    n = min(int(os.getenv("POST_BEST", "5")), int(os.getenv("MAX_POSTS", "5")))
    gap = int(os.getenv("POST_GAP_MINUTES", "60"))
    best = pick_best(report.get("clips", []), out, n)
    print(f"{len(report.get('clips', []))} Clips im Lauf, {len(best)} ausgewählt:")
    for i, c in enumerate(best, 1):
        print(f"  {i}. {c['file']}  (Punktzahl {c.get('score', 0)})")
    live = os.getenv("AUTO_PUBLISH") == "1" and publisher.configured()
    if not live:
        why = "AUTO_PUBLISH ist nicht 1" if os.getenv("AUTO_PUBLISH") != "1" else "fehlt: " + ", ".join(publisher.missing())
        print(f"Nicht gepostet ({why}). Nur Vorschau.")
        return 0
    failed = 0
    for i, c in enumerate(best):
        try:
            r = publisher.publish(out / c["file"], publisher.build_caption(c.get("channel", "")),
                                  delay_minutes=3 + gap * i)
            c["posted"] = r.get("post_id") or "ok"
            print(f"Geplant: {c['file']} um {r.get('due')}", flush=True)
        except publisher.PublishError as exc:
            failed += 1
            c["posted"] = ""
            print(f"Posten fehlgeschlagen ({c['file']}): {exc}", flush=True)
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if best and failed == len(best) else 0


if __name__ == "__main__":
    sys.exit(main())
