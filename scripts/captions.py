"""Hook title + burned-in subtitles for CLIPFORGE clips (9:16, any width/height)."""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
import zlib
from functools import lru_cache
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


def _positions(height, split, hook_y_override, subtitle_y_override):
    sub_y = round(height * (0.80 if split else 0.735))      # unterhalb des 16:9-Spielfelds, oberhalb der TikTok-Bedienelemente
    hook_y = round(height * (0.40 - 0.07) if split else height * 0.22)      # im unscharfen Bereich ueber dem Spielfeld
    if hook_y_override is not None:
        hook_y = max(50, min(height - 50, int(hook_y_override)))
    if subtitle_y_override is not None:
        sub_y = max(50, min(height - 50, int(subtitle_y_override)))
    return hook_y, sub_y


def _font_sizes(width):
    return round(width * 0.078), round(width * 0.092)


def build_ass(words, hook: str, width: int, height: int, duration: float, hook_seconds: float = 2.8, split: bool = False, hook_y_override: int | None = None, subtitle_y_override: int | None = None) -> str:
    fs, hs = _font_sizes(width)
    hook_y, sub_y = _positions(height, split, hook_y_override, subtitle_y_override)
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
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    info = json.loads(result.stdout)
    video = info["streams"][0]
    return int(video["width"]), int(video["height"]), float(info["format"]["duration"])


@lru_cache(maxsize=1)
def _has_ass():
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=15,
    )
    return any(line.split()[1:3] == ["ass", "V->V"] for line in result.stdout.splitlines())


@lru_cache(maxsize=24)
def _bold_font(size):
    from PIL import ImageFont

    for name in ("DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _draw_caption(draw, text, width, y, size, columns, fill, max_height):
    size = max(1, size)
    lines = wrap(text, columns).replace("\\N", "\n")
    while True:
        font = _bold_font(size)
        stroke = max(1, size // 12)
        spacing = max(1, size // 10)
        left, top, right, bottom = draw.multiline_textbbox(
            (0, 0), lines, font=font, align="center", spacing=spacing, stroke_width=stroke,
        )
        scale = min(width * 0.9 / max(1, right - left), max_height / max(1, bottom - top))
        if scale >= 1 or size == 1:
            break
        size = max(1, int(size * scale))
    draw.multiline_text(
        ((width - right - left) / 2, y - top), lines, font=font,
        align="center", spacing=spacing, fill=fill, stroke_width=stroke, stroke_fill="black",
    )


def _write_overlay_track(work, words, hook, width, height, duration, options):
    """Write one alpha frame per change instead of a stream of repeated PNGs."""
    from PIL import Image, ImageDraw

    sub_size, hook_size = _font_sizes(width)
    hook_y, sub_y = _positions(
        height, options["split"], options["hook_y_override"], options["subtitle_y_override"],
    )
    hook_limit = sub_y if hook_y < sub_y else height
    hook_height = max(1, hook_limit - hook_y - sub_size // 4)
    end = max(1, round(duration * 100))
    hook_end = max(0, min(end, round(options["hook_seconds"] * 100)))
    events = []
    for start, stop, text in group_words(words):
        start, stop = max(0, round(start * 100)), min(end, round(stop * 100))
        if text and start < stop:
            events.append((start, stop, text))
    breaks = {0, hook_end, end}
    for start, stop, _ in events:
        breaks.update((start, stop))
    points = sorted(breaks)
    listing = ["ffconcat version 1.0"]
    files = {}
    for start, stop in zip(points, points[1:]):
        current_hook = hook.upper() if start < hook_end else ""
        subtitle = next((text for a, b, text in events if a <= start < b), "")
        key = current_hook, subtitle
        if key not in files:
            frame = Image.new("RGBA", (width, height))
            draw = ImageDraw.Draw(frame)
            if current_hook:
                _draw_caption(draw, current_hook, width, hook_y, hook_size, 16,
                              "white" if options["split"] else "#ffd200", hook_height)
            if subtitle:
                _draw_caption(draw, subtitle, width, sub_y, sub_size, 14, "white", height - sub_y)
            name = f"overlay-{len(files):04d}.png"
            frame.save(work / name, compress_level=1)
            files[key] = name
        name = files[key]
        listing.extend((f"file {name}", "option framerate 100", f"duration {(stop - start) / 100:.2f}"))
    # The concat demuxer needs the final file repeated to represent its hold.
    listing.extend((f"file {name}", "option framerate 100"))
    path = work / "overlay.ffconcat"
    path.write_text("\n".join(listing) + "\n", encoding="utf-8")
    return path.name


def burn_captions(
    source: Path, output: Path, words, hook: str, *, split: bool = False,
    hook_seconds: float = 2.8, hook_y_override: int | None = None,
    subtitle_y_override: int | None = None, master_seconds: float | None = None,
) -> Path:
    """Render with ASS when available, using PNG alpha overlays as a fallback."""
    source, output = source.resolve(), output.resolve()
    width, height, duration = probe(source)
    duration = master_seconds if master_seconds is not None else duration
    options = dict(split=split, hook_seconds=hook_seconds, hook_y_override=hook_y_override,
                   subtitle_y_override=subtitle_y_override)
    video_tail = ",tpad=stop_mode=clone:stop_duration=1,fps=30:start_time=0" if master_seconds is not None else ""
    audio_args = ["-c:a", "copy"] if master_seconds is None else [
        "-af", f"apad,atrim=duration={master_seconds},asetpts=N/SR/TB",
        "-frames:v", str(round(master_seconds * 30)), "-t", str(master_seconds),
        "-c:a", "aac", "-b:a", "160k",
    ]
    with tempfile.TemporaryDirectory(prefix=".captions-", dir=output.parent) as temp:
        work = Path(temp)
        staged = work / "rendered.mp4"
        base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
        encoding = [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            *audio_args, "-movflags", "+faststart", staged.name,
        ]

        def render(filters):
            return subprocess.run(
                base + filters + encoding, cwd=work, capture_output=True, text=True, timeout=480,
            )

        if _has_ass():
            (work / "captions.ass").write_text(
                build_ass(words, hook, width, height, duration, **options), encoding="utf-8",
            )
            result = render(["-vf", "ass=captions.ass" + video_tail])
            if result.returncode == 0 and staged.is_file() and staged.stat().st_size > 0:
                staged.replace(output)
                return output
        track = _write_overlay_track(work, words, hook, width, height, duration, options)
        result = render([
            "-f", "concat", "-safe", "0", "-i", track,
            "-filter_complex", "[0:v][1:v]overlay=eof_action=pass:repeatlast=0" + video_tail + "[v]",
            "-map", "[v]", "-map", "0:a:0?",
        ])
        if result.returncode or not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError("FFmpeg Untertitel/Hook-Render: " + result.stderr[-300:].strip())
        staged.replace(output)
        return output


def add_captions(mp4: Path, channel: str, seed: str = "", split: bool | None = None) -> Path:
    """Burn hook + subtitles into mp4 (in place on success). Falls back to the original on any error."""
    try:
        words, lang = transcribe(mp4)
        burn_captions(
            mp4, mp4, words, pick_hook(channel, seed or mp4.name, lang),
            split=(os.getenv("VIDEO_FIT", "split") == "split") if split is None else split,
        )
        print(f"Untertitel: {len(words)} Woerter, Sprache {lang}")
        return mp4
    except Exception as e:
        print("Captions uebersprungen:", e); return mp4
