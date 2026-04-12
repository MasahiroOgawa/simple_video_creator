import argparse
from pathlib import Path

import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}
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
                 width: int, height: int, fps: int, output: str,
                 black_screen_duration: int = 3) -> dict:
    return {
        "output": {"path": output, "width": width, "height": height, "fps": fps,
                   "black_screen_duration": black_screen_duration},
        "title": {
            "text": title,
            "duration": 6,
            "font_family": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "font_size": 72,
            "font_color": "white",
            "bg_color": "black",
        },
        "media": scan_media(data_dir, image_duration),
    }


def _title_from_filename(path: str) -> str:
    return Path(path).stem.replace("_", " ")


def scan_videos_and_songs(data_dir: str) -> tuple[list[dict], list[dict]]:
    root = Path(data_dir)
    videos = [
        {"path": str(f), "title": _title_from_filename(f)}
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS
    ]
    songs = [
        {"path": str(f), "title": _title_from_filename(f)}
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS
    ]
    return videos, songs


def build_burn_config(data_dir: str, device: str = "/dev/sr0",
                      fmt: str = "ntsc", disc_label: str = "MY_DVD") -> dict:
    videos, songs = scan_videos_and_songs(data_dir)
    return {
        "dvd": {
            "device": device,
            "format": fmt,
            "disc_label": disc_label,
            "blank_disc": False,
        },
        "videos": videos,
        "songs": songs,
        "output": {
            "dvd_dir": "output/dvd_structure",
            "contents_file": "output/dvd_contents.txt",
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Generate config.yaml from media files")
    parser.add_argument("--data-dir", default="data", help="Directory containing media files")
    parser.add_argument("--title", default="My Video", help="Title slide text")
    parser.add_argument("--image-duration", type=int, default=6, help="Display seconds per image")
    parser.add_argument("--width", type=int, default=1920, help="Output video width")
    parser.add_argument("--height", type=int, default=1080, help="Output video height")
    parser.add_argument("--fps", type=int, default=30, help="Output video FPS")
    parser.add_argument("--output", default="output/result.mp4", help="Output video path")
    parser.add_argument("--black-screen-duration", type=int, default=3, help="Black screen seconds before/after video (0 to disable)")
    parser.add_argument("--config", default=None, help="Config file to write")
    parser.add_argument("-b", "--burn", action="store_true",
                        help="Generate DVD burn config instead of video creation config")
    parser.add_argument("--device", default="/dev/sr0", help="DVD device path")
    parser.add_argument("--dvd-format", choices=["ntsc", "pal"], default="ntsc",
                        help="DVD video format")
    parser.add_argument("--disc-label", default="MY_DVD", help="DVD disc label")
    args = parser.parse_args()

    if args.burn:
        config_path = args.config or "output/config_burning.yaml"
        cfg = build_burn_config(args.data_dir, args.device, args.dvd_format,
                                args.disc_label)
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)
        print(f"Created {config_path} with {len(cfg['videos'])} videos and {len(cfg['songs'])} songs")
    else:
        config_path = args.config or "output/config.yaml"
        cfg = build_config(args.data_dir, args.title, args.image_duration,
                           args.width, args.height, args.fps, args.output,
                           args.black_screen_duration)
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        print(f"Created {config_path} with {len(cfg['media'])} media files")


if __name__ == "__main__":
    main()
