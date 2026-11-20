"""TikTok-Ablauf gegen einen lokalen Fake-Server (kein echtes TikTok)."""
import json, os, sys, tempfile, threading, time, unittest, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALLS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _j(self, d, code=200):
        b = json.dumps(d).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        CALLS.append((self.path, self.headers.get("Authorization"), body))
        if self.path == "/v2/oauth/token/":
            f = urllib.parse.parse_qs(body.decode())
            assert f["grant_type"][0] in ("authorization_code", "refresh_token")
            if f["grant_type"][0] == "authorization_code":
                assert f["code_verifier"][0]
            return self._j({"access_token": "AT", "refresh_token": "RT", "expires_in": 86400,
                            "refresh_expires_in": 31536000, "scope": "user.info.basic,video.upload", "open_id": "x"})
        if self.path == "/v2/post/publish/inbox/video/init/":
            src = json.loads(body)["source_info"]
            assert src["source"] == "FILE_UPLOAD" and src["total_chunk_count"] == 1
            return self._j({"data": {"publish_id": "p1", "upload_url": f"http://127.0.0.1:{self.server.server_port}/up"},
                            "error": {"code": "ok"}})
        if self.path == "/v2/post/publish/status/fetch/":
            return self._j({"data": {"status": "SEND_TO_USER_INBOX"}, "error": {"code": "ok"}})
        self._j({}, 404)

    def do_PUT(self):
        n = int(self.headers["Content-Length"]); self.rfile.read(n)
        CALLS.append((self.path, self.headers.get("Content-Range"), n))
        self._j({}, 201)


class TikTokFlow(unittest.TestCase):
    def test_login_and_draft_upload(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update({"TIKTOK_API_BASE": f"http://127.0.0.1:{srv.server_port}",
                           "TIKTOK_CLIENT_KEY": "ck", "TIKTOK_CLIENT_SECRET": "cs"})
        sys.path.insert(0, str(ROOT / "app"))
        import importlib, tiktok
        importlib.reload(tiktok)
        with tempfile.TemporaryDirectory() as h:
            t = tiktok.TikTok(Path(h), "http://localhost:8787/tiktok/callback")
            url = t.login_url()
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertIn("video.upload", q["scope"][0])
            self.assertEqual(q["code_challenge_method"][0], "S256")
            t.finish_login("CODE", q["state"][0])
            self.assertTrue(t.connected())
            self.assertEqual(oct(os.stat(t.token_path).st_mode)[-3:], "600")
            with self.assertRaises(tiktok.TikTokError):
                t.finish_login("CODE", "falscher-state")
            vid = Path(h) / "c.mp4"; vid.write_bytes(b"0" * 12345)
            r = t.upload_draft(vid, wait_s=5)
            self.assertEqual(r, {"publish_id": "p1", "status": "SEND_TO_USER_INBOX"})
            put = [c for c in CALLS if c[0] == "/up"][0]
            self.assertEqual(put[1], "bytes 0-12344/12345")
            init = [c for c in CALLS if c[0].endswith("init/")][0]
            self.assertEqual(init[1], "Bearer AT")
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
