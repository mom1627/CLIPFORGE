import json, os, subprocess, sys, tempfile, threading, time, unittest, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))
import chat  # noqa: E402


class ChatTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(chat.parse_privmsg(":abc!abc@abc.tmi.twitch.tv PRIVMSG #xqc :OMEGALUL no way"), ("abc", "OMEGALUL no way"))
        self.assertIsNone(chat.parse_privmsg(":tmi.twitch.tv 001 justinfan1 :Welcome"))

    def test_weight(self):
        self.assertEqual(chat.message_weight("hello there"), 1.0)
        self.assertGreater(chat.message_weight("KEKW"), 1.9)

    def test_spike_detected_once_and_bots_ignored(self):
        s = chat.ChatSpikes(min_gap=120, warmup=90)
        t0 = 1_000_000
        for sec in range(300):           # ruhiger Chat: 1 Nachricht / s
            s.add(t0 + sec, "viewer", "hi")
            s.add(t0 + sec, "nightbot", "!discord " * 3)  # Bot zaehlt nicht
        hits = []
        for sec in range(300, 312):      # Ausraster: 8 Hype-Nachrichten / s
            for i in range(8):
                s.add(t0 + sec, f"u{i}", "LUL LUL")
            r = s.check(t0 + sec + 1)
            if r:
                hits.append(r)
        self.assertEqual(len(hits), 1)
        self.assertGreater(hits[0][1], 2.5)

    def test_flat_chat_no_spike(self):
        s = chat.ChatSpikes()
        t0 = 2_000_000
        hits = []
        for sec in range(600):
            for i in range(3):
                s.add(t0 + sec, f"u{i}", "hello")
            r = s.check(t0 + sec + 1)
            if r:
                hits.append(r)
        self.assertEqual(hits, [])


class ServerTest(unittest.TestCase):
    def test_api_and_range(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "CLIPFORGE_HOME": home}
            clips = Path(home) / "clips"
            clips.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=72x128:d=1",
                            "-pix_fmt", "yuv420p", str(clips / "clipforge_test_1.mp4")], check=True)
            (clips / "clipforge_test_1.json").write_text('{"channel": "test"}')
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=72x128:d=1",
                            "-pix_fmt", "yuv420p", str(clips / "clipforge_busy_2.mp4")], check=True)  # noch in Arbeit
            p = subprocess.Popen([sys.executable, str(ROOT / "app/server.py"), "--port", "8799", "--no-poll"], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                for _ in range(50):
                    try:
                        urllib.request.urlopen("http://127.0.0.1:8799/api/state", timeout=1); break
                    except OSError:
                        time.sleep(0.1)
                st = json.load(urllib.request.urlopen("http://127.0.0.1:8799/api/state"))
                self.assertEqual([c["file"] for c in st["clips"]], ["clipforge_test_1.mp4"])
                req = urllib.request.Request("http://127.0.0.1:8799/api/channels", method="POST",
                                             data=json.dumps({"channels": ["Trymacs", "https://twitch.tv/kaicenat"]}).encode())
                self.assertEqual(json.load(urllib.request.urlopen(req))["channels"], ["trymacs", "kaicenat"])
                bad = urllib.request.Request("http://127.0.0.1:8799/api/channels", method="POST",
                                             data=json.dumps({"channels": ["Kai Cenat"]}).encode())
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(bad)
                self.assertEqual(e.exception.code, 400)
                cam = urllib.request.Request("http://127.0.0.1:8799/api/cam", method="POST",
                                             data=json.dumps({"channel": "trymacs", "value": "unten-links"}).encode())
                urllib.request.urlopen(cam)
                st = json.load(urllib.request.urlopen("http://127.0.0.1:8799/api/state"))
                self.assertEqual(st["channels"][0]["cam"], [0.0, 0.60, 0.26, 0.40])
                r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8799/clips/clipforge_test_1.mp4",
                                                                  headers={"Range": "bytes=0-99"}))
                self.assertEqual(r.status, 206)
                self.assertEqual(len(r.read()), 100)
                page = urllib.request.urlopen("http://127.0.0.1:8799/").read().decode()
                self.assertIn("CLIPFORGE", page)
                trav = urllib.request.Request("http://127.0.0.1:8799/clips/..%2Fconfig.json")
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(trav)
            finally:
                p.terminate(); p.wait(5)


if __name__ == "__main__":
    unittest.main()
