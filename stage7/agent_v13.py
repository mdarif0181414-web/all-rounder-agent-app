# Agent v13 (development phase, step 8 — 2026-11-20): v12 + production
# tools. The agent could only write text packages; now it can produce:
#   make_narration  — Gemini TTS (3.1 Flash, probed working) -> WAV
#   make_image      — Gemini image models -> PNG (NOTE: free image
#                     quota was EXHAUSTED on probe day 2026-11-20; the
#                     tool returns a clean quota error when blocked)
#   make_card_image — local Pillow title-card PNG (the honest fallback
#                     visual when image quota is gone; must be
#                     disclosed in the production report)
#   assemble_video  — ffmpeg: stills + per-scene narration -> 1080p MP4
#                     (CRF 17 master rule), returns measured durations.
import json
import os
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_v12 as v12  # noqa: E402  (v11 + lesson memory)

WORK = os.path.join(HERE, "work_prod1")
v7 = v12.v7
mem = v12.mem  # agent_v6: client()

TTS_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]
IMG_MODELS = ["gemini-2.5-flash-image", "gemini-3.1-flash-image",
              "gemini-3-pro-image-preview"]


def set_work(path):
    global WORK
    WORK = path
    v12.set_work(path)


set_work(WORK)

from pydantic import BaseModel  # noqa: E402


class NarrationArgs(BaseModel):
    text: str
    voice: str = "Algieba"
    out_name: str


class ImageArgs(BaseModel):
    prompt: str
    out_name: str


class CardArgs(BaseModel):
    title: str
    subtitle: str = ""
    out_name: str


class AssembleArgs(BaseModel):
    image_files: list
    audio_files: list
    out_name: str = "final_video.mp4"


def _path(name):
    p = os.path.normpath(os.path.join(WORK, name))
    if not p.startswith(os.path.normpath(WORK) + os.sep):
        return None
    return p


def _err(msg, **kw):
    d = {"status": "error", "error": msg}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


def make_narration(text: str, voice: str = "Algieba",
                   out_name: str = "narration.wav") -> str:
    """Generate spoken narration audio (WAV) from text with Gemini TTS.

    One call per scene/segment — keep text under ~900 characters.
    Returns the measured duration in seconds; never estimate it.

    Args:
        text: The exact words to speak.
        voice: Prebuilt voice name (e.g. Algieba, Charon).
        out_name: WAV filename inside the work folder.
    Returns:
        JSON string with file, seconds, bytes.
    """
    if len(text) > 900:
        return _err("text খুব লম্বা — scene ধরে ভাগ করে আলাদা call করো")
    path = _path(out_name)
    if path is None:
        return _err("work folder-এর বাইরে যাওয়া যায় না")
    from google.genai import types
    last = None
    for model in TTS_MODELS:
        try:
            r = mem.client().models.generate_content(
                model=model, contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice)))))
            pcm = r.candidates[0].content.parts[0].inline_data.data
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            secs = len(pcm) / (24000 * 2)
            return json.dumps({"status": "ok", "file": out_name,
                               "model": model, "voice": voice,
                               "seconds": round(secs, 2),
                               "bytes": os.path.getsize(path)},
                              ensure_ascii=False)
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:140]}"
    return _err(f"TTS ব্যর্থ: {last}")


def make_image(prompt: str, out_name: str = "image.png") -> str:
    """Generate an image with a Gemini image model and save it as PNG.

    If the free image quota is exhausted the tool returns a quota
    error — then use make_card_image as the visual and DISCLOSE the
    fallback in the production report.

    Args:
        prompt: Image description (ask for a wide 16:9 composition).
        out_name: PNG filename inside the work folder.
    Returns:
        JSON string with file, bytes, model — or a quota error.
    """
    path = _path(out_name)
    if path is None:
        return _err("work folder-এর বাইরে যাওয়া যায় না")
    last = None
    for model in IMG_MODELS:
        try:
            r = mem.client().models.generate_content(model=model,
                                                     contents=prompt)
            for part in r.candidates[0].content.parts:
                if getattr(part, "inline_data", None):
                    open(path, "wb").write(part.inline_data.data)
                    return json.dumps(
                        {"status": "ok", "file": out_name, "model": model,
                         "bytes": os.path.getsize(path)},
                        ensure_ascii=False)
            last = "response-এ image নেই"
        except Exception as e:
            s = str(e)
            if "429" in s or "RESOURCE_EXHAUSTED" in s:
                return _err("image quota শেষ (429) — make_card_image "
                            "fallback ব্যবহার করো এবং report-এ উল্লেখ করো",
                            error_type="quota")
            last = f"{type(e).__name__}: {s[:140]}"
    return _err(f"image ব্যর্থ: {last}")


def _font(size, bold=True):
    from PIL import ImageFont
    cands = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in cands:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_card_image(title: str, subtitle: str = "",
                    out_name: str = "card.png") -> str:
    """Render a clean 1920x1080 title-card PNG locally (no quota).

    Dark gradient background, big centered title, smaller subtitle.
    This is a FALLBACK visual for when AI image generation is
    unavailable — disclose its use in the production report.

    Args:
        title: Main line (short).
        subtitle: Optional second line.
        out_name: PNG filename inside the work folder.
    Returns:
        JSON string with file and size.
    """
    path = _path(out_name)
    if path is None:
        return _err("work folder-এর বাইরে যাওয়া যায় না")
    try:
        from PIL import Image, ImageDraw
        W, H = 1920, 1080
        img = Image.new("RGB", (W, H))
        px = img.load()
        for y in range(H):
            t = y / H
            px_row = (int(10 + 14 * t), int(14 + 10 * t),
                      int(34 + 30 * t))
            for x in range(0, W, 8):
                for dx in range(8):
                    if x + dx < W:
                        px[x + dx, y] = px_row
        d = ImageDraw.Draw(img)

        def wrap(text, font, maxw):
            words, lines, cur = text.split(), [], ""
            for w_ in words:
                trial = (cur + " " + w_).strip()
                if d.textlength(trial, font=font) <= maxw:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w_
            if cur:
                lines.append(cur)
            return lines

        tf = _font(92)
        lines = wrap(title, tf, 1560)[:3]
        total_h = len(lines) * 108
        y = (H - total_h) // 2 - (70 if subtitle else 0)
        for ln in lines:
            w_ = d.textlength(ln, font=tf)
            d.text(((W - w_) // 2, y), ln, font=tf, fill=(240, 240, 235))
            y += 108
        if subtitle:
            sf = _font(46, bold=False)
            slines = wrap(subtitle, sf, 1500)[:2]
            y += 26
            for ln in slines:
                w_ = d.textlength(ln, font=sf)
                d.text(((W - w_) // 2, y), ln, font=sf,
                       fill=(168, 178, 200))
                y += 58
        img.save(path)
        return json.dumps({"status": "ok", "file": out_name,
                           "size": [W, H],
                           "bytes": os.path.getsize(path)},
                          ensure_ascii=False)
    except Exception as e:
        return _err(f"card ব্যর্থ: {type(e).__name__}: {e}")


def _probe_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def assemble_video(image_files: list, audio_files: list,
                   out_name: str = "final_video.mp4") -> str:
    """Assemble a 1080p video: one still image per narration segment.

    Each image is shown for exactly its segment's audio length
    (scale+crop to 1920x1080), then all scenes are joined. Master
    quality (CRF 17). Returns the measured total duration.

    Args:
        image_files: Image filenames in scene order (work folder).
        audio_files: Narration WAV filenames in the same order.
        out_name: Output MP4 filename inside the work folder.
    Returns:
        JSON string with file, seconds, scenes, size.
    """
    if len(image_files) != len(audio_files) or not image_files:
        return _err("image আর audio file-এর সংখ্যা সমান হতে হবে")
    out = _path(out_name)
    if out is None:
        return _err("work folder-এর বাইরে যাওয়া যায় না")
    parts = []
    try:
        for i, (im, au) in enumerate(zip(image_files, audio_files)):
            ip, ap = _path(im), _path(au)
            if not ip or not ap or not os.path.exists(ip) \
                    or not os.path.exists(ap):
                return _err(f"file নেই: {im} / {au}")
            seg = _path(f"_seg_{i:02d}.mp4")
            cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30",
                   "-i", ip, "-i", ap,
                   "-filter_complex",
                   "[0:v]scale=1920:1080:force_original_aspect_ratio="
                   "increase,crop=1920:1080,format=yuv420p[v]",
                   "-map", "[v]", "-map", "1:a", "-c:v", "libx264",
                   "-crf", "17", "-preset", "veryfast", "-c:a", "aac",
                   "-b:a", "160k", "-shortest", seg]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                return _err(f"scene {i} encode ব্যর্থ: "
                            f"{r.stderr[-300:]}")
            parts.append(seg)
        lst = _path("_concat.txt")
        with open(lst, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                            "-i", lst, "-c", "copy", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return _err(f"concat ব্যর্থ: {r.stderr[-300:]}")
        secs = _probe_seconds(out)
        return json.dumps({"status": "ok", "file": out_name,
                           "seconds": round(secs, 2),
                           "scenes": len(parts),
                           "bytes": os.path.getsize(out)},
                          ensure_ascii=False)
    finally:
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass


v7.TOOLS = v7.TOOLS + [make_narration, make_image, make_card_image,
                       assemble_video]
v7.SCHEMAS = {**v7.SCHEMAS, make_narration: NarrationArgs,
              make_image: ImageArgs, make_card_image: CardArgs,
              assemble_video: AssembleArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nPRODUCTION নিয়ম (v13): video বানাতে হলে — (১) প্রতিটা scene-এর "
    "narration আলাদা make_narration call-এ; (২) visual-এর জন্য আগে "
    "make_image চেষ্টা করবে, quota error এলে make_card_image fallback "
    "নেবে এবং production report-এ সৎভাবে লিখবে কোন scene-এ কোনটা "
    "ব্যবহার হয়েছে; (৩) assemble_video দিয়ে final video; (৪) সব "
    "duration/সংখ্যা tool-এর মাপ থেকে — নিজে আন্দাজ করবে না।")

if __name__ == "__main__":
    if "--check" in sys.argv:
        print("tools:", all(n in v7.TOOL_MAP for n in
                            ["make_narration", "make_image",
                             "make_card_image", "assemble_video"]))
        sys.exit(0)
    print("[v13] library module — run via a mission runner.")
