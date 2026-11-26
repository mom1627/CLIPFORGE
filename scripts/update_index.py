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


def release_assets() -> list[dict] | None:
    """Dateien im Release; None = nicht abrufbar (dann nichts aus der Liste entfernen)."""
    try:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/{TAG}"], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout).get("assets", []) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def merge(index: dict, rows: list[dict], assets: dict, camp_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        f = r.get("file")
        if not f:
            continue
        ch = r.get("streamer") or r.get("channel") or streamer_of(f)
        hook = (r.get("hook") or "").split(" | ")[0]
        e = index.get(f, {})
        if hook:
            e["hook"] = hook
        for k in ("quality", "game"):
            if r.get(k) not in (None, ""):
                e[k] = r[k]
        e.update({"file": f, "streamer": ch, "score": float(r.get("score") or e.get("score") or 0),
                  "campaign": r.get("campaign", camp_name if camp_name != "auto" else "") or e.get("campaign", ""),
                  "caption": publisher.build_caption(ch, hook, tags=os.getenv("CAPTION_TAGS") or None),
                  "source": r.get("vod_link") or e.get("source", ""),
                  "added": e.get("added") or (assets.get(f) or {}).get("created_at") or now})
        if f in assets:
            e["url"], e["bytes"] = assets[f]["browser_download_url"], assets[f]["size"]
        index[f] = e


def fix_captions(index: dict) -> None:
    """Beschreibung immer passend zur Kampagne (Pflicht-Hashtags); Lacy-Clips gehören zur Lacy-Kampagne."""
    old = os.environ.get("CAMPAIGN")
    try:
        for c in index.values():
            camp = c.get("campaign") or ("lacy" if c.get("streamer") == "lacy" else "")
            c["campaign"] = camp
            os.environ["CAMPAIGN"] = camp
            head = (c.get("caption") or "").split("\n\n")[0]
            if "rastet" in head or not head.strip():
                head = ""
            if camp:
                import captions
                head = captions.pick_hook(c.get("streamer", ""), c["file"], "en", fresh=False)
            c["caption"] = publisher.build_caption(c.get("streamer", ""), head)
    finally:
        if old is None:
            os.environ.pop("CAMPAIGN", None)
        else:
            os.environ["CAMPAIGN"] = old


def rank_key(c: dict) -> tuple:
    """Bester Clip zuerst: Reaktion/Drama im Clip (quality), dann Chat-/Ton-Spitze, dann neuer."""
    return (float(c.get("quality") or 0), float(c.get("score") or 0), str(c.get("added", "")))


def best_only(index: dict, keep: int, hours: float, now: datetime | None = None) -> tuple[dict, list[str]]:
    """Nur die besten 'keep' Clips behalten: aus den letzten 'hours' Stunden die besten; reicht das nicht,
    mit den neuesten auffüllen. Rückgabe: (behaltene Clips, zu löschende Dateinamen)."""
    if keep <= 0 or len(index) <= keep:
        return index, []
    now = now or datetime.now(timezone.utc)

    def age_h(c):
        try:
            t = datetime.fromisoformat(str(c.get("added", "")).replace("Z", "+00:00"))
            return (now - t).total_seconds() / 3600
        except ValueError:
            return 10**9
    recent = sorted((c for c in index.values() if age_h(c) <= hours), key=rank_key, reverse=True)
    rest = sorted((c for c in index.values() if age_h(c) > hours), key=lambda c: str(c.get("added", "")), reverse=True)
    kept = (recent + rest)[:keep]
    names = {c["file"] for c in kept}
    return {k: v for k, v in index.items() if k in names}, [k for k in index if k not in names]


def delete_assets(names: list[str]) -> None:
    for n in names:
        r = subprocess.run(["gh", "release", "delete-asset", TAG, n, "-R", REPO, "-y"],
                           capture_output=True, text=True, timeout=60)
        print("Gelöscht (nicht unter den besten):" if r.returncode == 0 else "Löschen fehlgeschlagen:", n)


def make_preview(src: Path, dest: Path) -> bool:
    """Kleine Abspiel-Version (540p) fürs Handy; die volle 1080p-Datei bleibt zum Herunterladen."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-vf", "scale=540:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest)],
                       capture_output=True, timeout=300)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000


def ensure_previews(index: dict, limit: int) -> None:
    """Clips ohne Vorschau: (lokal oder aus dem Release) verkleinern und zu Cloudinary hochladen.
    GitHub liefert Release-Dateien als Download aus – Safari (iPhone) spielt sie nicht im Player ab."""
    import tempfile
    if not (os.getenv("CLOUDINARY_CLOUD_NAME") and os.getenv("CLOUDINARY_UPLOAD_PRESET")):
        print("Vorschau übersprungen: Cloudinary nicht eingerichtet")
        return
    todo = [c for c in sorted(index.values(), key=lambda c: c.get("added", ""), reverse=True) if not c.get("preview")][:limit]
    with tempfile.TemporaryDirectory(prefix="prev_") as td:
        for c in todo:
            src = OUT / c["file"]
            if not src.exists():
                dl = subprocess.run(["gh", "release", "download", TAG, "-R", REPO, "-p", c["file"], "-D", td, "--clobber"],
                                    capture_output=True, timeout=300)
                src = Path(td) / c["file"]
                if dl.returncode or not src.exists():
                    continue
            prev = Path(td) / ("prev_" + c["file"])
            try:
                if make_preview(src, prev):
                    c["preview"] = publisher.host_video(prev)
                    print("Vorschau:", c["file"])
            except (publisher.PublishError, OSError, subprocess.TimeoutExpired) as exc:
                print("Vorschau fehlgeschlagen:", c["file"], exc)
            finally:
                prev.unlink(missing_ok=True)
                if src.parent == Path(td):
                    src.unlink(missing_ok=True)


def main() -> int:
    index = {}
    if INDEX.exists():
        index = {c["file"]: c for c in json.loads(INDEX.read_text(encoding="utf-8")).get("clips", [])}
    if len(sys.argv) > 2 and sys.argv[1] == "--merge":  # eigene Einträge (z. B. nach Push-Konflikt) übernehmen
        for c in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")).get("clips", []):
            old = dict(index.get(c["file"], {}))
            if c.get("asset_updated") and c.get("asset_updated") != old.get("asset_updated"):
                old.pop("preview", None)  # neu geschnittene Datei: alte Vorschau verwerfen
            index[c["file"]] = {**old, **{k: v for k, v in c.items() if v not in ("", None)}}
    listed = release_assets()
    assets = {a["name"]: a for a in (listed or []) if a["name"].endswith(".mp4")}
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
        e = index[name]
        if e.get("asset_updated") and e["asset_updated"] != a.get("updated_at"):
            e.pop("preview", None)  # Datei wurde neu geschnitten -> neue Vorschau
        e["asset_updated"] = a.get("updated_at", "")
        e["bytes"] = a["size"]
    index = {k: v for k, v in index.items() if k in assets or listed is None}  # gelöschte Assets entfernen (auch alle)
    hidden_file = ROOT / "docs/hidden.json"  # nicht zum Hochladen geeignet (Nacktheit, 50 s, kaputte Facecam …)
    hidden = set(json.loads(hidden_file.read_text(encoding="utf-8"))) if hidden_file.exists() else set()
    index = {k: v for k, v in index.items() if k not in hidden}
    # ersetzte Live-Clips (neu geschnitten unter neuem Namen) aus der Liste nehmen
    for r in rows:
        if r.get("replaces") and r["replaces"] in index and r.get("file") in index:
            index.pop(r["replaces"], None)
    keep = int(os.getenv("KEEP_BEST", "0") or 0)  # z. B. 3: App zeigt nur die 3 besten, Rest wird gelöscht
    if keep and not (len(sys.argv) > 1 and sys.argv[1] == "--merge"):
        index, drop = best_only(index, keep, float(os.getenv("KEEP_HOURS", "24")))
        if drop and assets:
            delete_assets([d for d in drop if d in assets])
    elif keep:  # --merge nach Push-Konflikt: nur filtern, gelöscht wurde schon
        index, _ = best_only(index, keep, float(os.getenv("KEEP_HOURS", "24")))
    fix_captions(index)
    ensure_previews(index, int(os.getenv("PREVIEW_MAX", "25")))
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "repo": REPO, "clips": sorted(index.values(), key=lambda c: c.get("added", ""),
                                                               reverse=True)}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"Index: {len(index)} Clips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
