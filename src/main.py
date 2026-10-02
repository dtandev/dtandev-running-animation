"""
Running animation generator
Builds one self-contained interactive HTML animation from a GPX track, a folder of photos,
an event logo and the event name. Everything else (stats, colours, photo pins) is automatic.

Usage:
    python src/main.py --gpx run.gpx --photos photos/ --logo logo.png --name "Event name"
    python src/main.py --help
"""

import argparse
import logging
import re
import sys
import unicodedata
from pathlib import Path

# Allow `python src/main.py` as well as `python -m src.main`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.animation import write_animation  # noqa: E402
from src.gpx_track import read_gpx  # noqa: E402
from src.photos import load_photos  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/output")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an interactive HTML animation of an activity from a GPX track",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Photos are placed on the track per photo, first match wins:
  1. locations.json in the photo folder (optional manual override),
  2. GPS tags in EXIF,
  3. capture time in EXIF matched against the track's timestamps,
  4. assumption: one photo every 10 minutes, in file-name order.

Example:
  python src/main.py --gpx training_gpx/run.gpx --photos photos/event \\
      --logo photos/event/logo.png --name "Mazurski Maraton Rolkowy"
        """,
    )
    parser.add_argument("--gpx", type=Path, required=True, help="GPX file with the track")
    parser.add_argument("--photos", type=Path, help="Folder with photos (JPEG/PNG)")
    parser.add_argument("--logo", type=Path, help="Event logo (PNG/SVG/JPEG)")
    parser.add_argument("--name", help="Event name (default: activity name from the GPX)")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}); file is named after the event",
    )
    parser.add_argument(
        "--photo-utc-offset",
        type=float,
        help="UTC offset (hours) of the camera clock, for photos matched by capture time "
        "(default: inferred from the activity)",
    )
    parser.add_argument(
        "--photo-max-distance",
        type=float,
        default=50.0,
        help="Max distance in metres between a GPS-tagged photo and the track (default: 50)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def slugify(text: str) -> str:
    # NFKD does not decompose the stroked letters, so map them by hand (otherwise "Półmaraton"
    # would lose its "ł").
    text = text.translate(
        str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})
    )
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "animation"


def run(
    gpx: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    photos_dir: Path | None = None,
    logo: Path | None = None,
    name: str | None = None,
    photo_max_distance_m: float = 50.0,
    photo_utc_offset_hours: float | None = None,
) -> Path:
    """Write the animation and return the path of the HTML file."""
    if not gpx.is_file():
        raise FileNotFoundError(f"GPX file not found: {gpx}")
    if logo is not None and not logo.is_file():
        raise FileNotFoundError(f"Logo file not found: {logo}")
    if photos_dir is not None and not photos_dir.is_dir():
        raise FileNotFoundError(f"Photo folder not found: {photos_dir}")

    gpx_name, points = read_gpx(gpx)
    title = name or gpx_name
    photos = []
    if photos_dir is not None:
        # the logo is often kept in the photo folder - it must not become a pin
        exclude = {logo} if logo is not None else set()
        photos = load_photos(
            photos_dir, points, photo_max_distance_m, photo_utc_offset_hours, exclude
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{slugify(title)}.html"
    write_animation(title, points, photos, out, logo)
    logger.info("Wrote %s (%d points, %d photos)", out, len(points), len(photos))
    return out


def main() -> int:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        run(
            args.gpx,
            args.output,
            args.photos,
            args.logo,
            args.name,
            args.photo_max_distance,
            args.photo_utc_offset,
        )
        logger.info("Done.")
        return 0
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
