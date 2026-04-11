import argparse
import subprocess
import tempfile
from pathlib import Path

import pillow_heif
import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}

XFADE_TRANSITIONS = [
    "fade", "fadeblack", "fadewhite", "fadegrays",
    "distance", "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circlecrop", "rectcrop", "circleclose", "circleopen",
    "horzclose", "horzopen", "vertclose", "vertopen",
    "diagbl", "diagbr", "diagtl", "diagtr",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "dissolve", "pixelize", "radial", "hblur",
    "wipetl", "wipetr", "wipebl", "wipebr",
    "squeezeh", "squeezev", "zoomin",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
]


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


def get_video_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _add_music(music_cfg: dict, cfg: dict, silent_path: str, out_path: str,
               total_dur: float, black_dur: float):
    """Overlay background music on a silent video."""
    music_start = music_cfg.get("start", 0)
    music_dur = total_dur - music_start
    last_dur = cfg["media"][-1].get("duration", 6) if cfg["media"] else 6
    fade_dur = last_dur / 2
    fade_start = music_dur - fade_dur - black_dur
    delay_ms = int(music_start * 1000)

    print(f"  [music] adding {music_cfg['path']} "
          f"(start={music_start}s, fade out at {fade_start:.1f}s, {fade_dur:.1f}s)")
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


def build_xfade_filter(seg_durs: list[float], transition: str, transition_dur: float) -> str:
    """Build ffmpeg xfade filter chain for N segments."""
    n = len(seg_durs)
    filters = []
    accumulated = seg_durs[0]
    for i in range(n - 1):
        offset = max(0, accumulated - transition_dur)
        src = f"[{i}:v]" if i == 0 else f"[v{i}]"
        dst = "[v]" if i == n - 2 else f"[v{i + 1}]"
        filters.append(
            f"{src}[{i + 1}:v]xfade=transition={transition}"
            f":duration={transition_dur}:offset={offset}{dst}"
        )
        accumulated = offset + seg_durs[i + 1]
    return ";".join(filters), accumulated


def main():
    parser = argparse.ArgumentParser(description="Create video from config")
    parser.add_argument("--config", default="output/config.yaml", help="Path to config YAML")
    args = parser.parse_args()
    cfg = load_config(args.config)
    w, h = cfg["output"]["width"], cfg["output"]["height"]
    fps = cfg["output"].get("fps", 30)
    out_path = cfg["output"]["path"]
    black_dur = cfg["output"].get("black_screen_duration", 3)

    # Transition config
    transition = cfg["output"].get("transition", "none")
    transition_dur = cfg["output"].get("transition_duration", 1)
    if transition != "none" and transition not in XFADE_TRANSITIONS:
        raise ValueError(
            f"Unsupported transition: {transition}. "
            f"Supported: {', '.join(XFADE_TRANSITIONS)}"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        segments = []   # (path, duration)
        seg_idx = 0

        # Black screen helper
        def add_black_screen():
            nonlocal seg_idx
            black_png = f"{tmpdir}/black.png"
            if not Path(black_png).exists():
                Image.new("RGB", (w, h), (0, 0, 0)).save(black_png)
            ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"
            image_to_ts(black_png, black_dur, fps, ts)
            segments.append((ts, black_dur))
            seg_idx += 1

        # Opening black screen
        if black_dur > 0:
            add_black_screen()
            print("  [black] opening")

        # Title
        title_png = f"{tmpdir}/title.png"
        make_title_image(cfg, w, h).save(title_png)
        title_ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"
        title_dur = cfg["title"].get("duration", 3)
        image_to_ts(title_png, title_dur, fps, title_ts)
        segments.append((title_ts, title_dur))
        seg_idx += 1
        print("  [title] done")

        # Media
        for i, item in enumerate(cfg["media"], 1):
            p = Path(item["path"])
            ext = p.suffix.lower()
            seg_ts = f"{tmpdir}/seg_{seg_idx:03d}.ts"

            if ext in IMAGE_EXTS:
                img_png = f"{tmpdir}/img_{i:03d}.png"
                fit_image(load_image(str(p)), w, h).save(img_png)
                dur = item["duration"]
                image_to_ts(img_png, dur, fps, seg_ts)
            elif ext in VIDEO_EXTS:
                video_to_ts(str(p), w, h, fps, seg_ts)
                dur = item.get("duration") or get_video_duration(seg_ts)
            else:
                raise ValueError(f"Unsupported: {ext}")

            segments.append((seg_ts, dur))
            seg_idx += 1
            print(f"  [{i}/{len(cfg['media'])}] {p.name}")

        # Closing black screen
        if black_dur > 0:
            add_black_screen()
            print("  [black] closing")

        # --- Concatenate ---
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        seg_paths = [s[0] for s in segments]
        seg_durs = [s[1] for s in segments]
        music_cfg = cfg.get("music")

        if transition == "none":
            # Fast concat (no re-encode)
            if not music_cfg:
                ffmpeg(["-i", f"concat:{'|'.join(seg_paths)}",
                        "-c", "copy", out_path])
            else:
                silent_path = f"{tmpdir}/silent.mp4"
                ffmpeg(["-i", f"concat:{'|'.join(seg_paths)}",
                        "-c", "copy", silent_path])
                total_dur = sum(seg_durs)
                _add_music(music_cfg, cfg, silent_path, out_path,
                           total_dur, black_dur)
        else:
            # xfade transition (re-encode)
            print(f"  [transition] {transition} ({transition_dur}s)")
            filter_str, total_dur = build_xfade_filter(
                seg_durs, transition, transition_dur,
            )
            inputs = [arg for p in seg_paths for arg in ("-i", p)]

            if not music_cfg:
                ffmpeg(inputs + [
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-c:v", "libx264", "-preset", "fast",
                    "-pix_fmt", "yuv420p", out_path,
                ])
            else:
                # Add music input as last input
                music_idx = len(seg_paths)
                inputs += ["-i", music_cfg["path"]]

                music_start = music_cfg.get("start", 0)
                music_dur = total_dur - music_start
                last_dur = (cfg["media"][-1].get("duration", 6)
                            if cfg["media"] else 6)
                fade_dur = last_dur / 2
                fade_start = music_dur - fade_dur - black_dur

                delay_ms = int(music_start * 1000)
                audio_filter = (
                    f"[{music_idx}:a]atrim=0:{music_dur},"
                    f"afade=t=out:st={fade_start}:d={fade_dur},"
                    f"adelay={delay_ms}|{delay_ms}[a]"
                )
                full_filter = f"{filter_str};{audio_filter}"

                print(f"  [music] adding {music_cfg['path']} "
                      f"(start={music_start}s, fade out at "
                      f"{fade_start:.1f}s, {fade_dur:.1f}s)")
                ffmpeg(inputs + [
                    "-filter_complex", full_filter,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", out_path,
                ])

    print(f"Created {out_path}")


if __name__ == "__main__":
    main()
