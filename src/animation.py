"""Build a self-contained HTML animation of a run (Leaflet map + stats + photo pins)."""

import base64
import json
import mimetypes
from pathlib import Path

from src.gpx_track import TrackPoint, elevation_gain_m
from src.photos import Photo

TEMPLATE_PATH = Path(__file__).parent / "template.html"


def build_payload(
    name: str, points: list[TrackPoint], photos: list[Photo], logo: Path | None = None
) -> dict:
    total_s = points[-1].elapsed_s
    total_m = points[-1].dist_m
    return {
        "name": name,
        "logo": _logo_data_uri(logo) if logo else None,
        "date": points[0].time.strftime("%Y-%m-%d %H:%M UTC"),
        "total_s": total_s,
        "total_m": total_m,
        "avg_pace": (total_s / 60) / (total_m / 1000) if total_m > 0 else None,
        "gain_m": elevation_gain_m(points),
        # Parallel arrays keep the embedded JSON small (~4k points per run).
        "lat": [round(p.lat, 6) for p in points],
        "lon": [round(p.lon, 6) for p in points],
        "ele": [None if p.ele is None else round(p.ele, 1) for p in points],
        "t": [round(p.elapsed_s, 1) for p in points],
        "dist": [round(p.dist_m, 1) for p in points],
        "pace": [None if p.pace_min_km is None else round(p.pace_min_km, 2) for p in points],
        "hr": [p.hr for p in points],
        "photos": [
            {
                "name": ph.name,
                "lat": ph.lat,
                "lon": ph.lon,
                "idx": ph.track_index,
                "thumb": ph.thumb_b64,
                "full": ph.full_b64,
                "source": ph.source,
            }
            for ph in photos
        ],
    }


def _logo_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def write_animation(
    name: str,
    points: list[TrackPoint],
    photos: list[Photo],
    output_path: Path,
    logo: Path | None = None,
) -> None:
    payload = build_payload(name, points, photos, logo)
    # "</" would let embedded text close the <script> tag early.
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE_PATH.read_text(encoding="utf-8").replace("__DATA__", data_json)
    html = html.replace("__TITLE__", name.replace("<", "&lt;"))
    output_path.write_text(html, encoding="utf-8")
