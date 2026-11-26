"""Hook title + burned-in subtitles for CLIPFORGE clips (9:16, any width/height)."""
from __future__ import annotations
import os, subprocess, zlib
from pathlib import Path

HOOKS = {  # nur Fallback, wenn im Clip kein starkes Zitat fällt; wechseln sich ab (keine Wiederholung)
    "de": ["Das hat keiner kommen sehen", "Warte bis zum Ende", "{s} hat das wirklich gemacht",
           "Der Chat konnte es nicht glauben", "Das ist komplett eskaliert", "Wie kann das passieren",
           "{s} war nicht bereit", "Das Ende ist unglaublich", "Niemand hat damit gerechnet",
           "Diese Reaktion von {s}", "Das darf nicht wahr sein", "{s} hat es übertrieben"],
    "en": ["Nobody saw this coming", "Wait for the ending", "{s} actually did this",
           "This went way too far", "He was NOT ready", "The way he reacted",
           "This can't be real", "Watch till the end", "{s} crossed the line",
           "How did this even happen", "This escalated fast", "{s} had no idea",
           "Chat could not believe it", "The ending is insane", "{s} was NOT ready",
           "He really said that", "This is why we watch {s}", "Instant regret"],
}
DISPLAY = {  # Twitch-Login -> Name, den Zuschauer kennen
    "montanablack88": "Monte", "kaicenat": "Kai Cenat", "xqc": "xQc", "trymacs": "Trymacs",
    "papaplatte": "Papaplatte", "eliasn97": "Eli", "knossi": "Knossi", "revedtv": "Reved",
    "jynxzi": "Jynxzi", "lacy": "Lacy", "stableronaldo": "StableRonaldo", "summit1g": "summit1g", "dylanpage": "Dylan Page", "bendadonnn": "BenDaDonnn", "caseoh_": "CaseOh", "ohnepixel": "ohnePixel", "hasanabi": "Hasan",
}


def display_name(channel: str) -> str:
    return DISPLAY.get(channel.lower(), channel)


_USED: set = set()


def recent_hooks(limit: int = 40) -> set:
    """Zuletzt benutzte Hooks (App-Liste + dieser Lauf), damit sich keiner ständig wiederholt."""
    import json
    try:
        data = json.loads((Path(__file__).resolve().parent.parent / "docs/clips.json").read_text())
        clips = sorted(data.get("clips", []), key=lambda c: str(c.get("added", "")), reverse=True)[:limit]
        return {str(c.get("hook", "")).lower() for c in clips if c.get("hook")} | _USED
    except (OSError, ValueError):
        return set(_USED)


def pick_hook(channel: str, seed: str, lang: str, fresh: bool = True) -> str:
    """fresh=True: kürzlich benutzte Hooks meiden (neuer Clip). fresh=False: stabil je seed (App-Beschreibung)."""
    import campaign
    if campaign.title():  # Kampagne verlangt sachlichen Titel (keine Übertreibung)
        return campaign.title()
    titles = campaign.load().get("titles") or []
    if titles:  # Kampagne gibt neutrale Titel vor (z. B. nicht negativ darstellen)
        return str(titles[zlib.crc32(seed.encode()) % len(titles)]).format(s=display_name(channel))
    custom = [h.strip() for h in os.getenv("HOOKS", "").split("|") if h.strip()]
    pool = [h.format(s=display_name(channel)) for h in (custom or HOOKS.get(lang[:2], HOOKS["en"]))]
    if not fresh:
        return pool[zlib.crc32(seed.encode()) % len(pool)]
    used = recent_hooks()
    avail = [h for h in pool if h.lower() not in used] or pool
    hook = avail[zlib.crc32(seed.encode()) % len(avail)]
    _USED.add(hook.lower())
    return hook


PUNCH = ("no way", "what the", "oh my god", "oh my gosh", "are you serious", "you're joking", "let's go", "holy",
         "bro", "dude", "wtf", "why", "how", "never", "nobody", "insane", "crazy", "wait", "stop", "shut up",
         "i can't", "what?", "what!", "are you kidding", "help", "run", "oh no", "yo", "dead", "kill", "caught",
         "scared", "screaming", "lying", "worst", "best", "can't believe", "look at", "did you see", "hell")
FILLER = {"yeah", "yes", "okay", "ok", "um", "uh", "like", "so", "and", "the", "a", "i", "you", "it", "is", "that"}


def punch(text: str) -> float:
    """Wie stark zieht ein Satz Aufmerksamkeit? Reaktions-/Drama-Wörter, Frage/Ausruf zählen; Füllwörter und
    Wiederholungen ('yeah, yeah') nicht."""
    t = text.lower()
    ws = [w.strip(" .,!?'") for w in t.split()]
    if not ws:
        return 0.0
    import re as _re
    score = 3.0 * sum(bool(_re.search(r"(?<![a-z'])" + _re.escape(p) + r"(?![a-z'])", t)) for p in PUNCH)
    score += 1.5 * ("?" in t) + 1.5 * ("!" in t)
    score -= 3.0 * (sum(w in FILLER for w in ws) / len(ws) > 0.6)
    score -= 3.0 * (len(set(ws)) < len(ws) * 0.7)
    return score


def sentences(words, lo: int = 3, hi: int = 7):
    """Ganze Sätze/Satzteile aus Whisper-Wörtern: Schnitt an . ? ! , und an Pausen > 0.6 s.
    Nur 3-7 Wörter – so entstehen keine Bruchstücke wie 'TO YOU WHAT THE FUCK DO'."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        t = str(w[2]).strip()
        gap = (words[i + 1][0] - w[1]) if i + 1 < len(words) else 9
        if t[-1:] in ".?!," or gap > 0.6:
            if t[-1:] != "," or len(cur) >= lo:
                out.append(cur); cur = []
    if cur:
        out.append(cur)
    res = []
    for c in out:
        text = " ".join(str(x[2]).strip() for x in c).strip(" ,-")
        if lo <= len(text.split()) <= hi and 12 <= len(text) <= 38:
            res.append((c[0][0], c[-1][1], text.upper()))
    return res


def quote_hook(words, around: float | None = None) -> str:
    """Hook aus dem echten Gesagten (wie 'NOT EVEN A WARNING'): der stärkste ganze Satz (3-7 Wörter);
    nur wenn er wirklich zieht (punch >= 3), sonst lieber eine starke Vorlage."""
    lines = [(a, b, t) for a, b, t in sentences(list(words))
             if (not _clean_wanted() or is_clean(t)) and t.lower() not in recent_hooks()]
    if not lines:
        return ""
    if around is None:
        around = max(b for _, b, _ in lines) * 0.6
    best = max(lines, key=lambda x: (punch(x[2]), -abs((x[0] + x[1]) / 2 - around)))
    if punch(best[2]) < 3:
        return ""
    _USED.add(best[2].lower())
    return best[2].strip(" .,")


def reaction_score(words) -> float:
    """Wie lebendig ist der Clip? Sprechdichte (Wörter/Sek.) + Drama-/Reaktionswörter. Langweilig < 1.5."""
    if not words:
        return 0.0
    text = " ".join(w[2] for w in words).lower()
    dur = max(1.0, words[-1][1] - words[0][0])
    import re as _re
    hits = sum(len(_re.findall(r"(?<![a-z'])" + _re.escape(p) + r"(?![a-z'])", text)) for p in PUNCH)
    return round(len(words) / dur + 0.5 * hits, 2)


def make_hook(channel: str, seed: str, lang: str, words=(), around: float | None = None) -> str:
    """Kampagnen-Titel haben Vorrang (Regeln); sonst Zitat-Hook; sonst wechselnde Vorlage."""
    import campaign
    if campaign.title() or campaign.load().get("titles"):
        return pick_hook(channel, seed, lang)
    return quote_hook(list(words), around) or pick_hook(channel, seed, lang)


PROFANITY = {"fuck", "fucking", "fucked", "shit", "bitch", "pussy", "dick", "cock", "cunt", "nigga", "nigger",
             "whore", "slut", "porn", "sex", "penis", "vagina", "boobs", "tits", "ass", "faggot", "retard",
             "scheiße", "scheisse", "fotze", "hure", "wichser", "ficken", "fick", "schlampe", "hurensohn"}


def is_clean(text: str) -> bool:
    import re as _re
    return not any(w in PROFANITY for w in _re.findall(r"[\wäöüß]+", text.lower()))


def _clean_wanted() -> bool:
    """Schimpfwort-Filter nur, wenn die Kampagne ihn will ("clean_quotes": true) oder CLEAN_QUOTES=1."""
    import campaign
    return bool(campaign.load().get("clean_quotes")) or os.getenv("CLEAN_QUOTES") == "1"


def pick_quote(words, around: float | None = None, max_words: int = 5) -> str:
    """Echtes Zitat aus dem Clip (2-5 Wörter) für den roten Kasten, möglichst nahe am Highlight.
    Optional ohne Schimpfwörter (Kampagnen-Einstellung "clean_quotes")."""
    lines = [(a, b, t) for a, b, t in group_words(words, max_words=max_words, max_len=3.0)
             if len(t.split()) >= 2 and (not _clean_wanted() or is_clean(t))]
    if not lines:
        return ""
    if around is None:
        around = max(b for _, b, _ in lines) * 0.7
    a, b, t = min(lines, key=lambda x: abs((x[0] + x[1]) / 2 - around))
    return t.lower().strip(" .,!?")


def _t(sec: float) -> str:
    sec = max(0.0, sec); cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words, max_words=3, max_gap=0.7, max_len=2.4):
    """words: [(start,end,text)] -> [(start,end,text)] lines of 1..max_words words."""
    lines, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > max_gap or w[1] - cur[0][0] > max_len):
            lines.append(cur); cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    out = []
    for i, ln in enumerate(lines):
        a = ln[0][0]; b = ln[-1][1]
        if i + 1 < len(lines):
            b = min(max(b, a + 0.5), lines[i + 1][0][0])
        else:
            b = max(b, a + 0.5)
        out.append((a, b, " ".join(x[2].strip() for x in ln).strip().upper()))
    return out


def wrap(text: str, width: int = 17) -> str:
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    out.append(cur)
    return "\\N".join(out[:3])


def build_ass(words, hook: str, width: int, height: int, duration: float, hook_seconds: float = 2.8, split: bool = False, hook_y_override: int | None = None, subtitle_y_override: int | None = None) -> str:
    fs, hs = round(width * 0.078), round(width * 0.092)
    sub_y = round(height * (0.80 if split else 0.735))      # unterhalb des 16:9-Spielfelds, oberhalb der TikTok-Bedienelemente
    hook_y = round(height * (0.40 - 0.07) if split else height * 0.22)      # im unscharfen Bereich ueber dem Spielfeld
    if hook_y_override is not None:
        hook_y = max(50, min(height - 50, int(hook_y_override)))
    if subtitle_y_override is not None:
        sub_y = max(50, min(height - 50, int(subtitle_y_override)))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Sub,DejaVu Sans,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{max(3, fs // 12)},1,8,40,40,0,1
Style: Hook,DejaVu Sans,{hs},{'&H00FFFFFF' if split else '&H0000D2FF'},&H000000FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,1,{max(4, hs // 10)},2,8,50,50,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ev = [f"Dialogue: 1,{_t(0)},{_t(min(hook_seconds, duration))},Hook,,0,0,0,,{{\\an8\\pos({width // 2},{hook_y})\\fad(150,350)}}{wrap(_esc(hook.upper()), 16)}"]
    for a, b, t in group_words(words):
        ev.append(f"Dialogue: 0,{_t(a)},{_t(b)},Sub,,0,0,0,,{{\\an8\\pos({width // 2},{sub_y})}}{wrap(_esc(t), 14)}")
    return head + "\n".join(ev) + "\n"


def transcribe(path: Path):
    """Returns (words, language). Needs faster-whisper; returns ([], 'en') if unavailable."""
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # pragma: no cover
        print("Whisper nicht verfuegbar:", e); return [], os.getenv("CAPTION_LANG", "de")
    model = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    lang = os.getenv("CAPTION_LANG") or None
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, timeout=120).stdout
    audio = np.frombuffer(pcm[: len(pcm) // 4 * 4], dtype=np.float32)   # kein PyAV noetig
    segs, info = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True, beam_size=1)
    words = [(w.start, w.end, w.word) for s in segs for w in (s.words or [])]
    return words, info.language


def probe(path: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True)
    a, b = r.stdout.split()[0].split("x")[:2], r.stdout.split()[1] if len(r.stdout.split()) > 1 else "0"
    return int(a[0]), int(a[1]), float(b)


def has_ass_filter() -> bool:
    """Homebrew-ffmpeg auf dem Mac hat oft kein libass -> dann Pillow-Weg."""
    if os.getenv("CAPTION_RENDERER", "").lower() == "pillow":
        return False
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
        return any(ln.split()[1:2] == ["ass"] for ln in r.stdout.splitlines() if ln.strip())
    except Exception:
        return False


FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",            # macOS
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",          # Linux / GitHub
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for f in [os.getenv("CAPTION_FONT", "")] + FONT_CANDIDATES:
        if f and Path(f).is_file():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size)
    except TypeError:  # sehr altes Pillow
        return ImageFont.load_default()


def _draw_block(draw, text: str, font, cx: int, top: int, fill, stroke: int, shadow: int):
    """Zentrierte, umrandete Zeilen ab y=top (wie ASS \\an8\\pos)."""
    y = top
    for line in text.split("\\N"):
        box = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
        w, h = box[2] - box[0], box[3] - box[1]
        x = cx - w // 2 - box[0]
        if shadow:
            draw.text((x + shadow, y + shadow - box[1]), line, font=font, fill=(0, 0, 0, 140),
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 140))
        draw.text((x, y - box[1]), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += int(h * 1.18)


def _no_emoji(text: str) -> str:
    """Die Video-Schrift kann keine Emojis – sonst erscheinen Kästchen."""
    return " ".join("".join(ch for ch in text if ord(ch) < 0x2190 and ch not in "\ufe0f\u200d").split())


def _draw_box(draw, text: str, font, cx: int, top: int, bg, fg, pad: int, max_w: int) -> int:
    """Abgerundeter Kasten mit zentriertem Text (mehrzeilig umbrochen). Gibt die Unterkante zurück."""
    words, rows, cur = _no_emoji(text).split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if cur and draw.textlength(test, font=font) > max_w - 2 * pad:
            rows.append(cur); cur = w
        else:
            cur = test
    rows.append(cur)
    rows = rows[:3]
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)
    tw = max(int(draw.textlength(r, font=font)) for r in rows)
    w, h = tw + 2 * pad, lh * len(rows) + int(pad * 1.2)
    x0 = cx - w // 2
    draw.rounded_rectangle([x0, top, x0 + w, top + h], radius=max(8, pad // 2), fill=bg)
    y = top + int(pad * 0.6)
    for r in rows:
        draw.text((cx - int(draw.textlength(r, font=font)) // 2, y), r, font=font, fill=fg)
        y += lh
    return top + h


HOOK_FONT = Path(__file__).resolve().parent.parent / "config" / "fonts" / "LuckiestGuy-Regular.ttf"


def _hook_font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(HOOK_FONT), size)
    except OSError:
        return _font(size)


def draw_glow_hook(img, text: str, width: int, center_y: int):
    """Hook wie TikTok-Beispiel: gelbe Comic-Schrift, dicker schwarzer Rand, rotes Leuchten, ohne Kasten.
    Möglichst eine Zeile (Schrift wird verkleinert), höchstens zwei. Mittig um center_y."""
    from PIL import Image, ImageDraw, ImageFilter
    text = " ".join(_no_emoji(text).upper().replace("?!", "?").split())
    max_w = round(width * 0.9)
    d0 = ImageDraw.Draw(img)
    size, rows = round(width * 0.085), [text]
    while size > round(width * 0.05):
        f = _hook_font(size)
        if d0.textlength(text, font=f) <= max_w:
            rows = [text]; break
        words = text.split(); best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            w = max(d0.textlength(a, font=f), d0.textlength(b, font=f))
            if w <= max_w and (best is None or w < best[0]):
                best = (w, [a, b])
        if best and size <= round(width * 0.07):
            rows = best[1]; break
        size -= 2
    f = _hook_font(size)
    stroke = max(4, size // 9)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 0.98)
    top = center_y - lh * len(rows) // 2
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dl, dg = ImageDraw.Draw(layer), ImageDraw.Draw(glow)
    for i, r in enumerate(rows):
        x = width // 2 - int(d0.textlength(r, font=f)) // 2
        y = top + i * lh
        dg.text((x, y), r, font=f, fill=(255, 20, 0, 255), stroke_width=stroke * 4, stroke_fill=(255, 20, 0, 255))
        dl.text((x, y), r, font=f, fill=(255, 226, 40, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.45))
    a = glow.getchannel("A").point(lambda v: min(255, int(v * 1.6)))
    glow.putalpha(a)
    img.alpha_composite(glow)
    img.alpha_composite(layer)


def build_overlay_frames(words, hook: str, width: int, height: int, duration: float, outdir: Path,
                         hook_seconds: float = 2.8, split: bool = False, quote: str = "",
                         style: str | None = None, seam_y: int | None = None) -> Path:
    """Zeichnet Hook + Untertitel als transparente PNGs und schreibt eine concat-Liste (Bild + Dauer).
    style 'box' (Standard): weißer Kasten mit schwarzem Titel + roter Kasten mit Zitat an der Naht,
    den ganzen Clip lang sichtbar. style 'classic': weiße Schrift mit Rand, nur die ersten Sekunden."""
    from PIL import Image, ImageDraw
    style = style or os.getenv("CAPTION_STYLE", "glow")
    fs, hs = round(width * 0.078), round(width * 0.092)
    sub_y = round(height * (0.80 if split else 0.735))
    import campaign
    sub_y = campaign.subtitle_y(height, sub_y)
    hook_y = round(height * (0.40 - 0.07) if split else height * 0.22)
    f_sub, f_hook = _font(fs), _font(hs)
    f_box, f_quote = _font(round(width * 0.074)), _font(round(width * 0.066))
    hook_fill = (255, 255, 255, 255) if split else (255, 210, 0, 255)
    hook_end = duration if style in ("box", "glow") else min(hook_seconds, duration)
    subs = [(a, min(b, duration), wrap(_esc(t), 14)) for a, b, t in group_words(words) if a < duration]
    cuts = sorted({0.0, hook_end, duration, *[x for a, b, _ in subs for x in (a, b)]})
    cuts = [c for c in cuts if 0 <= c <= duration]
    outdir.mkdir(parents=True, exist_ok=True)
    cache, lines = {}, ["ffconcat version 1.0"]
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.01:
            continue
        mid = (a + b) / 2
        hook_on = mid < hook_end
        sub = next((t for s, e, t in subs if s <= mid < e), "")
        key = (hook_on, sub)
        if key not in cache:
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if hook_on and style == "glow":
                draw_glow_hook(img, hook, width, seam_y if seam_y else round(height * 0.297))
                d = ImageDraw.Draw(img)
            elif hook_on and style == "box":
                top = round(height * (0.31 if split else 0.18))
                bottom = _draw_box(d, _esc(hook), f_box, width // 2, top, (255, 255, 255, 255), (0, 0, 0, 255),
                                   pad=round(width * 0.035), max_w=round(width * 0.88))
                if quote:
                    _draw_box(d, _esc(quote), f_quote, width // 2, bottom - round(width * 0.012),
                              (232, 59, 59, 255), (255, 255, 255, 255), pad=round(width * 0.03), max_w=round(width * 0.78))
            elif hook_on:
                _draw_block(d, wrap(_esc(hook.upper()), 16), f_hook, width // 2, hook_y, hook_fill, max(4, hs // 10), 4)
            if sub:
                _draw_block(d, sub, f_sub, width // 2, sub_y, (255, 255, 255, 255), max(3, fs // 12), 2)
            import campaign
            campaign.paste_logo(img, width, height)  # Kampagnen-Logo (falls aktiv) in jedes Bild
            path = outdir / f"o{len(cache):03d}.png"
            img.save(path, optimize=True)
            cache[key] = path
        lines += [f"file '{cache[key].name}'", f"duration {b - a:.3f}"]
    if not cache:
        raise RuntimeError("Clip zu kurz fuer Untertitel")
    lines.append(lines[-2])  # concat-Demuxer braucht das letzte Bild nochmal, sonst fehlt dessen Dauer
    lst = outdir / "overlay.txt"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lst


LAST_WORDS: list = []
LAST_HOOK = ""


def add_captions(mp4: Path, channel: str, seed: str = "", split: bool | None = None) -> Path:
    """Burn hook + subtitles into mp4 (in place on success). Falls back to the original on any error.
    Mit libass: ASS-Filter. Ohne libass (Homebrew auf dem Mac): Pillow-PNGs + overlay."""
    import shutil
    tmp = None
    try:
        w, h, d = probe(mp4)
        words, lang = transcribe(mp4)
        split = (os.getenv("VIDEO_FIT", "split") == "split") if split is None else split
        global LAST_WORDS, LAST_HOOK
        LAST_WORDS = words
        style = os.getenv("CAPTION_STYLE", "glow")
        hook = (make_hook(channel, seed or mp4.name, lang, words, float(os.getenv("HIGHLIGHT_AT", "42")))
                if style == "glow" else pick_hook(channel, seed or mp4.name, lang))
        LAST_HOOK = hook
        quote = pick_quote(words, around=float(os.getenv("HIGHLIGHT_AT", "42"))) if style == "box" else ""
        out = mp4.with_name(mp4.stem + "_cap.mp4")
        enc = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "copy", "-movflags", "+faststart", out.name]
        import campaign
        if style == "classic" and has_ass_filter() and not campaign.logo_path():
            ass = mp4.with_suffix(".ass")
            ass.write_text(build_ass(words, hook, w, h, d, split=split), encoding="utf-8")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp4.name, "-vf", f"ass={ass.name}"] + enc
            how = "ass"
        else:
            tmp = mp4.with_name(mp4.stem + "_ov")
            lst = build_overlay_frames(words, hook, w, h, d, tmp, split=split, quote=quote, style=style)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp4.name,
                   "-f", "concat", "-safe", "0", "-i", str(lst.relative_to(mp4.parent)),
                   "-filter_complex", "[0:v][1:v]overlay=0:0:eof_action=repeat:format=auto[v]",
                   "-map", "[v]", "-map", "0:a?", "-t", f"{d:.3f}"] + enc
            how = "pillow"
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(mp4.parent), timeout=600)
        if r.returncode or not out.exists() or out.stat().st_size < 10_000:
            print("Untertitel-Rendern fehlgeschlagen:", r.stderr[-300:]); return mp4
        print(f"Untertitel ({how}): {len(words)} Woerter, Sprache {lang}")
        mp4.unlink(); out.rename(mp4)
        return mp4
    except Exception as e:
        print("Captions uebersprungen:", e); return mp4
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
