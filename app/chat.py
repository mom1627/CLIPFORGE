"""Twitch-Chat live mitlesen (offizieller IRC, anonym, nur lesen) und Chat-Spitzen erkennen."""
from __future__ import annotations

import random
import re
import socket
import ssl
import statistics
import threading
import time

HOST, PORT = "irc.chat.twitch.tv", 6697

# Reaktions-Emotes/Woerter zaehlen staerker als normale Nachrichten
HYPE = re.compile(r"\b(lul|lmao|lmfao|kekw|omegalul|pog|pogchamp|poggers|pogu|w+|l+|holy|wtf|omg|xd+|haha+|ahah+|"
                  r"monkas|sadge|ez|clip(?:\s*it)?|bro+|digga|krass|alter)\b", re.I)


def parse_privmsg(line: str):
    """':nick!nick@nick.tmi.twitch.tv PRIVMSG #chan :text' -> (nick, text) oder None."""
    if " PRIVMSG #" not in line:
        return None
    try:
        prefix, rest = line.split(" PRIVMSG #", 1)
        nick = prefix.lstrip(":").split("!", 1)[0]
        text = rest.split(" :", 1)[1] if " :" in rest else ""
        return nick.lower(), text.strip()
    except (ValueError, IndexError):
        return None


def message_weight(text: str) -> float:
    """1 pro Nachricht, bis zu +1.5 fuer Hype-Woerter/Emotes, GROSSBUCHSTABEN oder Wiederholungen."""
    w = 1.0
    if HYPE.search(text):
        w += 1.0
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        w += 0.25
    if re.search(r"(.)\1{3,}", text):
        w += 0.25
    return w


class ChatSpikes:
    """Gewichtete Nachrichten pro Sekunde -> Spitzen gegenueber dem gleitenden Grundniveau.
    Rein rechnerisch, ohne Netzwerk; deshalb testbar."""

    def __init__(self, window: int = 10, baseline_s: int = 300, ratio: float = 2.5,
                 min_weight: float = 12.0, min_gap: int = 120, warmup: int = 90):
        self.window, self.baseline_s, self.ratio = window, baseline_s, ratio
        self.min_weight, self.min_gap, self.warmup = min_weight, min_gap, warmup
        self.buckets: dict[int, float] = {}
        self.bots: set[str] = {"nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "wizebot"}
        self.last_hit = -10**9
        self.first: int | None = None

    def add(self, ts: float, nick: str, text: str):
        if nick in self.bots or nick.endswith("bot"):
            return
        sec = int(ts)
        if self.first is None:
            self.first = sec
        self.buckets[sec] = self.buckets.get(sec, 0.0) + message_weight(text)

    def window_sum(self, end: int) -> float:
        return sum(self.buckets.get(s, 0.0) for s in range(end - self.window, end))

    def check(self, now: float):
        """Gibt (zeitpunkt, staerke) zurueck, wenn das letzte Fenster eine Spitze ist, sonst None."""
        end = int(now)
        if self.first is None or end - self.first < self.warmup or end - self.last_hit < self.min_gap:
            return None
        cur = self.window_sum(end)
        starts = range(max(self.first, end - self.baseline_s), end - self.window, self.window)
        hist = [self.window_sum(s + self.window) for s in starts]
        if len(hist) < 4:
            return None
        base = max(statistics.median(hist), 1.0)
        if cur >= self.min_weight and cur / base >= self.ratio:
            self.last_hit = end
            return end, round(cur / base, 2)
        # alte Eintraege aufraeumen
        for s in [k for k in self.buckets if k < end - self.baseline_s - 60]:
            del self.buckets[s]
        return None

    def rate(self, now: float) -> float:
        return round(self.window_sum(int(now)) / self.window, 2)


class ChatReader(threading.Thread):
    """Liest den Chat eines Kanals im Hintergrund und fuettert ChatSpikes."""

    def __init__(self, channel: str, spikes: ChatSpikes):
        super().__init__(daemon=True)
        self.channel, self.spikes = channel.lower(), spikes
        self.running = True
        self.connected = False
        self.messages = 0
        self.error = ""

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            try:
                ctx = ssl.create_default_context()
                with socket.create_connection((HOST, PORT), timeout=30) as raw, \
                        ctx.wrap_socket(raw, server_hostname=HOST) as sock:
                    nick = f"justinfan{random.randint(10000, 99999)}"  # anonymer Lesezugang von Twitch
                    sock.sendall(f"NICK {nick}\r\nJOIN #{self.channel}\r\n".encode())
                    self.connected, buf = True, b""
                    sock.settimeout(5)
                    while self.running:
                        try:
                            data = sock.recv(65536)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        buf += data
                        *lines, buf = buf.split(b"\r\n")
                        for raw_line in lines:
                            line = raw_line.decode("utf-8", "replace")
                            if line.startswith("PING"):
                                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                                continue
                            msg = parse_privmsg(line)
                            if msg:
                                self.messages += 1
                                self.spikes.add(time.time(), *msg)
            except OSError as exc:
                self.error = str(exc)[:200]
            self.connected = False
            if self.running:
                time.sleep(5)
