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


def build_ass(words, hook: str, width: int, height: int, duration: float, hook_seconds: float = 2.8, split: bool = False) -> str:
    fs, hs = round(width * 0.078), round(width * 0.092)
    sub_y = round(height * (0.80 if split else 0.735))      # unterhalb des 16:9-Spielfelds, oberhalb der TikTok-Bedienelemente
    hook_y = round(height * (0.40 - 0.07) if split else height * 0.22)      # im unscharfen Bereich ueber dem Spielfeld
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


def add_captions(mp4: Path, channel: str, seed: str = "") -> Path:
    """Burn hook + subtitles into mp4 (in place on success). Falls back to the original on any error."""
    try:
        w, h, d = probe(mp4)
        words, lang = transcribe(mp4)
        ass = mp4.with_suffix(".ass")
        ass.write_text(build_ass(words, pick_hook(channel, seed or mp4.name, lang), w, h, d, split=os.getenv('VIDEO_FIT', 'split') == 'split'), encoding="utf-8")
        out = mp4.with_name(mp4.stem + "_cap.mp4")
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp4.name,
                            "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out.name],
                           capture_output=True, text=True, cwd=str(mp4.parent), timeout=300)
        if r.returncode or not out.exists() or out.stat().st_size < 10_000:
            print("Untertitel-Rendern fehlgeschlagen:", r.stderr[-300:]); return mp4
        print(f"Untertitel: {len(words)} Woerter, Sprache {lang}")
        mp4.unlink(); out.rename(mp4)
        return mp4
    except Exception as e:
        print("Captions uebersprungen:", e); return mp4
