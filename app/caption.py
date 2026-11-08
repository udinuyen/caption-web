#!/usr/bin/env python3
"""Caption engine: video -> faster-whisper -> ASS/SRT -> ffmpeg burn-in.

Two styles, matching what the owner actually uses for YouTube Shorts:
- "sentence" (default): sentence-level, big bold white text on a solid
  black box, max 2 lines, lifted above the Shorts UI zone. Easy to read.
- "word": word-by-word pop captions (CapCut style, uppercase).
"""
import re
import subprocess
import textwrap
from pathlib import Path

# Loaded lazily, once, and reused for every job (model download is slow).
_MODEL = None


def get_model(model_name: str):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _MODEL


def release_model():
    """Drop the Whisper model from RAM. On the 512 MB free tier the
    ffmpeg burn step that follows needs that room, or the container
    gets OOM-killed mid-encode and the job is lost."""
    global _MODEL
    _MODEL = None
    import gc
    gc.collect()


def probe(path: Path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1",
        str(path)], text=True)
    w = h = None
    dur = 0.0
    for line in out.splitlines():
        if line.startswith("width="):
            w = int(line.split("=")[1])
        elif line.startswith("height="):
            h = int(line.split("=")[1])
        elif line.startswith("duration="):
            dur = float(line.split("=")[1])
    if not w or not h:
        raise RuntimeError("Không đọc được kích thước video (file hỏng?)")
    return w, h, dur


def fmt_ass(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{int(s):02d}.{int((s % 1) * 100):02d}"


def fmt_srt(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def transcribe(video: Path, model_name: str, language: str):
    """Return (segments, detected_language). Each segment is a dict with
    start/end/text and per-word timings."""
    model = get_model(model_name)
    lang = None if language in ("", "auto") else language
    segments_iter, info = model.transcribe(
        str(video), language=lang, word_timestamps=True,
        vad_filter=True, beam_size=1)
    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({"start": w.start, "end": w.end,
                              "word": w.word.strip()})
        segments.append({"start": seg.start, "end": seg.end,
                         "text": seg.text.strip(), "words": words})
    if not segments:
        raise RuntimeError(
            "Whisper không nghe thấy lời nào trong video. "
            "Kiểm tra video có tiếng nói không, hoặc thử ngôn ngữ khác.")
    return segments, (info.language or language or "auto")


def split_sentence_chunks(segments, max_chars=42, max_dur=4.5):
    """Split long Whisper segments into readable chunks (<=2 lines of
    ~40 chars, <= ~5s each), timing split proportionally by characters."""
    chunks = []
    for seg in segments:
        text = re.sub(r"\s+", " ", seg["text"]).strip()
        if not text:
            continue
        dur = max(seg["end"] - seg["start"], 0.1)
        if len(text) <= max_chars and dur <= max_dur:
            chunks.append((seg["start"], seg["end"], text))
            continue
        pieces = textwrap.wrap(text, width=max_chars, break_long_words=False,
                               break_on_hyphens=False)
        total = sum(len(p) for p in pieces) or 1
        cursor = seg["start"]
        for p in pieces:
            d = dur * (len(p) / total)
            chunks.append((cursor, cursor + d, p))
            cursor += d
    return chunks


def wrap_two_lines(text: str, width=21) -> str:
    # DejaVu Sans Bold at font size 64 on a 1080-wide frame only fits
    # ~20 characters per line (verified on a real rendered frame), so
    # wrapping is measured in those units, not in "40 chars" guesses.
    lines = textwrap.wrap(text, width=width, break_long_words=False,
                          break_on_hyphens=False)
    return r"\N".join(lines[:2])


ASS_HEADER = """[Script Info]
Title: Auto Caption Web
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass_sentence(segments, out: Path, play_w: int, play_h: int):
    scale = play_w / 1080.0
    font_size = max(28, round(64 * scale))
    margin_v = max(60, round(play_h * 400 / 1920))
    # BorderStyle 3 = solid opaque box behind text (the easy-read style).
    style = (f"Style: Caption,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,"
             f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,2,30,30,"
             f"{margin_v},1")
    lines = [ASS_HEADER.format(w=play_w, h=play_h, style=style)]
    srt = []
    for i, (s, e, text) in enumerate(split_sentence_chunks(segments), 1):
        if e - s < 0.4:
            e = s + 0.4
        lines.append(f"Dialogue: 0,{fmt_ass(s)},{fmt_ass(e)},Caption,,0,0,0,,"
                     f"{wrap_two_lines(text)}")
        srt.append(f"{i}\n{fmt_srt(s)} --> {fmt_srt(e)}\n{text}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    return len(lines) - 1


def build_ass_word(segments, out: Path, play_w: int, play_h: int):
    scale = play_w / 1080.0
    font_size = max(26, round(58 * scale))
    margin_v = max(50, round(play_h * 320 / 1920))
    style = (f"Style: Caption,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,"
             f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,30,30,"
             f"{margin_v},1")
    lines = [ASS_HEADER.format(w=play_w, h=play_h, style=style)]
    srt = []
    count = 0
    for i, seg in enumerate(segments, 1):
        if seg["text"]:
            srt.append(f"{i}\n{fmt_srt(seg['start'])} --> "
                       f"{fmt_srt(seg['end'])}\n{seg['text']}\n")
        for w in seg["words"]:
            word = w["word"].strip().upper()
            if not word:
                continue
            s, e = w["start"], w["end"]
            if e - s < 0.12:
                e = s + 0.12
            lines.append(f"Dialogue: 0,{fmt_ass(s)},{fmt_ass(e)},Caption,,"
                         f"0,0,0,,{word}")
            count += 1
    if count == 0:
        raise RuntimeError("Whisper không trả về mốc thời gian từng chữ.")
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    return count


def burn(video: Path, ass: Path, out: Path, to_916: bool, boost_audio: bool,
         src_w: int, src_h: int):
    vf = []
    if to_916:
        vf.append("scale=1080:1920:force_original_aspect_ratio=decrease")
        vf.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
    # Escape the ass path for the ffmpeg filter parser.
    ass_esc = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    vf.append(f"ass='{ass_esc}'")
    import os
    # ultrafast + few threads uses far less RAM than veryfast; the free
    # tier sets these env vars, bigger plans keep the better defaults.
    preset = os.environ.get("FFMPEG_PRESET", "veryfast")
    cmd = ["ffmpeg", "-y", "-i", str(video), "-vf", ",".join(vf),
           "-c:v", "libx264", "-crf", "18", "-preset", preset,
           "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    threads = os.environ.get("FFMPEG_THREADS")
    if threads:
        cmd += ["-threads", str(threads)]
    if boost_audio:
        # Gentle loudness normalisation for quiet phone/CapCut exports.
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac",
                "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy"]
    cmd.append(str(out))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg burn phụ đề lỗi: "
                           + result.stderr[-800:])
    return out
