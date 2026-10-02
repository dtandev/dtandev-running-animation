"""Reading GPX activities and computing per-point distance, speed and pace."""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EARTH_RADIUS_M = 6_371_000.0
# Window (seconds) over which speed is averaged. GPS jitter at 1 Hz makes raw
# point-to-point speed useless, ~10 s gives a pace that matches a watch display.
SMOOTHING_WINDOW_S = 10
# Pace slower than this (min/km) is treated as standing still.
MAX_PACE_MIN_KM = 20.0


@dataclass
class TrackPoint:
    lat: float
    lon: float
    ele: float | None
    time: datetime
    hr: int | None = None
    cad: int | None = None
    dist_m: float = 0.0  # cumulative distance from start
    elapsed_s: float = 0.0  # seconds from first point
    pace_min_km: float | None = None  # smoothed; None when standing still


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _local(tag: str) -> str:
    """Strip the XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: ET.Element, name: str) -> str | None:
    for child in elem.iter():
        if _local(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def read_gpx(path: Path) -> tuple[str, list[TrackPoint]]:
    """Return (activity name, points) with distance, elapsed time and pace filled in."""
    root = ET.parse(path).getroot()
    name = path.stem
    for elem in root.iter():
        if _local(elem.tag) == "trk":
            name = _child_text(elem, "name") or name
            break

    points: list[TrackPoint] = []
    for trkpt in root.iter():
        if _local(trkpt.tag) != "trkpt":
            continue
        time_text = _child_text(trkpt, "time")
        if time_text is None:
            continue  # animation is time-based, points without a timestamp are unusable
        ele_text = _child_text(trkpt, "ele")
        hr_text = _child_text(trkpt, "hr")
        cad_text = _child_text(trkpt, "cad")
        points.append(
            TrackPoint(
                lat=float(trkpt.attrib["lat"]),
                lon=float(trkpt.attrib["lon"]),
                ele=float(ele_text) if ele_text else None,
                time=_parse_time(time_text),
                hr=int(hr_text) if hr_text else None,
                cad=int(cad_text) if cad_text else None,
            )
        )

    if len(points) < 2:
        raise ValueError(f"{path.name}: fewer than 2 timestamped track points")

    _fill_derived(points)
    return name, points


def _fill_derived(points: list[TrackPoint]) -> None:
    t0 = points[0].time
    for prev, cur in zip(points, points[1:], strict=False):
        cur.dist_m = prev.dist_m + haversine_m(prev.lat, prev.lon, cur.lat, cur.lon)
    for p in points:
        p.elapsed_s = (p.time - t0).total_seconds()

    # Smoothed pace: distance covered over a trailing time window.
    start = 0
    for i, p in enumerate(points):
        while p.elapsed_s - points[start].elapsed_s > SMOOTHING_WINDOW_S:
            start += 1
        dt = p.elapsed_s - points[start].elapsed_s
        dd = p.dist_m - points[start].dist_m
        if dt <= 0 or dd <= 0:
            p.pace_min_km = None
            continue
        pace = (dt / 60.0) / (dd / 1000.0)
        p.pace_min_km = pace if pace <= MAX_PACE_MIN_KM else None


def elevation_gain_m(points: list[TrackPoint], threshold_m: float = 1.0) -> float:
    """Total ascent, ignoring changes smaller than threshold_m to suppress barometer noise."""
    gain = 0.0
    ref: float | None = None
    for p in points:
        if p.ele is None:
            continue
        if ref is None:
            ref = p.ele
        elif p.ele - ref >= threshold_m:
            gain += p.ele - ref
            ref = p.ele
        elif ref - p.ele >= threshold_m:
            ref = p.ele
    return gain
