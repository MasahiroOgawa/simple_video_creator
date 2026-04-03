import argparse
import subprocess
import tempfile
from pathlib import Path

import pillow_heif
import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}


def load_config(path: str = "output/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_image(path: str) -> Image.Image:
    if Path(path).suffix.lower() == ".heic":
        heif_file = pillow_heif.open_heif(path)
        return Image.frombytes(heif_file.mode, heif_file.size, heif_file.data)
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def fit_image(img: Image.Image, w: int, h: int, bg=(0, 0, 0)) -> Image.Image:
    """Letterbox image to target resolution."""
    scale = min(w / img.width, h / img.height)
    new_w, new_h = int(img.width * scale), int(img.height * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), bg)
    canvas.paste(resized, ((w - new_w) // 2, (h - new_h) // 2))
    return canvas


def make_title_image(cfg: dict, w: int, h: int) -> Image.Image:
    t = cfg["title"]
    canvas = Image.new("RGB", (w, h), t.get("bg_color", "black"))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(t.get("font_family", ""), t.get("font_size", 72))
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), t["text"], font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) // 2, (h - th) // 2), t["text"],
              fill=t.get("font_color", "white"), font=font)
    return canvas


def ffmpeg(args: list[str]):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                   check=True)


def image_to_ts(png_path: str, duration: float, fps: int, out: str):
    ffmpeg(["-loop", "1", "-t", str(duration), "-i", png_path,
            "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-r", str(fps), "-f", "mpegts", out])


def video_to_ts(video_path: str, w: int, h: int, fps: int, out: str):
    ffmpeg(["-i", video_path,
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-r", str(fps), "-an", "-f", "mpegts", out])


def main():
    parser = argparse.ArgumentParser(description="Create video from config")
    parser.add_argument("--config", default="output/config.yaml", help="Path to config YAML")
    args = parser.parse_args()
    cfg = load_config(args.config)
    w, h = cfg["output"]["width"], cfg["output"]["height"]
    fps = cfg["output"].get("fps", 30)
    out_path = cfg["output"]["path"]

    black_dur = cfg["output"].get("black_screen_duration", 3)

    with tempfile.TemporaryDirectory() as tmpdir:
        segments = []
        seg_idx = 0

        # Black screen helper
        def add_black_screen():
            nonlocal seg_idx
            black_png = f"{tmpdir}/black.png"
            if not Path(black_png).exists():
                Image.new("RGB", (w, h), (0, 0, 0)).save(black_png)
            ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"
            image_to_ts(black_png, black_dur, fps, ts)
            segments.append(ts)
            seg_idx += 1

        # Opening black screen
        if black_dur > 0:
            add_black_screen()
            print("  [black] opening")

        # Title
        title_png = f"{tmpdir}/title.png"
        make_title_image(cfg, w, h).save(title_png)
        title_ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"
        image_to_ts(title_png, cfg["title"].get("duration", 3), fps, title_ts)
        segments.append(title_ts)
        seg_idx += 1
        print(f"  [title] done")

        # Media
        for i, item in enumerate(cfg["media"], 1):
            p = Path(item["path"])
            ext = p.suffix.lower()
            seg_ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"

            if ext in IMAGE_EXTS:
                img_png = f"{tmpdir}/img_{i:03d}.png"
                fit_image(load_image(str(p)), w, h).save(img_png)
                image_to_ts(img_png, item["duration"], fps, seg_ts)
            elif ext in VIDEO_EXTS:
                video_to_ts(str(p), w, h, fps, seg_ts)
            else:
                raise ValueError(f"Unsupported: {ext}")

            segments.append(seg_ts)
            seg_idx += 1
            print(f"  [{i}/{len(cfg['media'])}] {p.name}")

        # Closing black screen
        if black_dur > 0:
            add_black_screen()
            print("  [black] closing")

        # Concatenate video segments (silent)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        music_cfg = cfg.get("music")
        if not music_cfg:
            ffmpeg(["-i", f"concat:{'|'.join(segments)}", "-c", "copy", out_path])
        else:
            silent_path = f"{tmpdir}/silent.mp4"
            ffmpeg(["-i", f"concat:{'|'.join(segments)}", "-c", "copy", silent_path])

            # Calculate total video duration
            total_dur = black_dur  # opening black
            total_dur += cfg["title"].get("duration", 3)
            for item in cfg["media"]:
                total_dur += item.get("duration", 6)
            total_dur += black_dur  # closing black

            # Music start time and play duration
            music_start = music_cfg.get("start", 0)
            music_dur = total_dur - music_start

            # Fade out over the last half of final media duration
            last_dur = cfg["media"][-1].get("duration", 6) if cfg["media"] else 6
            fade_dur = last_dur / 2
            fade_start = music_dur - fade_dur - black_dur  # end fade before closing black

            delay_ms = int(music_start * 1000)

            print(f"  [music] adding {music_cfg['path']} (start={music_start}s, fade out at {fade_start:.1f}s, {fade_dur:.1f}s)")
            ffmpeg([
                "-i", silent_path,
                "-i", music_cfg["path"],
                "-filter_complex",
                f"[1:a]atrim=0:{music_dur},afade=t=out:st={fade_start}:d={fade_dur},"
                f"adelay={delay_ms}|{delay_ms}[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", out_path,
            ])

    print(f"Created {out_path}")


if __name__ == "__main__":
    main()
