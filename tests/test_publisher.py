"""Veröffentlichen über Cloudinary (Hosting) + Buffer (TikTok) gegen lokale Fake-Server."""
import json, os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CALLS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _j(self, d, code=200):
        b = json.dumps(d).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/cld/democloud/video/upload":
            assert b'name="upload_preset"\r\n\r\nclipforge_unsigned' in raw and b"V" * 2048 in raw
            CALLS.append(("upload", None))
            return self._j({"secure_url": "https://res.cloudinary.com/democloud/video/upload/v1/c.mp4"})
        if self.path == "/gql":
            assert self.headers["Authorization"] == "Bearer buf_test"
            q = json.loads(raw)["query"]; CALLS.append(("gql", q))
            if "organizations" in q:
                return self._j({"data": {"account": {"organizations": [{"id": "org1", "name": "Ich"}]}}})
            if "channels(" in q:
                return self._j({"data": {"channels": [{"id": "ig1", "service": "instagram"},
                                                      {"id": "tt9", "service": "tiktok"}]}})
            if "createPost" in q:
                return self._j({"data": {"createPost": {"post": {"id": "p1"}}}})
        self._j({"errors": [{"message": "unbekannt"}]}, 404)


class PublisherTest(unittest.TestCase):
    def test_caption(self):
        import publisher
        c = publisher.build_caption("trymacs", "Das hat niemand kommen sehen", "#gta6 #fyp")
        self.assertIn("Das hat niemand kommen sehen", c)
        self.assertTrue(c.endswith("#gta6 #fyp #trymacs"))

    def test_publish_flow(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        os.environ.update({"BUFFER_API_URL": base + "/gql", "CLOUDINARY_API_URL": base + "/cld",
                           "BUFFER_API_KEY": "buf_test", "CLOUDINARY_CLOUD_NAME": "democloud",
                           "CLOUDINARY_UPLOAD_PRESET": "clipforge_unsigned"})
        os.environ.pop("BUFFER_CHANNEL_ID", None)
        import importlib, publisher
        importlib.reload(publisher)
        self.assertTrue(publisher.configured())
        with tempfile.TemporaryDirectory() as t:
            v = Path(t) / "c.mp4"; v.write_bytes(b"V" * 2048)
            r = publisher.publish(v, 'Hallo "Chat" #gta6\nZeile 2')
        self.assertEqual(r["post_id"], "p1")
        q = [x for k, x in CALLS if k == "gql" and "createPost" in x][0]
        self.assertIn('channelId: "tt9"', q)
        self.assertIn('url: "https://res.cloudinary.com/democloud/video/upload/v1/c.mp4"', q)
        self.assertIn('text: "Hallo \\"Chat\\" #gta6\\nZeile 2"', q)
        self.assertIn("mode: customScheduled", q)
        srv.shutdown()
        for k in ("BUFFER_API_URL", "CLOUDINARY_API_URL", "BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET"):
            os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
