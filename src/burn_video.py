import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import yaml

DVD_MAX_BYTES = 4_700_000_000
DVD_VIDEO_BITRATE = 6_000_000  # 6 Mbps (video + overhead)
DVD_SONG_BITRATE = 400_000     # black frame + ac3 audio


def load_config(path: str = "output/config_burning.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_dvd_resolution(fmt: str) -> tuple[int, int, float]:
    return (720, 480, 29.97) if fmt == "ntsc" else (720, 576, 25.0)


def ffmpeg(args: list[str]):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                   check=True)


def ffprobe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def has_audio_stream(path: str) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def estimate_disc_size(videos: list[dict], songs: list[dict]) -> tuple[int, float]:
    """Estimate total bytes and duration. Returns (total_bytes, total_seconds)."""
    total_bytes = 0
    total_seconds = 0.0
    for v in videos:
        dur = ffprobe_duration(v["path"])
        v["_duration"] = dur
        total_bytes += int(dur * DVD_VIDEO_BITRATE / 8)
        total_seconds += dur
    for s in songs:
        dur = ffprobe_duration(s["path"])
        s["_duration"] = dur
        total_bytes += int(dur * DVD_SONG_BITRATE / 8)
        total_seconds += dur
    return total_bytes, total_seconds


def convert_video_to_vob(src: str, dst: str, w: int, h: int, fps: float,
                         fmt: str):
    target = f"{fmt}-dvd"
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
    if has_audio_stream(src):
        ffmpeg(["-i", src,
                "-target", target,
                "-vf", vf, "-aspect", "16:9",
                "-c:a", "ac3", "-b:a", "192k",
                dst])
    else:
        # Add silent audio so all VOBs have consistent streams in the titleset
        ffmpeg(["-i", src,
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-target", target,
                "-vf", vf, "-aspect", "16:9",
                "-map", "0:v", "-map", "1:a",
                "-c:a", "ac3", "-b:a", "192k",
                "-shortest",
                dst])


def convert_song_to_vob(src: str, dst: str, w: int, h: int, fps: float,
                        duration: float, fmt: str):
    target = f"{fmt}-dvd"
    ffmpeg(["-f", "lavfi",
            "-i", f"color=black:s={w}x{h}:r={fps}:d={duration}",
            "-i", src,
            "-target", target,
            "-c:a", "ac3", "-b:a", "192k",
            "-shortest",
            dst])


def author_dvd(vob_files: list[str], dvd_dir: str, fmt: str):
    """Create DVD-Video structure using dvdauthor.

    All VOBs go into a single titleset with one PGC per VOB.
    Each PGC chains to the next via <post>jump next pgc;</post>
    so the DVD player auto-advances through all titles.
    """
    if Path(dvd_dir).exists():
        shutil.rmtree(dvd_dir)
    Path(dvd_dir).mkdir(parents=True)

    pgcs = []
    for i, vob in enumerate(vob_files):
        post = "jump next pgc;" if i < len(vob_files) - 1 else ""
        pgcs.append(
            f'      <pgc>\n'
            f'        <vob file="{vob}" />\n'
            f'        <post>{post}</post>\n'
            f'      </pgc>'
        )
    pgcs_str = "\n".join(pgcs)
    xml_content = (
        f'<dvdauthor dest="{dvd_dir}">\n'
        f'  <vmgm>\n'
        f'    <fpc>jump title 1;</fpc>\n'
        f'  </vmgm>\n'
        f'  <titleset>\n'
        f'    <titles>\n'
        f'{pgcs_str}\n'
        f'    </titles>\n'
        f'  </titleset>\n'
        f'</dvdauthor>'
    )

    xml_path = Path(dvd_dir).parent / "dvdauthor.xml"
    xml_path.write_text(xml_content)

    env = os.environ.copy()
    env["VIDEO_FORMAT"] = fmt.upper()
    subprocess.run(["dvdauthor", "-x", str(xml_path)], check=True, env=env)
    print(f"  DVD structure created at {dvd_dir}")


def blank_disc(device: str):
    print(f"  Blanking DVD-RW at {device}...")
    subprocess.run(["dvd+rw-format", "-blank", device], check=True)
    print("  Blanking complete")


def burn_dvd(dvd_dir: str, device: str, label: str):
    print(f"  Burning to {device}...")
    subprocess.run([
        "growisofs", "-dvd-compat", "-Z", device,
        "-dvd-video", "-V", label, dvd_dir,
    ], check=True)
    print("  Burning complete")


def generate_contents(cfg: dict, out_path: str):
    dvd = cfg["dvd"]
    w, h, _ = get_dvd_resolution(dvd["format"])
    lines = [
        "=" * 48,
        f"DVD Contents: {dvd['disc_label']}",
        f"Format: {dvd['format'].upper()} ({w}x{h})",
        f"Date: {date.today()}",
        "=" * 48,
        "",
    ]

    idx = 1
    if cfg.get("videos"):
        lines.append("--- Videos ---")
        for v in cfg["videos"]:
            dur = format_duration(v.get("_duration", 0))
            lines.append(f" {idx:2d}. {v['title']:<40s} ({dur})")
            idx += 1
        lines.append("")

    if cfg.get("songs"):
        lines.append("--- Songs ---")
        for s in cfg["songs"]:
            dur = format_duration(s.get("_duration", 0))
            lines.append(f" {idx:2d}. {s['title']:<40s} ({dur})")
            idx += 1
        lines.append("")

    lines.extend([
        f"Total titles: {idx - 1}",
        "=" * 48,
        "",
    ])

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"  Contents file: {out_path}")


def play_dvd(device: str):
    print(f"  Playing DVD at {device} for verification...")
    try:
        subprocess.Popen(["vlc", f"dvd://{device}"])
    except FileNotFoundError:
        print("  Warning: vlc not found, skipping auto-play")


def main():
    parser = argparse.ArgumentParser(description="Burn videos to DVD")
    parser.add_argument("--config", default="output/config_burning.yaml",
                        help="Path to burn config YAML")
    parser.add_argument("--dry-run", action="store_true",
                        help="Convert and author only, skip actual burning")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dvd = cfg["dvd"]
    fmt = dvd["format"]
    device = dvd["device"]
    dvd_dir = cfg["output"]["dvd_dir"]
    contents_file = cfg["output"]["contents_file"]
    w, h, fps = get_dvd_resolution(fmt)

    videos = cfg.get("videos", [])
    songs = cfg.get("songs", [])

    if not videos and not songs:
        print("Error: no videos or songs in config")
        return

    # Validate source files exist
    for item in videos + songs:
        if not Path(item["path"]).exists():
            print(f"Error: file not found: {item['path']}")
            return

    # Check device (skip for dry-run)
    if not args.dry_run and not Path(device).exists():
        print(f"Error: DVD device not found: {device}")
        return

    # Estimate disc size
    print("Estimating disc size...")
    total_bytes, total_seconds = estimate_disc_size(videos, songs)
    print(f"  Estimated size: {total_bytes / 1e9:.2f} GB / 4.70 GB")
    print(f"  Total duration: {format_duration(total_seconds)}")
    if total_bytes > DVD_MAX_BYTES:
        print("Error: content exceeds DVD capacity (4.7 GB)")
        return

    # Convert to VOB
    with tempfile.TemporaryDirectory() as tmpdir:
        vob_files = []
        print("Converting videos...")
        for i, v in enumerate(videos, 1):
            vob = f"{tmpdir}/video_{i:03d}.vob"
            print(f"  [{i}/{len(videos)}] {Path(v['path']).name}")
            convert_video_to_vob(v["path"], vob, w, h, fps, fmt)
            vob_files.append(vob)

        print("Converting songs...")
        for i, s in enumerate(songs, 1):
            vob = f"{tmpdir}/song_{i:03d}.vob"
            print(f"  [{i}/{len(songs)}] {Path(s['path']).name}")
            convert_song_to_vob(s["path"], vob, w, h, fps, s["_duration"], fmt)
            vob_files.append(vob)

        # Author DVD structure
        print("Authoring DVD structure...")
        author_dvd(vob_files, dvd_dir, fmt)

    # Generate contents file
    generate_contents(cfg, contents_file)

    if args.dry_run:
        print("Dry run complete. DVD structure ready at: " + dvd_dir)
        return

    # Blank disc if requested
    if dvd.get("blank_disc"):
        blank_disc(device)

    # Burn
    burn_dvd(dvd_dir, device, dvd["disc_label"])

    # Auto-play for verification
    play_dvd(device)
    print("Done! Check playback to verify the burn.")


if __name__ == "__main__":
    main()
