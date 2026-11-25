"""Öffentlich auf TikTok posten über Buffer (kostenloser Tarif, offiziell geprüfte TikTok-Anbindung).

Ablauf: Clip per *unsigned* Upload zu Cloudinary (kostenlos, kein geheimer Schlüssel nötig) ->
öffentlicher HTTPS-Link -> Buffer-API `createPost` für den verbundenen TikTok-Kanal.

Einstellungen (in ~/CLIPFORGE/.env bzw. als GitHub-Secret/Variable):
  BUFFER_API_KEY            geheim – https://publish.buffer.com/settings/api (trägt der Nutzer selbst ein)
  CLOUDINARY_CLOUD_NAME     nicht geheim – Name des Cloudinary-Kontos
  CLOUDINARY_UPLOAD_PRESET  nicht geheim – Name eines *unsigned* Upload-Presets
  BUFFER_CHANNEL_ID         optional – sonst wird der erste TikTok-Kanal genommen
Nur Standardbibliothek. TikTok erlaubt über APIs insgesamt ca. 15 Posts pro Konto und Tag.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUFFER_API = os.getenv("BUFFER_API_URL", "https://api.buffer.com")
CLOUDINARY_API = os.getenv("CLOUDINARY_API_URL", "https://api.cloudinary.com/v1_1")
MAX_BYTES = 100 * 1024 * 1024
# Laut Metricool (volta_ro, Nov 2026): Top-Videos hatten 4-5 kurze Tags (#gta6 #gtavi #viral + Streamer)
DEFAULT_TAGS = "#gta6 #gtavi #viral"
MAX_TAGS = 6
# Kommentare fehlten fast ganz (0 bei allen Clips) -> Frage am Ende lädt zum Kommentieren ein
CTA = ["Would you have done the same? 👇", "Rate this 1-10 👇", "Who was right here? 👇",
       "What would you do? 👇", "Funniest part? 👇", "Did he deserve that? 👇", "Be honest… 👇"]


class PublishError(RuntimeError):
    pass


def configured() -> bool:
    return all(os.getenv(k) for k in ("BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET"))


def missing() -> list[str]:
    return [k for k in ("BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET") if not os.getenv(k)]


# ---------- Buffer (GraphQL) ----------
def _gql(query: str, timeout: int = 60) -> dict:
    key = os.getenv("BUFFER_API_KEY", "")
    if not key:
        raise PublishError("BUFFER_API_KEY fehlt (in ~/CLIPFORGE/.env bzw. als GitHub-Secret)")
    req = urllib.request.Request(BUFFER_API, data=json.dumps({"query": query}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise PublishError(f"Buffer {e.code}: {e.read()[:200].decode(errors='ignore')}") from None
    if out.get("errors"):
        raise PublishError("Buffer: " + "; ".join(str(x.get("message", x)) for x in out["errors"])[:300])
    return out.get("data") or {}


def _s(text: str) -> str:
    """String-Literal für GraphQL (JSON-Escaping ist gültiges GraphQL)."""
    return json.dumps(text, ensure_ascii=False)


def tiktok_channel() -> str:
    if os.getenv("BUFFER_CHANNEL_ID"):
        return os.environ["BUFFER_CHANNEL_ID"]
    orgs = (_gql("query { account { organizations { id name } } }").get("account") or {}).get("organizations") or []
    for org in orgs:
        chans = _gql("query { channels(input: {organizationId: %s}) { id service name isQueuePaused } }"
                     % _s(org["id"])).get("channels") or []
        for c in chans:
            if str(c.get("service", "")).lower() == "tiktok":
                return str(c["id"])
    raise PublishError("Kein TikTok-Kanal in Buffer verbunden")


# ---------- Cloudinary (öffentlicher Link) ----------
def host_video(video: Path) -> str:
    cloud, preset = os.getenv("CLOUDINARY_CLOUD_NAME", ""), os.getenv("CLOUDINARY_UPLOAD_PRESET", "")
    if not cloud or not preset:
        raise PublishError("CLOUDINARY_CLOUD_NAME / CLOUDINARY_UPLOAD_PRESET fehlen")
    b = uuid.uuid4().hex
    head = (f"--{b}\r\nContent-Disposition: form-data; name=\"upload_preset\"\r\n\r\n{preset}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{video.name}\"\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode()
    body = head + video.read_bytes() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{CLOUDINARY_API}/{cloud}/video/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = (json.load(e).get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        raise PublishError(f"Cloudinary {e.code}: {msg or 'Upload fehlgeschlagen'}") from None
    url = out.get("secure_url", "")
    if not url.startswith("https://"):
        raise PublishError("Cloudinary lieferte keinen HTTPS-Link")
    return url


# ---------- Beschreibung ----------
def build_caption(channel: str, hook: str = "", tags: str | None = None) -> str:
    """Beschreibung mit Hook, Quelle (Streamer) und Hashtags; max. 2200 Zeichen (TikTok)."""
    tags = (tags if tags is not None else os.getenv("CAPTION_TAGS", DEFAULT_TAGS)).strip()
    try:
        import campaign  # Pflicht-Hashtags der aktiven Kampagne immer vorne
        need = [t for t in campaign.hashtags().split() if t.lower() not in tags.lower().split()]
        tags = " ".join(need + tags.split())
    except ImportError:
        pass
    chan_tag = "#" + re.sub(r"[^a-z0-9_]", "", channel.lower()) if channel else ""
    if chan_tag and chan_tag.lower() not in tags.lower().split():
        tags = f"{tags} {chan_tag}".strip()
    try:
        import captions
        name = captions.display_name(channel)
    except ImportError:
        name = channel
    tags = " ".join(dict.fromkeys(tags.split()).keys())
    words = tags.split()
    if len(words) > MAX_TAGS:  # Pflicht-Tags (vorne) und Streamer-Tag behalten, Rest kürzen
        keep = words[:MAX_TAGS - 1] + ([chan_tag] if chan_tag and chan_tag not in words[:MAX_TAGS - 1] else [words[MAX_TAGS - 1]])
        tags = " ".join(keep)
    head = (hook or f"{name} can't believe this 😭").strip()
    if channel and name.lower() not in head.lower():
        head = f"{head} – {name}"  # Name für Suche und Kampagnen-Regeln (z. B. Lacy)
    import zlib
    cta = CTA[zlib.crc32(head.encode()) % len(CTA)]
    return "\n\n".join(p for p in (head, cta, tags) if p)[:2200]


# ---------- Posten ----------
def publish(video: Path, caption: str, dry_run: bool = False, delay_minutes: int = 3) -> dict:
    """Clip hosten und über Buffer in wenigen Minuten öffentlich auf TikTok posten."""
    size = video.stat().st_size
    if size > MAX_BYTES:
        raise PublishError("Clip größer als 100 MB")
    channel = tiktok_channel()
    if dry_run:
        return {"dry_run": True, "channel": channel, "bytes": size}
    url = host_video(video)
    due = (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    q = ("mutation { createPost(input: {text: %s, channelId: %s, schedulingType: automatic, mode: customScheduled, "
         "dueAt: %s, assets: [{video: {url: %s, metadata: {thumbnailOffset: 1500}}}]}) "
         "{ ... on PostActionSuccess { post { id } } ... on MutationError { message } } }"
         % (_s(caption), _s(channel), _s(due), _s(url)))
    res = _gql(q).get("createPost") or {}
    if res.get("message"):
        raise PublishError("Buffer: " + res["message"])
    pid = (res.get("post") or {}).get("id")
    if not pid:
        raise PublishError("Buffer lieferte keine Post-ID")
    return {"post_id": pid, "status": "geplant", "due": due, "video_url": url, "at": time.time()}
