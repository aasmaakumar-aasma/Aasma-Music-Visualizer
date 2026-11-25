import os, sys, glob, json, random, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from google import genai
from google.genai import types

THEMES = {
    "romantic": {
        "bg_top": (18, 8, 32), "bg_bot": (48, 14, 52),
        "neb1": (236, 72, 153, 65), "neb2": (139, 92, 246, 60),
        "glow": "&H00B469FF", "wave": "f472b6|c084fc", "bar": "f472b6",
        "tint": (244, 114, 182)
    },
    "sad": {
        "bg_top": (6, 12, 28), "bg_bot": (15, 23, 54),
        "neb1": (56, 189, 248, 55), "neb2": (99, 102, 241, 60),
        "glow": "&H00F8BD38", "wave": "38bdf8|818cf8", "bar": "38bdf8",
        "tint": (56, 189, 248)
    },
    "sufi": {
        "bg_top": (12, 10, 26), "bg_bot": (36, 22, 46),
        "neb1": (245, 158, 11, 55), "neb2": (124, 58, 237, 60),
        "glow": "&H004BB6F5", "wave": "fbbf24|a78bfa", "bar": "fbbf24",
        "tint": (245, 158, 11)
    },
    "energetic": {
        "bg_top": (8, 14, 24), "bg_bot": (20, 12, 44),
        "neb1": (34, 211, 238, 65), "neb2": (217, 70, 239, 65),
        "glow": "&H00EE D322".replace(" ", ""), "wave": "22d3ee|e879f9", "bar": "22d3ee",
        "tint": (34, 211, 238)
    },
    "lofi": {
        "bg_top": (10, 12, 28), "bg_bot": (28, 18, 48),
        "neb1": (168, 85, 247, 60), "neb2": (45, 212, 191, 55),
        "glow": "&H00F755A8", "wave": "2dd4bf|c084fc", "bar": "2dd4bf",
        "tint": (168, 85, 247)
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

def analyze_song_with_gemini(audio_path):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    audio_file = client.files.upload(file=audio_path)
    prompt = (
        "Listen carefully to this song. "
        "1. Detect the primary mood from ONLY one of: romantic, sad, sufi, energetic, lofi. "
        "2. Transcribe all sung lyrics into natural Hinglish (Hindi in Roman script, e.g., 'Khamoshiyan bhi ab kuch kehti hain'). "
        "Break into short clean lines (4-8 words max) with accurate start and end timestamps in seconds. "
        "Return ONLY valid JSON object: {\"mood\": \"sad\", \"lyrics\": [{\"start\": 1.2, \"end\": 4.5, \"text\": \"...\"}]}"
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_file, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    mood = str(data.get("mood", "lofi")).lower()
    if mood not in THEMES:
        mood = "lofi"
    return mood, data.get("lyrics", [])

def generate_cosmic_bg(out_path, theme, photo_path=None, width=1600, height=900):
    img = Image.new("RGB", (width, height), theme["bg_top"])
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = theme["bg_top"]
    r2, g2, b2 = theme["bg_bot"]
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=(int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t)))

    neb = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    nd.ellipse([80, 40, 1050, 680], fill=theme["neb1"])
    nd.ellipse([580, 220, 1520, 860], fill=theme["neb2"])
    nd.ellipse([380, 180, 1220, 720], fill=(255, 255, 255, 18))
    neb = neb.filter(ImageFilter.GaussianBlur(110))
    img = Image.alpha_composite(img.convert("RGBA"), neb)

    # Optional custom portrait blending
    if photo_path and os.path.exists(photo_path):
        try:
            from rembg import remove
            with open(photo_path, "rb") as f:
                cutout_bytes = remove(f.read())
            from io import BytesIO
            fg = Image.open(BytesIO(cutout_bytes)).convert("RGBA")
            target_h = int(height * 0.82)
            ratio = target_h / fg.height
            fg = fg.resize((int(fg.width * ratio), target_h), Image.LANCZOS)
            # Soft mood tint + 32% opacity blend
            tint_layer = Image.new("RGBA", fg.size, (*theme["tint"], 70))
            fg = Image.alpha_composite(fg, tint_layer)
            r, g, b, a = fg.split()
            a = a.filter(ImageFilter.GaussianBlur(3)).point(lambda p: int(p * 0.32))
            fg.putalpha(a)
            pos = ((width - fg.width) // 2, height - fg.height + 20)
            img.alpha_composite(fg, dest=pos)
        except Exception as e:
            print("Photo blend skipped:", e)

    # Soft glowing stars + bokeh
    stars = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    random.seed(int.from_bytes(os.urandom(2), "big"))
    for _ in range(320):
        x, y = random.randint(0, width-1), random.randint(0, height-1)
        rad = random.choice([1, 1, 1, 2, 2, 3])
        alpha = random.randint(90, 230)
        col = random.choice([(255,255,255,alpha), (186,230,253,alpha), (233,213,255,alpha)])
        sd.ellipse([x-rad, y-rad, x+rad, y+rad], fill=col)
    glow_stars = stars.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img, glow_stars)
    img = Image.alpha_composite(img, stars)

    # Cinematic dark vignette
    vig = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    vd.rectangle([0, 0, width, height], outline=(0, 0, 0, 210), width=110)
    vig = vig.filter(ImageFilter.GaussianBlur(95))
    img = Image.alpha_composite(img, vig).convert("RGB")
    img.save(out_path)

def generate_ui_overlay(out_path, title, theme, width=1280, height=720):
    ui = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(ui)
    # Top-left glass pill
    pill_w = min(460, max(240, len(title) * 14 + 80))
    d.rounded_rectangle([32, 26, 32 + pill_w, 72], radius=23, fill=(15, 23, 42, 125), outline=(255, 255, 255, 85), width=2)
    # Top-right glass pill
    d.rounded_rectangle([width - 250, 26, width - 32, 72], radius=23, fill=(15, 23, 42, 125), outline=(*theme["tint"], 170), width=2)
    # Progress bar track
    d.rounded_rectangle([32, height - 22, width - 32, height - 16], radius=3, fill=(255, 255, 255, 45))
    ui.save(out_path)

def write_spotify_ass(lyrics, ass_path, theme):
    glow = theme["glow"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,Lato,54,&H00FFFFFF,&H00FFFFFF,{glow},&H60000000,-1,0,0,0,100,100,0.5,0,1,2.5,0,5,70,70,40,1
Style: NextLine,Lato,34,&H75E2E8F0,&H75E2E8F0,&H90000000,&H00000000,0,-1,0,0,100,100,0.5,0,1,1,0,5,90,90,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    clean = [x for x in lyrics if str(x.get("text", "")).strip()]
    for i, item in enumerate(clean):
        st = float(item.get("start", 0))
        en = float(item.get("end", st + 3))
        txt = str(item["text"]).replace("\n", " ").strip()
        lines.append(
            f"Dialogue: 1,{format_ass_time(st)},{format_ass_time(en)},Active,,0,0,0,,"
            f"{{\\move(640,355,640,335,0,320)\\fad(280,280)\\blur2}}{txt}\n"
        )
        if i + 1 < len(clean):
            nxt = str(clean[i + 1]["text"]).replace("\n", " ").strip()
            lines.append(
                f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},NextLine,,0,0,0,,"
                f"{{\\pos(640,405)\\fad(300,250)}}( {nxt} )\n"
            )
    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def main():
    audio_path = sys.argv[1]
    out_mp4 = sys.argv[2]
    title = os.path.splitext(os.path.basename(audio_path))[0].replace("_", " ").title()
    duration = get_audio_duration(audio_path)

    photos = glob.glob("input_photo/*")
    photo_path = photos[0] if photos else None

    print("1/4 Analyzing song mood & Hinglish lyrics with Gemini...")
    mood, lyrics = analyze_song_with_gemini(audio_path)
    theme = THEMES[mood]
    print(f"Detected mood: {mood} | Lines: {len(lyrics)}")

    bg_path = "/tmp/cosmic_bg.png"
    ui_path = "/tmp/ui_overlay.png"
    ass_path = "/tmp/lyrics.ass"

    print("2/4 Generating dynamic cosmic background...")
    generate_cosmic_bg(bg_path, theme, photo_path)
    generate_ui_overlay(ui_path, title, theme)

    print("3/4 Writing Spotify-style synced lyrics...")
    write_spotify_ass(lyrics, ass_path, theme)

    print("4/4 Rendering final video with Smooth Zoom-Out + Equalizer...")
    fps = 25
    total_frames = max(1, int(duration * fps))
    filter_complex = (
        f"[0:v]zoompan=z='max(1.0,1.20-0.20*(in/{total_frames}))':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps={fps}[bg];"
        f"[bg][2:v]overlay=0:0[bg_ui];"
        f"[1:a]showfreqs=s=1216x135:mode=bar:ascale=log:fscale=log:colors={theme['wave']}:win_size=2048,"
        f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='0.88*alpha(X,Y)'[eq];"
        f"[bg_ui][eq]overlay=32:552:shortest=1,"
        f"ass={ass_path},"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='♪  {title}':fontcolor=white@0.92:fontsize=22:x=52:y=38,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='AASMA MUSIC':fontcolor={theme['bar']}@0.95:fontsize=20:x=w-215:y=39,"
        f"drawbox=x=32:y=698:w='1216*t/{duration}':h=6:color={theme['bar']}@0.95:t=fill,"
        f"format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-r", str(fps), "-i", bg_path,
        "-i", audio_path, "-i", ui_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4
    ]
    subprocess.run(cmd, check=True)
    print("Done:", out_mp4)

if __name__ == "__main__":
    main()
