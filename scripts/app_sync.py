#!/usr/bin/env python3
"""Neuen Clip SOFORT in der Handy-App zeigen: Liste neu bauen (nur die besten KEEP_BEST behalten,
Rest aus dem Release löschen) und docs/clips.json pushen – konfliktfrei wie in den Workflows.

Läuft nur in GitHub Actions (GITHUB_ACTIONS=true); lokal passiert nichts."""
from __future__ import annotations
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def sync(message: str = "Clip-Übersicht aktualisiert [skip ci]") -> bool:
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("APP_SYNC", "1") == "0":
        return False
    py = sys.executable
    branch = os.getenv("GITHUB_REF_NAME", "main")
    r = subprocess.run([py, "scripts/update_index.py"], cwd=ROOT, capture_output=True, text=True, timeout=1500)
    print(r.stdout[-400:], r.stderr[-400:], flush=True)
    mine = Path(tempfile.gettempdir()) / "clipforge_mine.json"
    shutil.copy(ROOT / "docs/clips.json", mine)
    _git("config", "user.name", "clipforge-bot")
    _git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for i in range(1, 6):
        _git("fetch", "-q", "origin", branch)
        _git("reset", "-q", "--hard", f"origin/{branch}")
        subprocess.run([py, "scripts/update_index.py", "--merge", str(mine)], cwd=ROOT,
                       capture_output=True, text=True, timeout=1500)
        _git("add", "docs/clips.json")
        if _git("diff", "--cached", "--quiet").returncode == 0:
            return True
        _git("commit", "-q", "-m", message)
        if _git("push", "-q", "origin", f"HEAD:{branch}").returncode == 0:
            print("App aktualisiert (sofort).", flush=True)
            return True
        time.sleep(i * 7)
    return False


if __name__ == "__main__":
    sys.exit(0 if sync() else 1)
