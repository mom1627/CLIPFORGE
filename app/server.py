"""CLIPFORGE Mac-App: lokaler Webserver mit Oberflaeche.
Start:  python3 app/server.py            -> http://127.0.0.1:8787
        python3 app/server.py --lan      -> auch fuer das iPhone im selben WLAN (mit Zugangscode)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manager import Manager  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"


def make_handler(mgr: Manager, token: str | None):
    class H(BaseHTTPRequestHandler):
        server_version = "CLIPFORGE"

        def log_message(self, *a):  # ruhige Konsole
            pass

        # ---- Hilfen ----
        def _auth(self) -> bool:
            if not token:
                return True
            q = parse_qs(urlparse(self.path).query)
            cookie = self.headers.get("Cookie", "")
            return q.get("k", [""])[0] == token or f"cf={token}" in cookie

        def _json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _file(self, path: Path, download: bool = False):
            if not path.is_file():
                return self._json({"error": "nicht gefunden"}, 404)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng and rng.startswith("bytes="):  # Safari/iPhone braucht Range fuer Video
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if a and b else size - 1
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        # ---- Routen ----
        def do_GET(self):
            u = urlparse(self.path)
            if not self._auth():
                return self._json({"error": "Zugangscode fehlt"}, 401)
            if u.path in ("/", "/index.html"):
                self.send_response(200)
                body = (STATIC / "index.html").read_bytes()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                if token:
                    self.send_header("Set-Cookie", f"cf={token}; Path=/; SameSite=Strict")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if u.path == "/api/state":
                return self._json(mgr.state())
            if u.path.startswith("/clips/"):
                name = unquote(u.path[len("/clips/"):])
                if "/" in name or ".." in name:
                    return self._json({"error": "ungültig"}, 400)
                return self._file(mgr.clips_dir / name, download="dl" in parse_qs(u.query))
            return self._json({"error": "nicht gefunden"}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            if not self._auth():
                return self._json({"error": "Zugangscode fehlt"}, 401)
            try:
                d = self._body()
                if u.path == "/api/channels":
                    return self._json({"channels": mgr.set_channels(d.get("channels", []))})
                if u.path == "/api/settings":
                    mgr.update_settings(d)
                    return self._json({"ok": True})
                if u.path == "/api/watch/start":
                    return self._json({"started": mgr.start_watch(d["channel"])})
                if u.path == "/api/watch/stop":
                    mgr.stop_watch(d["channel"])
                    return self._json({"ok": True})
                if u.path == "/api/vod":
                    mgr.run_vods(d.get("channels") or None)
                    return self._json({"ok": True})
                if u.path == "/api/delete":
                    mgr.delete_clip(d["file"])
                    return self._json({"ok": True})
            except (ValueError, RuntimeError, KeyError, PermissionError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"error": "nicht gefunden"}, 404)
    return H


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--lan", action="store_true", help="auch im WLAN erreichbar (iPhone), mit Zugangscode")
    ap.add_argument("--no-poll", action="store_true", help="keine automatische Live-Pruefung (Test)")
    a = ap.parse_args()
    mgr = Manager()
    if not a.no_poll:
        mgr.start()
    token = secrets.token_urlsafe(8) if a.lan else None
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, a.port), make_handler(mgr, token))
    print(f"CLIPFORGE läuft:  http://127.0.0.1:{a.port}" + (f"/?k={token}" if token else ""))
    if a.lan:
        print(f"iPhone (gleiches WLAN):  http://{lan_ip()}:{a.port}/?k={token}")
    print(f"Clips-Ordner: {mgr.clips_dir}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        mgr.running = False
        for w in mgr.workers.values():
            w.stop()


if __name__ == "__main__":
    main()
