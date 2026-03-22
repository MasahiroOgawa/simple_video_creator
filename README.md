# Simple Video Creator

Create a video from a title slide followed by images and videos in sequence. Media is letterboxed to fit the output resolution while preserving aspect ratio.

## Setup

```bash
uv sync
```

## Usage

### 1. Generate config from media files

```bash
uv run python create_config.py --data-dir data/my_photos --title "My Video" --image-duration 5
```

Options:
- `--data-dir` — directory containing media files (default: `data`)
- `--title` — title slide text (default: `My Video`)
- `--image-duration` — seconds to display each image (default: `5`)
- `--width` / `--height` — output resolution (default: `1920x1080`)
- `--fps` — output FPS (default: `30`)
- `--output` — output video path (default: `output/result.mp4`)
- `--config` — config file to write (default: `output/config.yaml`)

### 2. Create the video

```bash
uv run python create_video.py
```

Output is saved to the path specified in `output/config.yaml`.

## Config format

```yaml
output:
  path: output/result.mp4
  width: 1920
  height: 1080
  fps: 30

title:
  text: "My Video"
  duration: 3
  font_family: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
  font_size: 72
  font_color: "white"
  bg_color: "black"

media:
  - path: data/photo1.jpg
    duration: 5
  - path: data/photo2.jpg
    duration: 4
  - path: data/clip.mp4
```

- Images require a `duration` (seconds)
- Videos play their full length (no `duration` needed)
- Supported images: jpg, jpeg, png, bmp, tiff, webp, heic
- Supported videos: mov, mp4, avi, mkv, webm
