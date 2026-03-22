import argparse
from pathlib import Path

import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def scan_media(data_dir: str, image_duration: int) -> list[dict]:
    files = sorted(
        f for f in Path(data_dir).rglob("*")
        if f.is_file() and f.suffix.lower() in MEDIA_EXTS
    )
    return [
        {"path": str(f), "duration": image_duration} if f.suffix.lower() in IMAGE_EXTS
        else {"path": str(f)}
        for f in files
    ]


def build_config(data_dir: str, title: str, image_duration: int,
                 width: int, height: int, fps: int, output: str) -> dict:
    return {
        "output": {"path": output, "width": width, "height": height, "fps": fps},
        "title": {
            "text": title,
            "duration": 3,
            "font_family": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "font_size": 72,
            "font_color": "white",
            "bg_color": "black",
        },
        "media": scan_media(data_dir, image_duration),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate config.yaml from media files")
    parser.add_argument("--data-dir", default="data", help="Directory containing media files")
    parser.add_argument("--title", default="My Video", help="Title slide text")
    parser.add_argument("--image-duration", type=int, default=7, help="Display seconds per image")
    parser.add_argument("--width", type=int, default=1920, help="Output video width")
    parser.add_argument("--height", type=int, default=1080, help="Output video height")
    parser.add_argument("--fps", type=int, default=30, help="Output video FPS")
    parser.add_argument("--output", default="output/result.mp4", help="Output video path")
    parser.add_argument("--config", default="output/config.yaml", help="Config file to write")
    args = parser.parse_args()

    cfg = build_config(args.data_dir, args.title, args.image_duration,
                       args.width, args.height, args.fps, args.output)

    Path(args.config).parent.mkdir(parents=True, exist_ok=True)
    with open(args.config, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    print(f"Created {args.config} with {len(cfg['media'])} media files")


if __name__ == "__main__":
    main()
