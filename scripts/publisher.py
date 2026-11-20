"""Öffentlich auf TikTok posten über OmniSocials (offiziell geprüfte TikTok-Anbindung).

Wird von der Mac-App (Knopf „Veröffentlichen“) und von GitHub Actions (automatisch) benutzt.
Braucht OMNISOCIALS_API_KEY (https://app.omnisocials.com/settings/api) und ein in OmniSocials
verbundenes TikTok-Konto. Nur Standardbibliothek.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

API = os.getenv("OMNISOCIALS_BASE_URL", "https://api.omnisocials.com/v1")
MAX_BYTES = 50 * 1024 * 1024
DEFAULT_TAGS = "#gta6 #gtavi #gta6gameplay #twitchclips #gaming #fyp #viral"


class PublishError(RuntimeError):
    pass


def _key() -> str:
    k = os.getenv("OMNISOCIALS_API_KEY", "")
    if not k:
        raise PublishError("OMNISOCIALS_API_KEY fehlt (in ~/CLIPFORGE/.env bzw. als GitHub-Secret)")
    return k


def _call(method: str, path: str, body: dict | None = None, timeout: int = 300) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = (json.load(e).get("error") or {})
        except ValueError:
            err = {}
        raise PublishError(f"OmniSocials {e.code}: {err.get('message') or err.get('code') or 'Fehler'}") from None
    if isinstance(out, dict) and out.get("error"):
        raise PublishError(f"OmniSocials: {out['error'].get('message', out['error'])}")
    return out.get("data", out) if isinstance(out, dict) else out


def configured() -> bool:
    return bool(os.getenv("OMNISOCIALS_API_KEY"))


def tiktok_channel() -> str:
    """ID des verbundenen TikTok-Kontos in OmniSocials (oder OMNISOCIALS_TIKTOK_ID)."""
    if os.getenv("OMNISOCIALS_TIKTOK_ID"):
        return os.environ["OMNISOCIALS_TIKTOK_ID"]
    accounts = _call("GET", "/accounts")
    for a in accounts if isinstance(accounts, list) else []:
        if str(a.get("platform", "")).lower() == "tiktok" and str(a.get("status", "active")).lower() in ("active", "connected", ""):
            return str(a["id"])
    raise PublishError("Kein TikTok-Konto in OmniSocials verbunden")


def build_caption(channel: str, hook: str = "", tags: str | None = None) -> str:
    """Beschreibung mit Hook, Quelle (Streamer) und Hashtags; max. 2200 Zeichen (TikTok)."""
    tags = (tags if tags is not None else os.getenv("CAPTION_TAGS", DEFAULT_TAGS)).strip()
    chan_tag = "#" + re.sub(r"[^a-z0-9_]", "", channel.lower()) if channel else ""
    if chan_tag and chan_tag not in tags.split():
        tags = f"{tags} {chan_tag}".strip()
    head = (hook or f"{channel} rastet komplett aus 😭").strip()
    src = f"🎮 Streamer: {channel} (Twitch)" if channel else ""
    return "\n\n".join(p for p in (head, src, tags) if p)[:2200]


def publish(video: Path, caption: str, dry_run: bool = False) -> dict:
    """Lädt die MP4 hoch und veröffentlicht sie sofort öffentlich auf TikTok."""
    size = video.stat().st_size
    if size > MAX_BYTES:
        raise PublishError("Clip größer als 50 MB")
    channel = tiktok_channel()
    if dry_run:
        return {"dry_run": True, "channel": channel, "bytes": size}
    media = _call("POST", "/media/upload-from-base64", {
        "data": base64.b64encode(video.read_bytes()).decode(), "mime_type": "video/mp4", "filename": video.name})
    mid = media.get("id") if isinstance(media, dict) else None
    if not mid:
        raise PublishError("Upload zu OmniSocials lieferte keine Media-ID")
    post = _call("POST", "/posts/create-and-publish", {
        "content": caption, "channels": [channel], "type": "reel", "media_ids": [mid],
        "tiktok": {"privacy_level": os.getenv("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")}})
    return {"post_id": post.get("id"), "status": post.get("status"), "url": post.get("app_url", "")}
