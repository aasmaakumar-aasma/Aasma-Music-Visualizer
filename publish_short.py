import os, sys, json, smtplib, subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader

def format_ass_time(seconds):
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def build_karaoke_text(text, duration_sec):
    words = text.split()
    if not words:
        return text
    total_cs = max(30, int(duration_sec * 100))
    total_chars = sum(len(w) for w in words) or 1
    return " ".join(f"{{\\kf{max(8, int(total_cs * (len(w) / total_chars)))}}}{w}" for w in words)

def make_9_16_bg(src_bg, out_bg):
    img = Image.open(src_bg).convert("RGB")
    target_ratio = 9 / 16
    cur_ratio = img.width / img.height
    if cur_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    img.resize((900, 1600), Image.LANCZOS).save(out_bg)

def make_short_mask(out_mask, width=640, height=110):
    mask = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(mask)
    for x in range(4, width - 4, 12):
        d.rectangle([x, 0, x + 3, height], fill=(255, 255, 255))
    mask.save(out_mask)

def write_short_ass(lyrics, start_sec, dur_sec, ass_path, glow):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PrevLine,Lato,26,&H90E2E8F0,&H90E2E8F0,&H90000000,&H00000000,0,0,0,0,100,100,0.4,0,1,1,0,5,50,50,40,1
Style: Active,Lato,46,&H00FFFFFF,&H68CBD5E1,{glow},&H55000000,-1,0,0,0,100,100,0.6,0,1,2.2,1,5,45,45,40,1
Style: NextLine,Lato,27,&H78E2E8F0,&H78E2E8F0,&H90000000,&H00000000,0,-1,0,0,100,100,0.4,0,1,1,0,5,50,50,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    sub = []
    for item in lyrics:
        st = float(item["start"]) - start_sec
        en = float(item["end"]) - start_sec
        if en <= 0.2 or st >= dur_sec:
            continue
        sub.append({"start": max(0.0, st), "end": min(dur_sec, en), "text": item["text"]})

    lines = [header]
    for i, item in enumerate(sub):
        st, en, txt = item["start"], item["end"], item["text"]
        if i > 0:
            lines.append(f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},PrevLine,,0,0,0,,{{\\pos(360,575)\\fad(220,220)}}{sub[i-1]['text']}\n")
        k_txt = build_karaoke_text(txt, en - st)
        lines.append(f"Dialogue: 1,{format_ass_time(st)},{format_ass_time(en)},Active,,0,0,0,,{{\\move(360,660,360,640,0,260)\\fad(200,200)\\blur1.5}}{k_txt}\n")
        if i + 1 < len(sub):
            lines.append(f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},NextLine,,0,0,0,,{{\\pos(360,710)\\fad(220,200)}}{sub[i+1]['text']}\n")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return sub

def main():
    meta_path = "/tmp/aasma_meta.json"
    if not os.path.exists(meta_path):
        print("Metadata not found, skipping short.")
        sys.exit(0)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    audio_path = meta["audio_path"]
    thumb_path = meta["thumb_path"]
    title = meta["title"]
    theme = meta["theme"]
    lyrics = meta["lyrics"]
    duration = float(meta["duration"])

    # Pick best <=58s hook window
    short_start = max(0.0, float(meta.get("short_start", min(20.0, duration * 0.25))))
    short_end = float(meta.get("short_end", short_start + 52.0))
    short_dur = min(58.0, max(25.0, short_end - short_start))
    if short_start + short_dur > duration:
        short_start = max(0.0, duration - short_dur)
        short_dur = min(58.0, duration - short_start)

    print(f"Rendering 9:16 Short ({short_start:.1f}s to {short_start+short_dur:.1f}s, {short_dur:.1f}s)...")
    bg_916 = "/tmp/short_bg.png"
    mask_916 = "/tmp/short_mask.png"
    ass_916 = "/tmp/short_lyrics.ass"
    short_mp4 = "/tmp/aasma_short.mp4"

    make_9_16_bg("/tmp/nature_bg.png", bg_916)
    make_short_mask(mask_916)
    short_lyrics = write_short_ass(lyrics, short_start, short_dur, ass_916, theme["glow"])

    fps = 25
    total_frames = max(1, int(short_dur * fps))
    safe_title = title.replace("'", "").replace(":", "")

    filter_complex = (
        f"[0:v]zoompan=z='max(1.0,1.16-0.16*(in/{total_frames}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=720x1280:fps={fps}[bg];"
        f"[2:v]format=rgba,scale=w='trunc(120*(1+0.13*abs(sin(t*3.2)))/2)*2':h=-1:eval=frame[em];"
        f"[bg][em]overlay=x='(W-w)/2':y='390-(h/2)':shortest=1[bg_em];"
        f"[1:a]showfreqs=s=120x110:mode=bar:ascale=sqrt:fscale=log:colors={theme['w1']}|{theme['w2']}:win_size=1024:averaging=3,"
        f"fps={fps},scale=640:110:flags=neighbor,format=rgb24[eq_raw];"
        f"[3:v]format=rgb24[mask_rgb];"
        f"[eq_raw][mask_rgb]blend=all_mode=multiply:shortest=1,colorkey=0x000000:0.06:0.06,format=rgba,split=2[eq_s][eq_g];"
        f"[eq_g]gblur=sigma=5[eq_glow];"
        f"[bg_em][eq_glow]overlay=40:1030:shortest=1[b1];"
        f"[b1][eq_s]overlay=40:1030:shortest=1,"
        f"ass={ass_916},"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='{safe_title}':fontcolor=white@0.92:fontsize=30:x=(w-tw)/2:y=95:shadowcolor=black@0.7:shadowx=2:shadowy=2,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='AASMA MUSIC':fontcolor={theme['accent']}@0.95:fontsize=22:x=(w-tw)/2:y=142:shadowcolor=black@0.7:shadowx=2:shadowy=2,"
        f"drawbox=x=40:y=1170:w=640:h=4:color=white@0.2:t=fill,"
        f"drawbox=x=40:y=1170:w='640*t/{short_dur}':h=4:color={theme['accent']}@0.95:t=fill,"
        f"format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-r", str(fps), "-i", bg_916,
        "-ss", str(short_start), "-t", str(short_dur), "-i", audio_path,
        "-loop", "1", "-r", str(fps), "-i", "/tmp/mood_emoji.png",
        "-loop", "1", "-r", str(fps), "-i", mask_916,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "192k", "-t", str(short_dur), short_mp4
    ]
    subprocess.run(cmd, check=True)

    print("Uploading Short & Thumbnail to Cloudinary...")
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True
    )
    vid_res = cloudinary.uploader.upload(short_mp4, resource_type="video", folder="aasma_shorts")
    img_res = cloudinary.uploader.upload(thumb_path, resource_type="image", folder="aasma_thumbs")
    vid_url = vid_res["secure_url"]
    img_url = img_res["secure_url"]
    print("Cloudinary Video URL:", vid_url)

    print("Publishing Short to Blogger via Mail-to-Blogger...")
    lyrics_html = "<br>".join(x["text"] for x in short_lyrics) if short_lyrics else "Listen & feel the vibe."
    html_body = f"""
    <div style="text-align:center; font-family:sans-serif; max-width:420px; margin:auto;">
      <video controls playsinline poster="{img_url}" style="width:100%; border-radius:14px; box-shadow:0 8px 24px rgba(0,0,0,0.35);">
        <source src="{vid_url}" type="video/mp4">
      </video>
      <h2 style="margin-top:16px;">{title} (Music Short)</h2>
      <p style="color:#666; font-size:14px;">Mood: {meta.get('mood','').title()} | Aasma Music</p>
      <div style="background:#111827; color:#f3f4f6; padding:16px; border-radius:12px; margin-top:14px; line-height:1.7; font-size:15px;">
        {lyrics_html}
      </div>
    </div>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{title} - Official Lyric Short | Aasma Music"
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["BLOGGER_EMAIL"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASS"])
        server.sendmail(os.environ["GMAIL_USER"], os.environ["BLOGGER_EMAIL"], msg.as_string())
    print("Published to Blogger successfully!")

if __name__ == "__main__":
    main()
