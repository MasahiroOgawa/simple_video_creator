from pathlib import Path

import yaml
from moviepy import (
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fit_clip(clip, target_w: int, target_h: int):
    scale = min(target_w / clip.w, target_h / clip.h)
    resized = clip.resized((int(clip.w * scale), int(clip.h * scale)))
    return CompositeVideoClip(
        [resized.with_position("center")],
        size=(target_w, target_h),
        bg_color=(0, 0, 0),
    )


def make_title_clip(cfg: dict, w: int, h: int):
    t = cfg["title"]
    txt = TextClip(
        text=t["text"],
        font=t.get("font_family", "Arial"),
        font_size=t.get("font_size", 72),
        color=t.get("font_color", "white"),
        size=(w, h),
        method="caption",
        text_align="center",
        vertical_align="center",
        bg_color=t.get("bg_color", "black"),
    )
    return txt.with_duration(t.get("duration", 3))


def make_media_clip(item: dict, w: int, h: int):
    p = Path(item["path"])
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        clip = ImageClip(str(p)).with_duration(item["duration"])
    elif ext in VIDEO_EXTS:
        clip = VideoFileClip(str(p))
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    return fit_clip(clip, w, h)


def main():
    cfg = load_config()
    w, h = cfg["output"]["width"], cfg["output"]["height"]
    fps = cfg["output"].get("fps", 30)

    clips = [make_title_clip(cfg, w, h)] + [
        make_media_clip(item, w, h) for item in cfg["media"]
    ]

    final = concatenate_videoclips(clips, method="compose")
    Path(cfg["output"]["path"]).parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(cfg["output"]["path"], fps=fps, codec="libx264", audio_codec="aac")


if __name__ == "__main__":
    main()
