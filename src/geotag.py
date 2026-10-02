"""
Write the positions from locations.json into the photos' EXIF GPS tags.

Usage:
    python -m src.geotag --gpx training_gpx/run.gpx --photos photos/event --backup photos/event/_originals

The JPEG image data is not re-encoded: only the EXIF block is rewritten, other tags are kept.
"""

import argparse
import logging
import shutil
import sys
from fractions import Fraction
from pathlib import Path

import piexif

from src.gpx_track import read_gpx
from src.photos import LOCATIONS_FILE, read_locations, resolve_location

logger = logging.getLogger(__name__)


def _dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    value = abs(value)
    deg = int(value)
    minutes = int((value - deg) * 60)
    seconds = Fraction((value - deg - minutes / 60) * 3600).limit_denominator(10_000)
    return (deg, 1), (minutes, 1), (seconds.numerator, seconds.denominator)


def gps_ifd(lat: float, lon: float) -> dict:
    return {
        piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLongitudeRef: "E" if lon >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
    }


def geotag_file(path: Path, lat: float, lon: float) -> None:
    exif = piexif.load(str(path))
    exif["GPS"] = gps_ifd(lat, lon)
    piexif.insert(piexif.dump(exif), str(path))


def run(gpx: Path, photo_dir: Path, backup_dir: Path | None = None) -> list[Path]:
    """Geotag every JPEG listed in photo_dir/locations.json. Returns the tagged files."""
    _, points = read_gpx(gpx)
    entries = read_locations(photo_dir)
    if not entries:
        raise FileNotFoundError(f"No entries in {photo_dir / LOCATIONS_FILE}")

    tagged = []
    for name, entry in entries.items():
        path = photo_dir / name
        if path.suffix.lower() not in {".jpg", ".jpeg"}:
            logger.warning("%s: EXIF GPS can only be written to JPEG, skipped", name)
            continue
        if not path.is_file():
            logger.warning("%s: listed in %s but not found, skipped", name, LOCATIONS_FILE)
            continue
        lat, lon = resolve_location(entry, points)
        if backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / name
            if not backup.exists():  # never overwrite the first, untouched original
                shutil.copy2(path, backup)
        geotag_file(path, lat, lon)
        logger.info("%s: GPS set to %.6f, %.6f", name, lat, lon)
        tagged.append(path)
    return tagged


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--gpx", type=Path, required=True, help="Track the {km: ...} entries refer to"
    )
    parser.add_argument(
        "--photos", type=Path, required=True, help="Folder with photos + locations.json"
    )
    parser.add_argument("--backup", type=Path, help="Copy originals here before modifying them")
    args = parser.parse_args()
    try:
        run(args.gpx, args.photos, args.backup)
        return 0
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
