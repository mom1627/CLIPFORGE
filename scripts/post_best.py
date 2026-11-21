#!/usr/bin/env python3
"""Am Ende eines Cloud-Laufs: die besten Clips (höchste Punktzahl) öffentlich über Buffer posten.

Liest output/monitor_report.json (schreibt monitor.py laufend), nimmt nur Clips mit genau 60 s,
prüft auf Nacktheit (safety.py), sortiert nach Punktzahl (Ton-Ausschlag in dB über dem normalen Pegel) und plant die besten
POST_BEST (Standard 5) mit POST_GAP_MINUTES Abstand ein. Ohne AUTO_PUBLISH=1 oder ohne
Zugangsdaten wird nur angezeigt, was gepostet würde.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publisher, safety

CLIP_LEN = 60.0


def slot_delays(n: int, now=None, slots: str | None = None, tz: str | None = None, gap: int = 60) -> list[int]:
    """Minuten bis zu den nächsten n Post-Zeitfenstern (POST_SLOTS, Stunden in POST_TZ).
    Standard laut Metricool-Auswertung von volta_ro: 10, 12, 16, 18, 20 Uhr (Berlin).
    POST_SLOTS leer -> alter Modus: alle 'gap' Minuten ab jetzt + 3."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    slots = os.getenv("POST_SLOTS", "10,12,16,18,20") if slots is None else slots
    hours = sorted({int(h) for h in slots.split(",") if h.strip().isdigit() and 0 <= int(h) < 24})
    if not hours:
        return [3 + gap * i for i in range(n)]
    zone = ZoneInfo(tz or os.getenv("POST_TZ", "Europe/Berlin"))
    now = (now or datetime.now(zone)).astimezone(zone)
    out, day = [], now.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(out) < n:
        for h in hours:
            t = day.replace(hour=h)
            if t >= now + timedelta(minutes=5) and len(out) < n:
                out.append(int((t - now).total_seconds() // 60))
        day += timedelta(days=1)
    return out


def duration(mp4: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def pick_best(clips: list[dict], out: Path, n: int, check=None) -> list[dict]:
    """Die n besten noch nicht geposteten Clips: genau 60 s, ohne Nacktheit, beste zuerst."""
    ok = [c for c in clips if not c.get("posted") and not c.get("unsafe") and (out / c["file"]).exists()
          and abs(duration(out / c["file"]) - CLIP_LEN) <= 0.5]
    check, best = check or safety.check, []
    for c in sorted(ok, key=lambda c: float(c.get("score") or 0), reverse=True):
        if len(best) >= n:
            break
        safe, why = check(out / c["file"])
        if not safe:
            c["unsafe"] = why
            print(f"  übersprungen: {c['file']} – {why}", flush=True)
            continue
        best.append(c)
    return best


def post_now(clip: dict, out: Path, report: dict, check=None, now: float | None = None) -> str:
    """POST_MODE=now: einen frischen Clip sofort einplanen (Abstand POST_GAP_MINUTES zum letzten Post,
    höchstens MAX_POSTS pro Lauf, nur 60 s, ohne Nacktheit). Gibt den Status als Text zurück."""
    import time
    if os.getenv("AUTO_PUBLISH") != "1" or not publisher.configured():
        return "nicht gepostet (AUTO_PUBLISH/Zugangsdaten)"
    posted = [c for c in report.get("clips", []) if c.get("posted")]
    if len(posted) >= int(os.getenv("MAX_POSTS", "5")):
        return "nicht gepostet (MAX_POSTS erreicht)"
    mp4 = out / clip["file"]
    if abs(duration(mp4) - CLIP_LEN) > 0.5:
        return "nicht gepostet (nicht 60 s)"
    safe, why = (check or safety.check)(mp4)
    if not safe:
        clip["unsafe"] = why
        return "nicht gepostet – " + why
    now = time.time() if now is None else now
    gap = int(os.getenv("POST_GAP_MINUTES", "60")) * 60
    dues = [float(c["due_ts"]) for c in posted if c.get("due_ts")]
    earliest = max(now + 180, max(dues) + gap) if dues else now + 180
    delay = max(3, int((earliest - now) // 60))
    try:
        r = publisher.publish(mp4, publisher.build_caption(clip.get("channel", "")), delay_minutes=delay)
    except publisher.PublishError as exc:
        return f"Posten fehlgeschlagen: {exc}"
    clip["posted"] = r.get("post_id") or "ok"
    clip["due_ts"] = now + delay * 60
    return f"geplant in {delay} min ({r.get('due')})"


def main() -> int:
    out = Path(os.getenv("CLIPFORGE_OUTPUT", "output"))
    rep_path = out / "monitor_report.json"
    if not rep_path.exists():
        print("Kein Bericht – in diesem Lauf entstanden keine Clips.")
        return 0
    report = json.loads(rep_path.read_text())
    already = sum(1 for c in report.get("clips", []) if c.get("posted"))
    n = max(0, min(int(os.getenv("POST_BEST", "5")), int(os.getenv("MAX_POSTS", "5")) - already))
    if os.getenv("POST_MODE", "end") == "now":
        print(f"POST_MODE=now: {already} Clips wurden schon während des Laufs eingeplant.")
    gap = int(os.getenv("POST_GAP_MINUTES", "60"))
    best = pick_best(report.get("clips", []), out, n)
    print(f"{len(report.get('clips', []))} Clips im Lauf, {len(best)} ausgewählt:")
    for i, c in enumerate(best, 1):
        print(f"  {i}. {c['file']}  (Punktzahl {c.get('score', 0)})")
    live = os.getenv("AUTO_PUBLISH") == "1" and publisher.configured()
    if not live:
        why = "AUTO_PUBLISH ist nicht 1" if os.getenv("AUTO_PUBLISH") != "1" else "fehlt: " + ", ".join(publisher.missing())
        print(f"Nicht gepostet ({why}). Nur Vorschau.")
        rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    failed = 0
    delays = slot_delays(len(best), gap=gap, slots="" if os.getenv("POST_MODE", "end") == "now" else None)
    for i, c in enumerate(best):
        try:
            r = publisher.publish(out / c["file"], publisher.build_caption(c.get("channel", "")),
                                  delay_minutes=delays[i])
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
