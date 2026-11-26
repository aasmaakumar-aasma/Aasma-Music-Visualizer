import os, sys, glob, json, random, subprocess, urllib.request, urllib.parse
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from google import genai
from google.genai import types
from groq import Groq

THEMES = {
    "romantic": {
        "emoji": "🌹", "glow": "&H00B469FF", "w1": "0xf472b6", "w2": "0xfb7185",
        "accent": "0xf472b6", "tint": (244, 114, 182),
        "wiki": "blooming roses garden sunset nature landscape"
    },
    "sad": {
        "emoji": "🥀", "glow": "&H00F8BD38", "w1": "0x38bdf8", "w2": "0x818cf8",
        "accent": "0x38bdf8", "tint": (56, 189, 248),
        "wiki": "misty mountain lake forest rain nature landscape"
    },
    "sufi": {
        "emoji": "🌙", "glow": "&H004BB6F5", "w1": "0xfbbf24", "w2": "0xf59e0b",
        "accent": "0xfbbf24", "tint": (245, 158, 11),
        "wiki": "golden sunset mountains river valley nature landscape"
    },
    "energetic": {
        "emoji": "🔥", "glow": "&H00EED322", "w1": "0x22d3ee", "w2": "0xe879f9",
        "accent": "0x22d3ee", "tint": (34, 211, 238),
        "wiki": "waterfall ocean waves sunrise dramatic nature landscape"
    },
    "lofi": {
        "emoji": "🌿", "glow": "&H00A7F3D0", "w1": "0x34d399", "w2": "0x38bdf8",
        "accent": "0x34d399", "tint": (52, 211, 153),
        "wiki": "green pine forest stream flowers peaceful nature landscape"
    }
}

def get_audio_duration(audio_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    return float(subprocess.check_output(cmd).decode().strip())

def format_ass_time(seconds):
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def transcribe_with_groq(audio_path):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        client = Groq(api_key=api_key)
        with open(audio_path, "rb") as f:
            tr = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"]
            )
        raw = tr.model_dump() if hasattr(tr, "model_dump") else dict(tr)
        segments = raw.get("segments") or []
        words = raw.get("words") or []
        print(f"Groq Whisper extracted {len(segments)} segments and {len(words)} words.")
        return {"segments": segments, "words": words}
    except Exception as e:
        print("Groq Whisper fallback:", e)
        return None

def analyze_and_sync_lyrics(audio_path):
    groq_data = transcribe_with_groq(audio_path)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    audio_file = client.files.upload(file=audio_path)

    if groq_data and groq_data["segments"]:
        compact_segs = [
            {"start": round(float(s.get("start", 0)), 2), "end": round(float(s.get("end", 0)), 2), "text": str(s.get("text", "")).strip()}
            for s in groq_data["segments"] if str(s.get("text", "")).strip()
        ]
        prompt = (
            "You are given the song audio AND exact Whisper timestamped segments below. "
            "1. Detect the primary mood from ONLY one of: romantic, sad, sufi, energetic, lofi. "
            "2. Write a short cinematic real-Earth nature photography prompt (12-18 words) matching the mood (e.g. misty mountains, forest, waterfall, flowers, sunset; NO space, NO text, NO people). "
            "3. Convert every single segment into clean, natural Hinglish (Hindi written in Roman script, e.g. 'Khamoshiyan bhi ab kuch kehti hain'). "
            "Keep the exact start/end timestamps from Whisper (split any very long segment >9 words into 2 balanced lines with proportional timestamps). Do NOT skip any sung line. "
            f"Whisper segments:\n{json.dumps(compact_segs, ensure_ascii=False)}\n"
            "Return ONLY valid JSON: {\"mood\": \"sad\", \"scene_prompt\": \"...\", \"lyrics\": [{\"start\": 2.0, \"end\": 5.5, \"text\": \"...\"}]}"
        )
    else:
        prompt = (
            "Listen carefully to this entire song. "
            "1. Detect the primary mood from ONLY one of: romantic, sad, sufi, energetic, lofi. "
            "2. Write a short cinematic real-Earth nature photography prompt (12-18 words) matching the mood (NO space, NO text, NO people). "
            "3. Transcribe ALL sung lyrics into natural Hinglish (Roman script) broken into short lines (4-8 words) with accurate start and end timestamps in seconds. "
            "Return ONLY valid JSON: {\"mood\": \"sad\", \"scene_prompt\": \"...\", \"lyrics\": [{\"start\": 2.0, \"end\": 5.5, \"text\": \"...\"}]}"
        )

    import time
    text = None
    for model_name in ["gemini-2.5-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[audio_file, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            text = response.text.strip()
            break
        except Exception as e:
            print(f"Gemini {model_name} busy ({e}), retrying...")
            time.sleep(5)
    if not text:
        fallback_lyrics = [
            {"start": round(float(seg.get("start", 0)), 2), "end": round(float(seg.get("end", 0)), 2), "text": str(seg.get("text", "")).strip()}
            for seg in (groq_data["segments"] if groq_data and groq_data.get("segments") else [])
            if str(seg.get("text", "")).strip()
        ]
        text = json.dumps({"mood": "sad", "scene_prompt": "misty mountain lake forest rain nature landscape", "lyrics": fallback_lyrics})
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    mood = str(data.get("mood", "lofi")).lower().strip()
    if mood not in THEMES:
        mood = "lofi"
    scene_prompt = str(data.get("scene_prompt", "")).strip() or f"cinematic 4k nature photography, {THEMES[mood]['wiki']}, soft atmospheric light, no text"
    lyrics = sanitize_lyrics(data.get("lyrics", []))
    print(f"Mood: {mood} | Final synced lines: {len(lyrics)}")
    return mood, scene_prompt, lyrics

def sanitize_lyrics(raw_lyrics):
    clean = []
    for item in raw_lyrics:
        txt = str(item.get("text", "")).replace("\n", " ").replace("{", "").replace("}", "").strip()
        if not txt:
            continue
        st = max(0.0, float(item.get("start", 0)))
        en = float(item.get("end", st + 3.0))
        if en <= st + 0.3:
            en = st + 2.8
        clean.append({"start": st, "end": en, "text": txt})
    clean.sort(key=lambda x: x["start"])
    for i in range(len(clean) - 1):
        if clean[i]["end"] > clean[i + 1]["start"]:
            clean[i]["end"] = max(clean[i]["start"] + 0.4, clean[i + 1]["start"] - 0.05)
    return clean

def download_image(url, timeout=22):
    req = urllib.request.Request(url, headers={"User-Agent": "AasmaMusicStudio/5.0 (https://github.com/aasmaakumar-aasma)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    img = Image.open(BytesIO(data)).convert("RGB")
    if img.width < 400 or img.height < 250:
        raise ValueError("Image too small")
    return img

def fetch_nature_background(scene_prompt, theme, width=1600, height=900):
    try:
        full_prompt = f"{scene_prompt}, cinematic nature photography, moody lighting, 8k, no text, no watermark"
        seed = random.randint(1000, 99999)
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_prompt)}?width={width}&height={height}&nologo=true&seed={seed}"
        print("Fetching AI nature scene...")
        return download_image(url, timeout=25).resize((width, height), Image.LANCZOS)
    except Exception as e:
        print("AI scene fallback:", e)

    try:
        q = urllib.parse.quote(f"filetype:bitmap {theme['wiki']}")
        api = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrsearch={q}&gsrlimit=8&prop=imageinfo&iiprop=url&iiurlwidth={width}&format=json"
        req = urllib.request.Request(api, headers={"User-Agent": "AasmaMusicStudio/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
        pages = list(res.get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for p in pages:
            info = p.get("imageinfo", [{}])[0]
            img_url = info.get("thumburl") or info.get("url")
            if img_url and any(img_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png"]):
                img = download_image(img_url, timeout=20)
                target_ratio = width / height
                cur_ratio = img.width / img.height
                if cur_ratio > target_ratio:
                    new_w = int(img.height * target_ratio)
                    left = (img.width - new_w) // 2
                    img = img.crop((left, 0, left + new_w, img.height))
                else:
                    new_h = int(img.width / target_ratio)
                    top = (img.height - new_h) // 2
                    img = img.crop((0, top, img.width, top + new_h))
                return img.resize((width, height), Image.LANCZOS)
    except Exception as e:
        print("Wikimedia fallback:", e)

    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / height
        arr[y, :] = [int(15 + 25*t), int(28 + 30*t), int(38 + 35*t)]
    return Image.fromarray(arr, "RGB")

def build_background_and_thumbnail(bg_path, thumb_path, title, scene_prompt, theme, photo_path=None):
    width, height = 1600, 900
    img = fetch_nature_background(scene_prompt, theme, width, height).convert("RGBA")
    img = Image.alpha_composite(img, Image.new("RGBA", (width, height), (6, 10, 18, 128)))

    has_photo = False
    if photo_path and os.path.exists(photo_path):
        try:
            from rembg import remove
            with open(photo_path, "rb") as f:
                cutout_bytes = remove(f.read())
            fg = Image.open(BytesIO(cutout_bytes)).convert("RGBA")
            target_h = int(height * 0.78)
            ratio = target_h / fg.height
            fg = fg.resize((int(fg.width * ratio), target_h), Image.LANCZOS)
            fg = Image.alpha_composite(fg, Image.new("RGBA", fg.size, (*theme["tint"], 55)))
            r, g, b, a = fg.split()
            a_np = np.array(a, dtype=np.float32)
            fade = np.clip(np.linspace(1.0, 0.0, fg.height).reshape(-1, 1) * 2.2, 0, 1)
            fg.putalpha(Image.fromarray((a_np * 0.38 * fade).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)))
            img.alpha_composite(fg, dest=((width - fg.width) // 2, height - fg.height + 15))
            has_photo = True
        except Exception as e:
            print("Portrait skipped:", e)

    yn, xn = np.mgrid[0:height, 0:width].astype(np.float32)
    vx = (xn / width - 0.5) * 2
    vy = (yn / height - 0.5) * 2
    vig = np.clip((vx**2 + vy**2) * 0.48, 0, 0.72)
    arr = np.array(img.convert("RGB"), dtype=np.float32) * (1.0 - vig[:, :, None])
    final_bg = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    final_bg.save(bg_path)

    thumb = final_bg.resize((1280, 720), Image.LANCZOS).convert("RGBA")
    td = ImageDraw.Draw(thumb)
    try:
        f_title = ImageFont.truetype("/usr/share/fonts/truetype/lato/Lato-Bold.ttf", 74)
        f_sub = ImageFont.truetype("/usr/share/fonts/truetype/lato/Lato-Bold.ttf", 28)
    except Exception:
        f_title = f_sub = ImageFont.load_default()
    bbox = td.textbbox((0, 0), title, font=f_title)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (1280 - tw) // 2, (720 - th) // 2 - 15
    td.text((tx + 4, ty + 4), title, font=f_title, fill=(0, 0, 0, 180))
    td.text((tx, ty), title, font=f_title, fill=(255, 255, 255, 245))
    td.text((48, 36), "AASMA MUSIC", font=f_sub, fill=(*theme["tint"], 235))
    thumb.convert("RGB").save(thumb_path, quality=92)
    return has_photo

def generate_emoji_png(out_path, emoji_char, theme, has_photo):
    if has_photo:
        Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(out_path)
        return
    canvas = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    aura = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    ImageDraw.Draw(aura).ellipse([42, 42, 138, 138], fill=(*theme["tint"], 110))
    canvas = Image.alpha_composite(canvas, aura.filter(ImageFilter.GaussianBlur(22)))
    try:
        efont = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)
        d = ImageDraw.Draw(canvas)
        bbox = d.textbbox((0, 0), emoji_char, font=efont)
        ew, eh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((180 - ew) // 2, (180 - eh) // 2 - 6), emoji_char, font=efont, embedded_color=True)
    except Exception:
        ImageDraw.Draw(canvas).ellipse([65, 65, 115, 115], fill=(*theme["tint"], 230))
    canvas.save(out_path)

def generate_thin_bar_mask(out_path, width=1160, height=115):
    mask = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(mask)
    for x in range(6, width - 4, 14):
        d.rectangle([x, 0, x + 3, height], fill=(255, 255, 255))
    mask.save(out_path)

def build_karaoke_text(text, duration_sec):
    words = text.split()
    if not words:
        return text
    total_cs = max(30, int(duration_sec * 100))
    total_chars = sum(len(w) for w in words) or 1
    out = []
    for w in words:
        w_cs = max(8, int(total_cs * (len(w) / total_chars)))
        out.append(f"{{\\kf{w_cs}}}{w}")
    return " ".join(out)

def write_karaoke_3line_ass(lyrics, ass_path, theme, total_duration):
    glow = theme["glow"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PrevLine,Lato,28,&H90E2E8F0,&H90E2E8F0,&H90000000,&H00000000,0,0,0,0,100,100,0.4,0,1,1,0,5,100,100,40,1
Style: Active,Lato,54,&H00FFFFFF,&H68CBD5E1,{glow},&H55000000,-1,0,0,0,100,100,0.8,0,1,2.2,1,5,80,80,40,1
Style: NextLine,Lato,29,&H78E2E8F0,&H78E2E8F0,&H90000000,&H00000000,0,-1,0,0,100,100,0.4,0,1,1,0,5,100,100,40,1
Style: GapDots,Lato,36,&H55FFFFFF,&H55FFFFFF,{glow},&H00000000,-1,0,0,0,100,100,6,0,1,1.5,0,5,80,80,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    prev_end = 0.0
    for i, item in enumerate(lyrics):
        st, en, txt = item["start"], item["end"], item["text"]
        # Instrumental gap indicator if > 4.5s silence/music
        if st - prev_end >= 4.5:
            g_st, g_en = prev_end + 0.6, st - 0.6
            lines.append(
                f"Dialogue: 0,{format_ass_time(g_st)},{format_ass_time(g_en)},GapDots,,0,0,0,,"
                f"{{\\pos(640,348)\\fad(500,500)\\blur2}}•  •  •\n"
            )
        if i > 0:
            lines.append(
                f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},PrevLine,,0,0,0,,"
                f"{{\\pos(640,285)\\fad(240,240)}}{lyrics[i - 1]['text']}\n"
            )
        k_txt = build_karaoke_text(txt, en - st)
        lines.append(
            f"Dialogue: 1,{format_ass_time(st)},{format_ass_time(en)},Active,,0,0,0,,"
            f"{{\\move(640,366,640,348,0,280)\\fad(220,220)\\blur1.5}}{k_txt}\n"
        )
        if i + 1 < len(lyrics):
            lines.append(
                f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},NextLine,,0,0,0,,"
                f"{{\\pos(640,415)\\fad(240,220)}}{lyrics[i + 1]['text']}\n"
            )
        prev_end = en

    if total_duration - prev_end >= 4.5:
        lines.append(
            f"Dialogue: 0,{format_ass_time(prev_end + 0.6)},{format_ass_time(total_duration - 0.5)},GapDots,,0,0,0,,"
            f"{{\\pos(640,348)\\fad(500,500)\\blur2}}•  •  •\n"
        )
    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def main():
    audio_path = sys.argv[1]
    out_mp4 = sys.argv[2]
    out_thumb = sys.argv[3]
    title = os.path.splitext(os.path.basename(audio_path))[0].replace("_", " ").title()
    duration = get_audio_duration(audio_path)

    photos = glob.glob("input_photo/*")
    photo_path = photos[0] if photos else None

    print("1/4 Transcribing with Groq Whisper v3 + Hinglish Karaoke Sync...")
    mood, scene_prompt, lyrics = analyze_and_sync_lyrics(audio_path)
    theme = THEMES[mood]

    bg_path = "/tmp/nature_bg.png"
    emoji_path = "/tmp/mood_emoji.png"
    mask_path = "/tmp/bar_mask.png"
    ass_path = "/tmp/lyrics.ass"

    print("2/4 Building nature background + HD thumbnail + pulsing emoji...")
    has_photo = build_background_and_thumbnail(bg_path, out_thumb, title, scene_prompt, theme, photo_path)
    generate_emoji_png(emoji_path, theme["emoji"], theme, has_photo)
    generate_thin_bar_mask(mask_path)

    print("3/4 Writing 3-line Word-by-Word Karaoke ASS...")
    write_karaoke_3line_ass(lyrics, ass_path, theme, duration)

    print("4/4 Rendering Karaoke Nature Studio v5 MP4...")
    fps = 25
    total_frames = max(1, int(duration * fps))
    safe_title = title.replace("'", "").replace(":", "")

    filter_complex = (
        f"[0:v]scale=1280:720,format=rgba[bg];"
        f"[2:v]scale=130:-1,format=rgba[em];"
        f"[bg][em]overlay=x='(W-w)/2':y='155-(h/2)+sin(t*3.2)*6':shortest=1[bg_em];"
        f"[1:a]showfreqs=s=145x115:mode=bar:ascale=sqrt:fscale=log:colors={theme['w1']}|{theme['w2']}:win_size=1024:averaging=3,"
        f"fps={fps},scale=1160:115:flags=neighbor,format=rgb24[eq_raw];"
        f"[3:v]format=rgb24[mask_rgb];"
        f"[eq_raw][mask_rgb]blend=all_mode=multiply:shortest=1,colorkey=0x000000:0.06:0.06,format=rgba[eq_sharp];"
        f"[bg_em][eq_sharp]overlay=60:565:shortest=1,"
        f"ass={ass_path},"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='{safe_title}':fontcolor=white@0.9:fontsize=24:x=44:y=34:shadowcolor=black@0.7:shadowx=2:shadowy=2,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='AASMA MUSIC':fontcolor={theme['accent']}@0.95:fontsize=22:x=w-tw-44:y=35:shadowcolor=black@0.7:shadowx=2:shadowy=2,"
        f"drawbox=x=60:y=694:w=1160:h=3:color=white@0.20:t=fill,"
        f"drawbox=x=60:y=694:w='1160*t/{duration}':h=3:color={theme['accent']}@0.95:t=fill,"
        f"format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-r", str(fps), "-i", bg_path,
        "-i", audio_path,
        "-loop", "1", "-r", str(fps), "-i", emoji_path,
        "-loop", "1", "-r", str(fps), "-i", mask_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4
    ]
    subprocess.run(cmd, check=True)
    meta = {
        "audio_path": audio_path, "thumb_path": out_thumb, "title": title,
        "mood": mood, "theme": theme, "lyrics": lyrics, "duration": duration,
        "short_start": lyrics[min(len(lyrics)//3, len(lyrics)-1)]["start"] if lyrics else min(20.0, duration*0.25),
        "short_end": (lyrics[min(len(lyrics)//3, len(lyrics)-1)]["start"] + 52.0) if lyrics else min(72.0, duration)
    }
    with open("/tmp/aasma_meta.json", "w", encoding="utf-8") as mf:
        json.dump(meta, mf, ensure_ascii=False)
    print("Done:", out_mp4, "| Thumbnail:", out_thumb)

if __name__ == "__main__":
    main()
