import os, sys, json, random, subprocess
from PIL import Image, ImageDraw, ImageFilter
from google import genai
from google.genai import types

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

def generate_universe_bg(out_path, width=1440, height=810):
    img = Image.new("RGB", (width, height), (5, 7, 20))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(6 + (y / height) * 18)
        g = int(8 + (y / height) * 10)
        b = int(28 + (y / height) * 35)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    nebula = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ndraw = ImageDraw.Draw(nebula)
    ndraw.ellipse([150, 80, 900, 620], fill=(88, 28, 135, 55))
    ndraw.ellipse([600, 220, 1350, 760], fill=(14, 116, 144, 50))
    nebula = nebula.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), nebula).convert("RGB")

    sdraw = ImageDraw.Draw(img)
    random.seed(42)
    for _ in range(260):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        r = random.choice([1, 1, 1, 2, 2, 3])
        c = random.choice([(255, 255, 255), (186, 230, 253), (233, 213, 255), (254, 240, 138)])
        sdraw.ellipse([x - r, y - r, x + r, y + r], fill=c)

    img.save(out_path)

def extract_hinglish_lyrics(audio_path):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    audio_file = client.files.upload(file=audio_path)
    prompt = (
        "Listen carefully to this song and transcribe all sung lyrics into natural Hinglish "
        "(Hindi written in English/Roman script, e.g., 'Sukoon ki talash mein'). "
        "Break it into short, clean phrases (one line at a time, 4-8 words max per line) "
        "with accurate start and end timestamps in seconds. "
        "Return ONLY a JSON array of objects with keys: 'start' (number), 'end' (number), 'text' (string)."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_file, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)

def write_ass_file(lyrics, ass_path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,52,&H00FFFFFF,&H0000FFFF,&H00401030,&H80000000,-1,0,0,0,100,100,1,0,1,3,2,5,80,80,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for item in lyrics:
        start = format_ass_time(item.get("start", 0))
        end = format_ass_time(item.get("end", 0))
        txt = str(item.get("text", "")).replace("\n", " ").strip()
        if txt:
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\fad(350,350)}}{txt}\n")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def main():
    audio_path = sys.argv[1]
    out_mp4 = sys.argv[2]
    title = os.path.splitext(os.path.basename(audio_path))[0].replace("_", " ").title()

    duration = get_audio_duration(audio_path)
    bg_path = "/tmp/universe_bg.png"
    ass_path = "/tmp/lyrics.ass"

    print("1/3 Generating Universe background...")
    generate_universe_bg(bg_path)

    print("2/3 Extracting Hinglish synced lyrics with Gemini...")
    lyrics = extract_hinglish_lyrics(audio_path)
    write_ass_file(lyrics, ass_path)

    print("3/3 Rendering final video with FFmpeg...")
    filter_complex = (
        f"[0:v]crop=1280:720:x='(iw-1280)/2+40*sin(t/6)':y='(ih-720)/2+25*cos(t/8)',"
        f"ass={ass_path},"
        f"drawtext=text='{title}':fontcolor=white@0.85:fontsize=26:x=36:y=28,"
        f"drawtext=text='Aasma Music':fontcolor=00e5ff@0.85:fontsize=24:x=w-tw-36:y=28,"
        f"drawbox=x=0:y=714:w='iw*t/{duration}':h=6:color=00e5ff@0.9:t=fill[bg];"
        f"[1:a]showwaves=s=1280x130:mode=cline:colors=00e5ff|c084fc:rate=30,format=rgba[wave];"
        f"[bg][wave]overlay=0:575:shortest=1,format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", bg_path, "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4
    ]
    subprocess.run(cmd, check=True)
    print("Done:", out_mp4)

if __name__ == "__main__":
    main()
