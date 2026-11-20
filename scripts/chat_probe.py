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


def rate_from_offsets(offs, start):
    offs = [o for o in offs if o >= start]
    if len(offs) < 8:
        return len(offs) / 60.0
    return len(offs) / max(1.0, offs[-1] - offs[0])


def pick_peaks(samples, count, min_gap=150, min_ratio=2.0):
    if len(samples) < 8:
        return []
    base = max(statistics.median(r for _, r in samples), 1e-3)
    out = []
    for off, rate in sorted(samples, key=lambda x: -x[1]):
        ratio = rate / base
        if ratio < min_ratio:
            break
        if all(abs(off - o) >= min_gap for o, _ in out):
            out.append((off, ratio))
        if len(out) >= count:
            break
    return out


def chat_peaks(vod_id: str, duration: int, count: int = 6, probes: int = 360):
    step = max(30, duration // probes)
    offsets = list(range(0, max(1, duration - 30), step))

    def probe(o):
        try:
            return o, rate_from_offsets(fetch_page(vod_id, o), o)
        except Exception:
            return o, None
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(probe, offsets))
    ok = [(o, r) for o, r in res if r is not None]
    if len(ok) < len(res) * 0.6:
        return []
    return pick_peaks(ok, count)
