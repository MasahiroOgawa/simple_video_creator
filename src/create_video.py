import subprocess
import tempfile
from pathlib import Path

import pillow_heif
import yaml
from PIL import Image, ImageDraw, ImageFont

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}


def load_config(path: str = "output/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_image(path: str) -> Image.Image:
    if Path(path).suffix.lower() == ".heic":
        heif_file = pillow_heif.open_heif(path)
        return Image.frombytes(heif_file.mode, heif_file.size, heif_file.data)
    return Image.open(path).convert("RGB")


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
    cfg = load_config()
    w, h = cfg["output"]["width"], cfg["output"]["height"]
    fps = cfg["output"].get("fps", 30)
    out_path = cfg["output"]["path"]

    with tempfile.TemporaryDirectory() as tmpdir:
        segments = []

        # Title
        title_png = f"{tmpdir}/title.png"
        make_title_image(cfg, w, h).save(title_png)
        title_ts = f"{tmpdir}/seg_000.ts"
        image_to_ts(title_png, cfg["title"].get("duration", 3), fps, title_ts)
        segments.append(title_ts)
        print(f"  [title] done")

        # Media
        for i, item in enumerate(cfg["media"], 1):
            p = Path(item["path"])
            ext = p.suffix.lower()
            seg_ts = f"{tmpdir}/seg_{i:03d}.ts"

            if ext in IMAGE_EXTS:
                img_png = f"{tmpdir}/img_{i:03d}.png"
                fit_image(load_image(str(p)), w, h).save(img_png)
                image_to_ts(img_png, item["duration"], fps, seg_ts)
            elif ext in VIDEO_EXTS:
                video_to_ts(str(p), w, h, fps, seg_ts)
            else:
                raise ValueError(f"Unsupported: {ext}")

            segments.append(seg_ts)
            print(f"  [{i}/{len(cfg['media'])}] {p.name}")

        # Concatenate
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        ffmpeg(["-i", f"concat:{'|'.join(segments)}", "-c", "copy", out_path])

    print(f"Created {out_path}")


if __name__ == "__main__":
    main()
