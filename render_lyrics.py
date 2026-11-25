import os, sys, glob, json, math, random, subprocess
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from google import genai
from google.genai import types

THEMES = {
    "romantic": {
        "bg1": (16, 6, 28), "bg2": (52, 14, 48),
        "neb1": (236, 72, 153), "neb2": (139, 92, 246),
        "glow": "&H00B469FF", "wave1": "0xf472b6", "wave2": "0xc084fc",
        "accent": "0xf472b6", "tint": (244, 114, 182)
    },
    "sad": {
        "bg1": (5, 10, 24), "bg2": (14, 24, 52),
        "neb1": (56, 189, 248), "neb2": (99, 102, 241),
        "glow": "&H00F8BD38", "wave1": "0x38bdf8", "wave2": "0x818cf8",
        "accent": "0x38bdf8", "tint": (56, 189, 248)
    },
    "sufi": {
        "bg1": (12, 9, 22), "bg2": (38, 22, 42),
        "neb1": (245, 158, 11), "neb2": (139, 92, 246),
        "glow": "&H004BB6F5", "wave1": "0xfbbf24", "wave2": "0xa78bfa",
        "accent": "0xfbbf24", "tint": (245, 158, 11)
    },
    "energetic": {
        "bg1": (6, 12, 24), "bg2": (24, 10, 44),
        "neb1": (34, 211, 238), "neb2": (217, 70, 239),
        "glow": "&H00EED322", "wave1": "0x22d3ee", "wave2": "0xe879f9",
        "accent": "0x22d3ee", "tint": (34, 211, 238)
    },
    "lofi": {
        "bg1": (9, 11, 26), "bg2": (26, 18, 46),
        "neb1": (168, 85, 247), "neb2": (45, 212, 191),
        "glow": "&H00F755A8", "wave1": "0x2dd4bf", "wave2": "0xc084fc",
        "accent": "0x2dd4bf", "tint": (168, 85, 247)
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
        "Listen carefully to this entire song. "
        "1. Detect the primary mood from ONLY one of: romantic, sad, sufi, energetic, lofi. "
        "2. Transcribe ALL sung lyrics into natural Hinglish (Hindi written in clean Roman English script, e.g., 'Khamoshiyan bhi ab kuch kehti hain'). "
        "Break into short poetic lines (4 to 8 words max) with accurate start and end timestamps in seconds covering the whole song. "
        "Return ONLY valid JSON: {\"mood\": \"sad\", \"lyrics\": [{\"start\": 2.0, \"end\": 5.5, \"text\": \"...\"}]}"
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
    mood = str(data.get("mood", "lofi")).lower().strip()
    if mood not in THEMES:
        mood = "lofi"
    lyrics = data.get("lyrics", [])
    print(f"Mood: {mood} | Extracted {len(lyrics)} lyric lines.")
    for sample in lyrics[:3]:
        print("  Sample:", sample)
    return mood, lyrics

def generate_cinematic_bg(out_path, theme, photo_path=None, width=1600, height=900):
    # Smooth gradient + organic sinusoidal nebula clouds via numpy
    y_grid, x_grid = np.mgrid[0:height, 0:width].astype(np.float32)
    yn = y_grid / height
    xn = x_grid / width

    bg = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        bg[:, :, c] = theme["bg1"][c] * (1 - yn) + theme["bg2"][c] * yn

    # Organic nebula layers
    seed_off = random.uniform(0, 6.28)
    cloud1 = np.sin(xn * 4.5 + seed_off) * np.cos(yn * 3.8 - seed_off) + np.sin((xn + yn) * 6.0) * 0.5
    cloud1 = np.clip((cloud1 + 0.4) / 1.9, 0, 1) ** 2.2

    cloud2 = np.cos(xn * 5.2 - seed_off) * np.sin(yn * 4.2 + seed_off) + np.cos((xn - yn) * 5.5) * 0.5
    cloud2 = np.clip((cloud2 + 0.3) / 1.8, 0, 1) ** 2.4

    # Soft galaxy core glow in upper-center
    dist = np.sqrt(((xn - 0.52) * 1.4) ** 2 + ((yn - 0.38) * 1.6) ** 2)
    core = np.exp(-dist * 3.2)

    for c in range(3):
        bg[:, :, c] += cloud1 * theme["neb1"][c] * 0.42
        bg[:, :, c] += cloud2 * theme["neb2"][c] * 0.38
        bg[:, :, c] += core * (theme["neb1"][c] * 0.25 + 55)

    # Bottom atmospheric mist for visualizer depth
    mist = np.clip((yn - 0.65) / 0.35, 0, 1) ** 2
    for c in range(3):
        bg[:, :, c] = bg[:, :, c] * (1 - mist * 0.45) + theme["neb2"][c] * (mist * 0.14)

    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    # Optional custom portrait with auto-bg removal & natural sky blend
    if photo_path and os.path.exists(photo_path):
        try:
            from rembg import remove
            with open(photo_path, "rb") as f:
                cutout_bytes = remove(f.read())
            fg = Image.open(BytesIO(cutout_bytes)).convert("RGBA")
            target_h = int(height * 0.80)
            ratio = target_h / fg.height
            fg = fg.resize((int(fg.width * ratio), target_h), Image.LANCZOS)
            tint_layer = Image.new("RGBA", fg.size, (*theme["tint"], 65))
            fg = Image.alpha_composite(fg, tint_layer)
            r, g, b, a = fg.split()
            a_np = np.array(a, dtype=np.float32)
            # Soft bottom fade so subject melts into the mist
            fade = np.linspace(1.0, 0.0, fg.height).reshape(-1, 1)
            fade = np.clip(fade * 2.2, 0, 1)
            a_np = a_np * 0.34 * fade
            fg.putalpha(Image.fromarray(a_np.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)))
            pos = ((width - fg.width) // 2, height - fg.height + 15)
            img.alpha_composite(fg, dest=pos)
            print("Blended custom portrait:", photo_path)
        except Exception as e:
            print("Portrait blend skipped:", e)

    # Multi-scale glowing stars + subtle bokeh dust
    stars = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(360):
        x, y = random.randint(0, width - 1), random.randint(0, height - 1)
        rad = random.choices([1, 2, 3, 4], weights=[60, 28, 9, 3])[0]
        alpha = random.randint(70, 235)
        col = random.choice([(255, 255, 255, alpha), (210, 235, 255, alpha), (*theme["tint"], alpha)])
        sd.ellipse([x - rad, y - rad, x + rad, y + rad], fill=col)
    img = Image.alpha_composite(img, stars.filter(ImageFilter.GaussianBlur(3)))
    img = Image.alpha_composite(img, stars)

    # Cinematic dark vignette
    vx = (xn - 0.5) * 2
    vy = (yn - 0.5) * 2
    vig_mask = np.clip((vx ** 2 + vy ** 2) * 0.55, 0, 0.78)
    arr = np.array(img.convert("RGB"), dtype=np.float32)
    arr *= (1.0 - vig_mask[:, :, None])
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(out_path)

def write_spotify_ass(lyrics, ass_path, theme):
    glow = theme["glow"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,Lato,56,&H00FFFFFF,&H00FFFFFF,{glow},&H55000000,-1,0,0,0,100,100,0.8,0,1,2.2,1,5,80,80,40,1
Style: NextLine,Lato,32,&H68E2E8F0,&H68E2E8F0,&H80000000,&H00000000,0,-1,0,0,100,100,0.5,0,1,1,0,5,100,100,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    clean = [x for x in lyrics if str(x.get("text", "")).strip()]
    for i, item in enumerate(clean):
        st = float(item.get("start", 0))
        en = float(item.get("end", st + 3.5))
        if en <= st:
            en = st + 3.0
        txt = str(item["text"]).replace("\n", " ").strip()
        lines.append(
            f"Dialogue: 1,{format_ass_time(st)},{format_ass_time(en)},Active,,0,0,0,,"
            f"{{\\move(640,352,640,332,0,340)\\fad(300,300)\\blur2}}{txt}\n"
        )
        if i + 1 < len(clean):
            nxt = str(clean[i + 1]["text"]).replace("\n", " ").strip()
            lines.append(
                f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},NextLine,,0,0,0,,"
                f"{{\\pos(640,404)\\fad(320,260)}}{nxt}\n"
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

    bg_path = "/tmp/cosmic_bg.png"
    ass_path = "/tmp/lyrics.ass"

    print("2/4 Generating organic cosmic mood background...")
    generate_cinematic_bg(bg_path, theme, photo_path)

    print("3/4 Writing Spotify-style synced lyrics...")
    write_spotify_ass(lyrics, ass_path, theme)

    print("4/4 Rendering Cinematic Studio v3 MP4...")
    fps = 25
    total_frames = max(1, int(duration * fps))
    safe_title = title.replace("'", "").replace(":", "")

    filter_complex = (
        # Smooth cinematic zoom-out with gentle drift
        f"[0:v]zoompan=z='max(1.0,1.18-0.18*(in/{total_frames}))':"
        f"x='iw/2-(iw/zoom/2)+sin(in/45)*6':y='ih/2-(ih/zoom/2)+cos(in/55)*4':"
        f"d=1:s=1280x720:fps={fps}[bg];"
        # Dual-layer glowing mirror waveform (smooth & natural)
        f"[1:a]showwaves=s=1180x115:mode=cline:rate={fps}:colors={theme['wave1']}@0.9|{theme['wave2']}@0.75:scale=sqrt,format=rgba,split=2[w_sharp][w_glow_src];"
        f"[w_glow_src]gblur=sigma=7[w_glow];"
        f"[bg][w_glow]overlay=50:555:shortest=1[bg1];"
        f"[bg1][w_sharp]overlay=50:555:shortest=1,"
        # Synced Spotify-style lyrics
        f"ass={ass_path},"
        # Clean, minimal top-corner titles (no broken icons or heavy boxes)
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='{safe_title}':fontcolor=white@0.88:fontsize=24:x=44:y=34:shadowcolor=black@0.6:shadowx=2:shadowy=2,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='AASMA MUSIC':fontcolor={theme['accent']}@0.92:fontsize=22:x=w-tw-44:y=35:shadowcolor=black@0.6:shadowx=2:shadowy=2,"
        # Sleek glowing progress bar at bottom
        f"drawbox=x=50:y=694:w=1180:h=3:color=white@0.18:t=fill,"
        f"drawbox=x=50:y=694:w='1180*t/{duration}':h=3:color={theme['accent']}@0.95:t=fill,"
        f"format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-r", str(fps), "-i", bg_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4
    ]
    subprocess.run(cmd, check=True)
    print("Done:", out_mp4)

if __name__ == "__main__":
    main()
