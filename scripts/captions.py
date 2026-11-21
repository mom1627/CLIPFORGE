"""Hook title + burned-in subtitles for CLIPFORGE clips (9:16, any width/height)."""
from __future__ import annotations
import os, subprocess, zlib
from pathlib import Path

HOOKS = {
    "de": ["Das hat niemand kommen sehen", "Warte bis zum Ende", "{s} dreht komplett durch",
           "Diese Reaktion ist Gold", "Das ist doch nicht sein Ernst", "Schau genau hin", "Der Chat explodiert"],
    "en": ["Nobody saw this coming", "Wait for the end", "{s} completely loses it",
           "This reaction is gold", "This can't be real", "Watch closely", "Chat is going crazy"],
}


def pick_hook(channel: str, seed: str, lang: str) -> str:
    custom = [h.strip() for h in os.getenv("HOOKS", "").split("|") if h.strip()]
    pool = custom or HOOKS.get(lang[:2], HOOKS["en"])
    return pool[zlib.crc32(seed.encode()) % len(pool)].format(s=channel)


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


def build_overlay_frames(words, hook: str, width: int, height: int, duration: float, outdir: Path,
                         hook_seconds: float = 2.8, split: bool = False) -> Path:
    """Zeichnet Hook + Untertitel als transparente PNGs und schreibt eine concat-Liste (Bild + Dauer)."""
    from PIL import Image, ImageDraw
    fs, hs = round(width * 0.078), round(width * 0.092)
    sub_y = round(height * (0.80 if split else 0.735))
    hook_y = round(height * (0.40 - 0.07) if split else height * 0.22)
    f_sub, f_hook = _font(fs), _font(hs)
    hook_fill = (255, 255, 255, 255) if split else (255, 210, 0, 255)
    hook_end = min(hook_seconds, duration)
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
            if hook_on:
                _draw_block(d, wrap(_esc(hook.upper()), 16), f_hook, width // 2, hook_y, hook_fill, max(4, hs // 10), 4)
            if sub:
                _draw_block(d, sub, f_sub, width // 2, sub_y, (255, 255, 255, 255), max(3, fs // 12), 2)
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


def add_captions(mp4: Path, channel: str, seed: str = "", split: bool | None = None) -> Path:
    """Burn hook + subtitles into mp4 (in place on success). Falls back to the original on any error.
    Mit libass: ASS-Filter. Ohne libass (Homebrew auf dem Mac): Pillow-PNGs + overlay."""
    import shutil
    tmp = None
    try:
        w, h, d = probe(mp4)
        words, lang = transcribe(mp4)
        split = (os.getenv("VIDEO_FIT", "split") == "split") if split is None else split
        hook = pick_hook(channel, seed or mp4.name, lang)
        out = mp4.with_name(mp4.stem + "_cap.mp4")
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "copy", "-movflags", "+faststart", out.name]
        if has_ass_filter():
            ass = mp4.with_suffix(".ass")
            ass.write_text(build_ass(words, hook, w, h, d, split=split), encoding="utf-8")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp4.name, "-vf", f"ass={ass.name}"] + enc
            how = "ass"
        else:
            tmp = mp4.with_name(mp4.stem + "_ov")
            lst = build_overlay_frames(words, hook, w, h, d, tmp, split=split)
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
