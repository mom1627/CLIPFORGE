"""Veröffentlichen über OmniSocials gegen einen lokalen Fake-Server."""
import base64, json, os, sys, tempfile, threading, unittest
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

    def do_GET(self):
        assert self.headers["Authorization"] == "Bearer omsk_test"
        if self.path == "/v1/accounts":
            return self._j({"data": [{"id": "ig1", "platform": "instagram", "status": "active"},
                                     {"id": "tt9", "platform": "tiktok", "status": "active"}]})
        self._j({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append((self.path, body))
        if self.path == "/v1/media/upload-from-base64":
            assert base64.b64decode(body["data"]) == b"V" * 2048 and body["mime_type"] == "video/mp4"
            return self._j({"data": {"id": "m1"}})
        if self.path == "/v1/posts/create-and-publish":
            return self._j({"data": {"id": "p1", "status": "posting"}})
        self._j({"error": {"code": "not_found"}}, 404)


class PublisherTest(unittest.TestCase):
    def test_caption(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import publisher
        c = publisher.build_caption("trymacs", "Das hat niemand kommen sehen", "#gta6 #fyp")
        self.assertIn("Das hat niemand kommen sehen", c)
        self.assertIn("trymacs (Twitch)", c)
        self.assertTrue(c.endswith("#gta6 #fyp #trymacs"))

    def test_publish_flow(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update({"OMNISOCIALS_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1", "OMNISOCIALS_API_KEY": "omsk_test"})
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib, publisher
        importlib.reload(publisher)
        with tempfile.TemporaryDirectory() as t:
            v = Path(t) / "c.mp4"; v.write_bytes(b"V" * 2048)
            r = publisher.publish(v, "Hallo #gta6")
        self.assertEqual(r["post_id"], "p1")
        post = [b for p, b in CALLS if p.endswith("create-and-publish")][0]
        self.assertEqual(post["channels"], ["tt9"])
        self.assertEqual(post["media_ids"], ["m1"])
        self.assertEqual(post["tiktok"]["privacy_level"], "PUBLIC_TO_EVERYONE")
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
