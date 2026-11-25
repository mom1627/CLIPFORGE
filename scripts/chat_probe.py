"""Schnelle Chat-Aktivitaet fuer Twitch-VODs: kurze Stichproben statt kompletten Chat-Download.
Nutzt den inoffiziellen Web-Endpunkt gql.twitch.tv (wie der Twitch-Player; vom Nutzer ausdruecklich erlaubt).
Kann sich aendern oder gesperrt werden -> chat_peaks() liefert dann [] und der Aufrufer faellt auf die Audio-Suche zurueck."""
from __future__ import annotations
import json, statistics, urllib.request
from concurrent.futures import ThreadPoolExecutor

GQL = "https://gql.twitch.tv/gql"
CLIENT = "kimne78kx3ncx6brgo4mv6wki5h1ko"
HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


def fetch_page(vod_id: str, offset: int):
    body = json.dumps([{"operationName": "VideoCommentsByOffsetOrCursor",
                        "variables": {"videoID": vod_id, "contentOffsetSeconds": int(offset)},
                        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}}}]).encode()
    req = urllib.request.Request(GQL, data=body, headers={"Client-ID": CLIENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    edges = (((data[0].get("data") or {}).get("video") or {}).get("comments") or {}).get("edges") or []
    return [e["node"]["contentOffsetSeconds"] for e in edges if e.get("node")]


def fetch_messages(vod_id: str, offset: int):
    """Wie fetch_page, aber mit Text: [(sekunde, nachricht)]. Text fehlt -> ''."""
    body = json.dumps([{"operationName": "VideoCommentsByOffsetOrCursor",
                        "variables": {"videoID": vod_id, "contentOffsetSeconds": int(offset)},
                        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}}}]).encode()
    req = urllib.request.Request(GQL, data=body, headers={"Client-ID": CLIENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    edges = (((data[0].get("data") or {}).get("video") or {}).get("comments") or {}).get("edges") or []
    out = []
    for e in edges:
        n = e.get("node") or {}
        if "contentOffsetSeconds" not in n:
            continue
        frags = ((n.get("message") or {}).get("fragments") or [])
        out.append((n["contentOffsetSeconds"], " ".join(str(f.get("text") or "") for f in frags)))
    return out


# Chat-Reaktionen, die lustige/dramatische Momente anzeigen (Lachen, Schock, Hype)
REACTIONS = ("kekw", "lul", "omegalul", "lulw", "icant", "lmao", "lmfao", "xdd", "pog", "poggers", "monkas",
             "wtf", "no way", "nahh", "omg", "holy", "😂", "🤣", "💀", "😭", "😱", "🔥", "clip it", "clip that",
             "aware", "d:", "!!!", "????", "pepela", "sadge", "ez", "w ", "ratio", "dead", "crying", "screaming")


def reaction_share(texts) -> float:
    """Anteil der Nachrichten mit Lach-/Schock-/Hype-Reaktion (0..1)."""
    texts = [t.lower() + " " for t in texts if t]
    if not texts:
        return 0.0
    return sum(any(r in t for r in REACTIONS) for t in texts) / len(texts)


def rate_from_offsets(offs, start):
    offs = [o for o in offs if o >= start]
    if len(offs) < 8:
        return len(offs) / 60.0
    return len(offs) / max(1.0, offs[-1] - offs[0])


def pick_peaks(samples, count, min_gap=150, min_ratio=2.0, fun=None):
    """samples [(sek, rate)]; fun {sek: Reaktionsanteil}. Punktzahl = Chat-Anstieg × (1 + 3 × Reaktionsanteil):
    viel Chat UND viele Lach-/Schock-Reaktionen schlägt bloß viel Chat."""
    if len(samples) < 8:
        return []
    fun = fun or {}
    base = max(statistics.median(r for _, r in samples), 1e-3)
    scored = [(off, rate / base * (1 + 3 * fun.get(off, 0.0))) for off, rate in samples if rate / base >= min_ratio]
    out = []
    for off, score in sorted(scored, key=lambda x: -x[1]):
        if all(abs(off - o) >= min_gap for o, _ in out):
            out.append((off, round(score, 2)))
        if len(out) >= count:
            break
    return out


def chat_peaks(vod_id: str, duration: int, count: int = 6, probes: int = 360):
    step = max(30, duration // probes)
    offsets = list(range(0, max(1, duration - 30), step))

    fun = {}

    def probe(o):
        try:
            msgs = fetch_messages(vod_id, o)
            fun[o] = reaction_share([t for s, t in msgs if s >= o])
            return o, rate_from_offsets([s for s, _ in msgs], o)
        except Exception:
            return o, None
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(probe, offsets))
    ok = [(o, r) for o, r in res if r is not None]
    if len(ok) < len(res) * 0.6:
        return []
    if fun:
        print(f"CHAT-REAKTIONEN Ø {sum(fun.values()) / len(fun):.2f}, max {max(fun.values()):.2f}", flush=True)
    return pick_peaks(ok, count, fun=fun)


CHAPTER_HASH = "8d2793384aac3773beab5e59bd5d6f585aedb923d292800119e03d40cd0f9b41"


def game_chapters(vod_id: str, duration: int = 0):
    """Spiel-Kapitel eines Twitch-VODs: [(start_s, end_s, spielname)]. [] = keine Kapitel (ein Spiel),
    None = nicht ermittelbar. Gleicher inoffizieller Web-Endpunkt wie der Chat (vom Nutzer erlaubt)."""
    body = json.dumps([{"operationName": "VideoPlayer_ChapterSelectButtonVideo",
                        "variables": {"includePrivate": False, "videoID": str(vod_id)},
                        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": CHAPTER_HASH}}}]).encode()
    req = urllib.request.Request(GQL, data=body, headers={"Client-ID": CLIENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        video = (data[0].get("data") or {}).get("video")
        if video is None:
            return None
        edges = ((video.get("moments") or {}).get("edges")) or []
    except Exception:
        return None
    out = []
    for e in edges:
        n = e.get("node") or {}
        start = int(n.get("positionMilliseconds") or 0) // 1000
        length = int(n.get("durationMilliseconds") or 0) // 1000
        game = (((n.get("details") or {}).get("game")) or {}).get("displayName") or n.get("description") or ""
        out.append((start, start + length if length else (duration or 10**9), game))
    return out


def in_game(chapters, second: int, game: str) -> bool | None:
    """True/False, ob die Sekunde im Kapitel des Spiels liegt; None = unbekannt (keine Kapitel)."""
    if not chapters:
        return None
    g = game.lower()
    for a, b, name in chapters:
        if a <= second < b:
            return g in name.lower() or name.lower() in g
    return False
