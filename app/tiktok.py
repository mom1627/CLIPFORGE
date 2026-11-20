"""TikTok-Anbindung der Mac-App: Login (OAuth mit PKCE) und Upload als Entwurf in die TikTok-Inbox.

Warum Entwurf: Mit dem Scope video.upload landet der Clip in deiner TikTok-App (Benachrichtigung),
dort setzt du Beschreibung/Sound und tippst auf Posten. Direktes Veroeffentlichen (video.publish)
ist bei nicht geprueften TikTok-Apps nur als "privat" erlaubt, bis TikTok die App prueft (Audit).
Doku: https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_URL = os.getenv("TIKTOK_AUTH_URL", "https://www.tiktok.com/v2/auth/authorize/")
API = os.getenv("TIKTOK_API_BASE", "https://open.tiktokapis.com")
SCOPES = "user.info.basic,video.upload"
MAX_SINGLE_CHUNK = 64 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


class TikTok:
    def __init__(self, home: Path, redirect_uri: str):
        self.token_path = home / "tiktok_token.json"
        self.redirect_uri = redirect_uri
        self._pending: dict[str, str] = {}  # state -> code_verifier

    # ---------- Konfiguration ----------
    @property
    def client_key(self) -> str:
        return os.getenv("TIKTOK_CLIENT_KEY", "")

    @property
    def client_secret(self) -> str:
        return os.getenv("TIKTOK_CLIENT_SECRET", "")

    def configured(self) -> bool:
        return bool(self.client_key and self.client_secret)

    def token(self) -> dict:
        if self.token_path.exists():
            try:
                return json.loads(self.token_path.read_text(encoding="utf-8"))
            except ValueError:
                return {}
        return {}

    def connected(self) -> bool:
        t = self.token()
        return bool(t.get("access_token")) and t.get("refresh_expires_at", 0) > time.time()

    def _save(self, data: dict):
        now = time.time()
        data["expires_at"] = now + int(data.get("expires_in", 0)) - 60
        data["refresh_expires_at"] = now + int(data.get("refresh_expires_in", 0)) - 60
        self.token_path.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(self.token_path, 0o600)

    def disconnect(self):
        self.token_path.unlink(missing_ok=True)

    # ---------- HTTP ----------
    def _post_form(self, path: str, form: dict) -> dict:
        req = urllib.request.Request(API + path, data=urllib.parse.urlencode(form).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        return self._send(req)

    def _post_json(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.access_token()}",
                                              "Content-Type": "application/json; charset=UTF-8"})
        return self._send(req)

    @staticmethod
    def _send(req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                data = json.load(e)
            except ValueError:
                data = {}
            err = data.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else data.get("error_description") or str(err)
            raise TikTokError(f"TikTok {e.code}: {msg or 'Fehler'}") from None

    # ---------- Login ----------
    def login_url(self) -> str:
        if not self.configured():
            raise TikTokError("TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET fehlen in ~/CLIPFORGE/.env")
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if os.getenv("TIKTOK_PKCE_HEX", "1") == "1":  # Login Kit for Desktop erwartet SHA256 als Hex (getestet: Base64 wird abgelehnt)
            challenge = hashlib.sha256(verifier.encode()).hexdigest()
        state = secrets.token_urlsafe(16)
        self._pending[state] = verifier
        q = {"client_key": self.client_key, "scope": SCOPES, "response_type": "code",
             "redirect_uri": self.redirect_uri, "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        return AUTH_URL + "?" + urllib.parse.urlencode(q)

    def finish_login(self, code: str, state: str):
        verifier = self._pending.pop(state, None)
        if not verifier:
            raise TikTokError("Login abgelaufen oder ungültig, bitte erneut verbinden")
        data = self._post_form("/v2/oauth/token/", {
            "client_key": self.client_key, "client_secret": self.client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": self.redirect_uri, "code_verifier": verifier})
        if not data.get("access_token"):
            raise TikTokError(data.get("error_description") or "Kein Zugriffstoken erhalten")
        if "video.upload" not in data.get("scope", ""):
            raise TikTokError("TikTok hat 'video.upload' nicht freigegeben – in der TikTok-Developer-App das Produkt "
                              "'Content Posting API' hinzufügen und den Scope aktivieren")
        self._save(data)

    def access_token(self) -> str:
        t = self.token()
        if not t.get("access_token"):
            raise TikTokError("TikTok ist nicht verbunden")
        if t.get("expires_at", 0) > time.time():
            return t["access_token"]
        if t.get("refresh_expires_at", 0) < time.time():
            raise TikTokError("TikTok-Anmeldung abgelaufen, bitte neu verbinden")
        data = self._post_form("/v2/oauth/token/", {
            "client_key": self.client_key, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
        if not data.get("access_token"):
            raise TikTokError("Token-Erneuerung fehlgeschlagen, bitte neu verbinden")
        self._save(data)
        return data["access_token"]

    # ---------- Upload ----------
    def upload_draft(self, video: Path, wait_s: int = 120) -> dict:
        """Laedt die MP4 als Entwurf in die TikTok-Inbox. Gibt publish_id und Status zurueck."""
        size = video.stat().st_size
        if size > MAX_SINGLE_CHUNK:
            raise TikTokError("Clip größer als 64 MB – bitte kleiner rendern")
        init = self._post_json("/v2/post/publish/inbox/video/init/", {"source_info": {
            "source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}})
        err = (init.get("error") or {}).get("code", "ok")
        if err != "ok":
            raise TikTokError(f"TikTok-Init: {(init.get('error') or {}).get('message', err)}")
        data = init.get("data") or {}
        url, pid = data.get("upload_url"), data.get("publish_id")
        if not url or not pid:
            raise TikTokError("TikTok gab keine Upload-Adresse zurück")
        req = urllib.request.Request(url, data=video.read_bytes(), method="PUT", headers={
            "Content-Type": "video/mp4", "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                if r.status not in (200, 201, 206):
                    raise TikTokError(f"Upload HTTP {r.status}")
        except urllib.error.HTTPError as e:
            raise TikTokError(f"Upload HTTP {e.code}") from None
        status = "PROCESSING_UPLOAD"
        deadline = time.time() + wait_s
        while time.time() < deadline:
            st = self._post_json("/v2/post/publish/status/fetch/", {"publish_id": pid})
            status = (st.get("data") or {}).get("status", status)
            if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                break
            if status == "FAILED":
                raise TikTokError("TikTok: Verarbeitung fehlgeschlagen ("
                                  + str((st.get("data") or {}).get("fail_reason", "unbekannt")) + ")")
            time.sleep(3)
        return {"publish_id": pid, "status": status}
