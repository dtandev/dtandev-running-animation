"""Photos: finding where on the track each one belongs, and preparing it for the page.

Position of a photo is decided per photo, first match wins:
  1. locations.json entry in the photo folder (manual override),
  2. GPS tags in EXIF,
  3. capture time in EXIF, matched against the track's timestamps,
  4. assumption: photos were taken ASSUMED_INTERVAL_MIN minutes apart, in file-name order.
"""

import base64
import bisect
import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

from src.gpx_track import TrackPoint, haversine_m

logger = logging.getLogger(__name__)

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
THUMB_PX = 96
FULL_PX = 1280
ASSUMED_INTERVAL_MIN = 10
# Camera clocks drift; accept capture times this far outside the activity window.
TIME_MARGIN_S = 5 * 60

_EXIF_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIGINAL = 36867
_TAG_OFFSET_TIME_ORIGINAL = 36880

# Optional file in the photo folder. Each entry is either [lat, lon] or {"km": distance along
# the track}; it overrides everything else. Keys starting with "_" are ignored (comments).
LOCATIONS_FILE = "locations.json"

SOURCE_MANUAL = "manual"
SOURCE_GPS = "gps"
SOURCE_TIME = "time"
SOURCE_ASSUMED = "assumed"


@dataclass
class Photo:
    name: str
    lat: float
    lon: float
    track_index: int  # index of the nearest track point
    thumb_b64: str
    full_b64: str
    source: str  # one of SOURCE_*


@dataclass
class _Candidate:
    name: str
    thumb_b64: str
    full_b64: str
    gps: tuple[float, float] | None = None
    manual: bool = False
    taken: datetime | None = None  # naive local time as written by the camera
    taken_offset: timedelta | None = None  # from OffsetTimeOriginal when present


# ---------------------------------------------------------------- EXIF helpers


def _dms_to_deg(dms, ref: str) -> float:
    deg = float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0
    return -deg if ref in ("S", "W") else deg


def read_gps(img: Image.Image) -> tuple[float, float] | None:
    gps = img.getexif().get_ifd(_EXIF_GPS_IFD)
    # GPS tags: 1 LatRef, 2 Lat, 3 LonRef, 4 Lon
    if not gps or 2 not in gps or 4 not in gps:
        return None
    try:
        return (
            _dms_to_deg(gps[2], gps.get(1, "N")),
            _dms_to_deg(gps[4], gps.get(3, "E")),
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def read_capture_time(img: Image.Image) -> tuple[datetime | None, timedelta | None]:
    """Capture time as written by the camera (naive) and its UTC offset, if recorded."""
    exif_ifd = img.getexif().get_ifd(_EXIF_IFD)
    raw = exif_ifd.get(_TAG_DATETIME_ORIGINAL)
    if not raw:
        return None, None
    try:
        taken = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None
    offset = None
    off_raw = exif_ifd.get(_TAG_OFFSET_TIME_ORIGINAL)
    if off_raw:
        try:
            sign = -1 if str(off_raw).startswith("-") else 1
            hh, mm = str(off_raw).lstrip("+-").split(":")
            offset = sign * timedelta(hours=int(hh), minutes=int(mm))
        except ValueError:
            offset = None
    return taken, offset


# --------------------------------------------------------- locations.json (manual)


def read_locations(photo_dir: Path) -> dict[str, list | dict]:
    path = photo_dir / LOCATIONS_FILE
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_location(entry: list | dict, points: list[TrackPoint]) -> tuple[float, float]:
    """Turn a locations.json entry into (lat, lon)."""
    if isinstance(entry, dict):
        target_m = float(entry["km"]) * 1000.0
        # first point at or past the requested distance; clamp to the end of the track
        point = next((p for p in points if p.dist_m >= target_m), points[-1])
        return point.lat, point.lon
    lat, lon = entry
    return float(lat), float(lon)


# --------------------------------------------------------------- image encoding


def _jpeg_b64(img: Image.Image, max_px: int, quality: int) -> str:
    img = img.copy()
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _square_thumb_b64(img: Image.Image) -> str:
    thumb = ImageOps.fit(img, (THUMB_PX, THUMB_PX))
    buf = io.BytesIO()
    thumb.convert("RGB").save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ------------------------------------------------------------------- matching


def nearest_point(points: list[TrackPoint], lat: float, lon: float) -> tuple[int, float]:
    """Index of the closest track point and its distance in metres."""
    best_i, best_d = 0, float("inf")
    for i, p in enumerate(points):
        d = haversine_m(p.lat, p.lon, lat, lon)
        if d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def index_at_elapsed(points: list[TrackPoint], elapsed_s: float) -> int:
    """Index of the last track point at or before elapsed_s (clamped to the track)."""
    times = [p.elapsed_s for p in points]
    return max(0, min(len(points) - 1, bisect.bisect_right(times, elapsed_s) - 1))


def _to_utc(taken: datetime, offset: timedelta) -> datetime:
    return taken.replace(tzinfo=timezone(offset)).astimezone(UTC)


def infer_utc_offset(
    takens: list[datetime], points: list[TrackPoint], hint_lon: float
) -> timedelta | None:
    """Pick the whole/half-hour UTC offset that puts most capture times inside the activity.

    Ties go to the offset closest to the solar time zone of the track (lon / 15).
    Returns None when no offset puts any photo inside the activity window.
    """
    margin = timedelta(seconds=TIME_MARGIN_S)
    start, end = points[0].time - margin, points[-1].time + margin
    solar = round(hint_lon / 15.0)
    best: tuple[int, float, float] | None = None  # (-hits, distance to solar, offset)
    for half_hours in range(-24, 29):
        off = half_hours / 2
        hits = sum(start <= _to_utc(t, timedelta(hours=off)) <= end for t in takens)
        if hits == 0:
            continue
        key = (-hits, abs(off - solar), off)
        if best is None or key < best:
            best = key
    return None if best is None else timedelta(hours=best[2])


def _choose_offset(
    cands: list[_Candidate], points: list[TrackPoint], utc_offset_hours: float | None
) -> timedelta | None:
    if utc_offset_hours is not None:
        return timedelta(hours=utc_offset_hours)
    # photos that carry their own OffsetTimeOriginal do not need the inferred one
    needing = [c.taken for c in cands if c.taken_offset is None]
    if not needing:
        return timedelta(0)
    mean_lon = sum(p.lon for p in points) / len(points)
    offset = infer_utc_offset(needing, points, mean_lon)
    if offset is not None:
        logger.warning(
            "Photo capture times carry no time zone: assuming UTC%+.1f (best fit to the "
            "activity). Override with --photo-utc-offset if the pins look wrong.",
            offset.total_seconds() / 3600,
        )
    return offset


def _on_track(c: _Candidate, points: list[TrackPoint], idx: int, source: str) -> Photo:
    p = points[idx]
    return Photo(c.name, p.lat, p.lon, idx, c.thumb_b64, c.full_b64, source)


def _read_candidates(
    photo_dir: Path, points: list[TrackPoint], exclude: set[Path]
) -> list[_Candidate]:
    manual = read_locations(photo_dir)
    candidates: list[_Candidate] = []
    for path in sorted(photo_dir.iterdir()):
        if path.suffix.lower() not in PHOTO_SUFFIXES or path.resolve() in exclude:
            continue
        try:
            with Image.open(path) as raw:
                oriented = ImageOps.exif_transpose(raw)
                cand = _Candidate(
                    path.name, _square_thumb_b64(oriented), _jpeg_b64(oriented, FULL_PX, 82)
                )
                if path.name in manual:
                    cand.gps = resolve_location(manual[path.name], points)
                    cand.manual = True
                else:
                    cand.gps = read_gps(raw)
                cand.taken, cand.taken_offset = read_capture_time(raw)
        except OSError as e:
            logger.warning("%s: cannot read image (%s), skipped", path.name, e)
            continue
        candidates.append(cand)
    return candidates


def load_photos(
    photo_dir: Path,
    points: list[TrackPoint],
    max_distance_m: float = 50.0,
    utc_offset_hours: float | None = None,
    exclude: set[Path] | None = None,
) -> list[Photo]:
    """Place every photo from photo_dir on the track. See the module docstring for the rules.

    exclude: files in photo_dir that are not photos (e.g. the event logo kept in the same folder).
    """
    placed: list[Photo] = []
    by_time: list[_Candidate] = []
    assumed: list[_Candidate] = []

    skip = {p.resolve() for p in exclude or set()}
    for c in _read_candidates(photo_dir, points, skip):
        if c.gps is not None:
            idx, dist = nearest_point(points, *c.gps)
            if dist > max_distance_m and not c.manual:
                logger.info(
                    "%s: GPS %.0f m from the track (limit %.0f m), skipped",
                    c.name,
                    dist,
                    max_distance_m,
                )
                continue
            source = SOURCE_MANUAL if c.manual else SOURCE_GPS
            placed.append(Photo(c.name, c.gps[0], c.gps[1], idx, c.thumb_b64, c.full_b64, source))
        elif c.taken is not None:
            by_time.append(c)
        else:
            assumed.append(c)

    if by_time:
        offset = _choose_offset(by_time, points, utc_offset_hours)
        if offset is None:
            logger.warning(
                "No UTC offset puts the photos' capture times inside the activity (camera clock "
                "off?) - using the %d-minute assumption for %d photo(s)",
                ASSUMED_INTERVAL_MIN,
                len(by_time),
            )
            assumed += by_time
        else:
            for c in by_time:
                utc = _to_utc(c.taken, c.taken_offset if c.taken_offset is not None else offset)
                elapsed = (utc - points[0].time).total_seconds()
                if not (-TIME_MARGIN_S <= elapsed <= points[-1].elapsed_s + TIME_MARGIN_S):
                    logger.warning(
                        "%s: capture time is outside the activity, using the assumption instead",
                        c.name,
                    )
                    assumed.append(c)
                    continue
                placed.append(_on_track(c, points, index_at_elapsed(points, elapsed), SOURCE_TIME))

    if assumed:
        assumed.sort(key=lambda c: c.name)
        duration_min = points[-1].elapsed_s / 60.0
        spacing = ASSUMED_INTERVAL_MIN
        if len(assumed) * spacing > duration_min:
            spacing = duration_min / (len(assumed) + 1)  # does not fit: spread over the activity
        logger.warning(
            "%d photo(s) without GPS or usable capture time: assuming one every %.1f min, "
            "first %.1f min after the start (file-name order)",
            len(assumed),
            spacing,
            spacing,
        )
        for i, c in enumerate(assumed, start=1):
            placed.append(
                _on_track(c, points, index_at_elapsed(points, i * spacing * 60.0), SOURCE_ASSUMED)
            )

    placed.sort(key=lambda p: p.track_index)
    counts = {s: sum(p.source == s for p in placed) for s in sorted({p.source for p in placed})}
    logger.info("Placed %d photo(s): %s", len(placed), counts or "none")
    return placed
