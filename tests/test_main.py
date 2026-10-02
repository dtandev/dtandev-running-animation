"""
Tests for the GPX -> HTML animation pipeline.

Run with: just test
"""

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from src.gpx_track import elevation_gain_m, haversine_m, read_gpx
from src.main import run, slugify
from src.photos import load_photos

GPX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:ns3="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><name>Test run</name><trkseg>
{points}
  </trkseg></trk>
</gpx>
"""

# ~3.3 m/s due east along 53.77N: 0.00005 deg lon ~= 3.3 m, 1 s apart -> ~5:00 min/km
LON_STEP = 0.00005


def _gpx(n: int = 60, with_hr: bool = True) -> str:
    pts = []
    for i in range(n):
        ext = (
            f"<extensions><ns3:TrackPointExtension><ns3:hr>{120 + i}</ns3:hr>"
            "</ns3:TrackPointExtension></extensions>"
            if with_hr
            else ""
        )
        pts.append(
            f'<trkpt lat="53.77" lon="{20.47 + i * LON_STEP:.6f}"><ele>{100 + i * 0.5}</ele>'
            f"<time>2026-09-21T14:00:{i:02d}.000Z</time>{ext}</trkpt>"
        )
    return GPX_TEMPLATE.format(points="\n".join(pts))


def _write_gpx(tmp_path: Path, **kw) -> Path:
    path = tmp_path / "run.gpx"
    path.write_text(_gpx(**kw), encoding="utf-8")
    return path


def _geotagged_jpeg(path: Path, lat: float, lon: float) -> None:
    img = Image.new("RGB", (400, 300), "green")
    exif = Image.Exif()
    gps = {
        1: "N",
        2: (int(lat), int((lat % 1) * 60), ((lat % 1) * 60 % 1) * 60),
        3: "E",
        4: (int(lon), int((lon % 1) * 60), ((lon % 1) * 60 % 1) * 60),
    }
    exif[0x8825] = gps
    img.save(path, "JPEG", exif=exif)


def test_haversine_one_degree_latitude():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)


def test_read_gpx_distance_pace_and_extensions(tmp_path):
    name, pts = read_gpx(_write_gpx(tmp_path))
    assert name == "Test run"
    assert len(pts) == 60
    assert pts[0].hr == 120
    assert pts[-1].elapsed_s == 59
    assert pts[-1].dist_m == pytest.approx(59 * 3.3, rel=0.02)
    assert pts[-1].pace_min_km == pytest.approx(5.05, rel=0.05)


def test_read_gpx_without_extensions(tmp_path):
    _, pts = read_gpx(_write_gpx(tmp_path, with_hr=False))
    assert pts[0].hr is None


def test_standing_still_has_no_pace(tmp_path):
    path = tmp_path / "still.gpx"
    pts = "\n".join(
        f'<trkpt lat="53.77" lon="20.47"><time>2026-09-21T14:00:{i:02d}.000Z</time></trkpt>'
        for i in range(30)
    )
    path.write_text(GPX_TEMPLATE.format(points=pts), encoding="utf-8")
    _, parsed = read_gpx(path)
    assert parsed[-1].pace_min_km is None


def test_too_short_track_rejected(tmp_path):
    with pytest.raises(ValueError):
        read_gpx(_write_gpx(tmp_path, n=1))


def test_elevation_gain_ignores_noise(tmp_path):
    _, pts = read_gpx(_write_gpx(tmp_path))
    assert elevation_gain_m(pts) == pytest.approx(29.5, abs=1.0)
    for p, e in zip(pts, [100, 100.4, 100, 100.4] * 15, strict=False):
        p.ele = e
    assert elevation_gain_m(pts) == 0


def _long_gpx_path(tmp_path: Path, minutes: int = 40) -> Path:
    """Track starting 14:00:00Z with a point every 10 s, moving east (index i = i * 10 s)."""
    pts = []
    for i in range(minutes * 6 + 1):
        t = f"2026-09-21T{14 + i * 10 // 3600:02d}:{i * 10 % 3600 // 60:02d}:{i * 10 % 60:02d}.000Z"
        pts.append(
            f'<trkpt lat="53.77" lon="{20.47 + i * 10 * LON_STEP / 1:.6f}"><ele>100</ele>'
            f"<time>{t}</time></trkpt>"
        )
    path = tmp_path / "long.gpx"
    path.write_text(GPX_TEMPLATE.format(points="\n".join(pts)), encoding="utf-8")
    return path


def _jpeg_taken(path: Path, taken: str | None, offset: str | None = None) -> None:
    exif = Image.Exif()
    ifd = {}
    if taken:
        ifd[36867] = taken
    if offset:
        ifd[36880] = offset
    if ifd:
        exif[0x8769] = ifd
    Image.new("RGB", (40, 30), "blue").save(path, "JPEG", exif=exif)


def _photo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "photos"
    d.mkdir()
    return d


def test_gps_photo_near_track_is_matched_and_far_one_skipped(tmp_path):
    _, pts = read_gpx(_write_gpx(tmp_path))
    d = _photo_dir(tmp_path)
    _geotagged_jpeg(d / "near.jpg", 53.77, 20.47 + 30 * LON_STEP)
    _geotagged_jpeg(d / "far.jpg", 53.80, 20.47)

    photos = load_photos(d, pts, max_distance_m=50)

    assert [(p.name, p.source) for p in photos] == [("near.jpg", "gps")]
    assert photos[0].track_index == pytest.approx(30, abs=1)


def test_capture_time_matched_with_inferred_offset(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    _jpeg_taken(d / "a.jpg", "2026:09:21 16:20:00")  # camera in UTC+2 -> 14:20Z = 20 min

    photos = load_photos(d, pts)

    assert [(p.name, p.source) for p in photos] == [("a.jpg", "time")]
    assert photos[0].track_index == 120


def test_capture_time_with_explicit_offset_option(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    _jpeg_taken(d / "a.jpg", "2026:09:21 15:10:00")

    photos = load_photos(d, pts, utc_offset_hours=1)  # 14:10Z = 10 min

    assert photos[0].source == "time"
    assert photos[0].track_index == 60


def test_capture_time_uses_offset_time_original_tag(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    _jpeg_taken(d / "a.jpg", "2026:09:21 16:30:00", "+02:00")  # 14:30Z = 30 min

    photos = load_photos(d, pts)

    assert photos[0].source == "time"
    assert photos[0].track_index == 180


def test_capture_time_outside_activity_falls_back_to_assumption(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    _jpeg_taken(d / "a.jpg", "2026:01:01 12:00:00")  # months before the activity

    photos = load_photos(d, pts)

    assert photos[0].source == "assumed"
    assert photos[0].track_index == 60  # first assumed photo: 10 min


def test_photos_without_gps_or_time_are_spaced_ten_minutes_by_filename(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        _jpeg_taken(d / name, None)

    photos = load_photos(d, pts)

    by_name = {p.name: p for p in photos}
    assert {p.source for p in photos} == {"assumed"}
    assert [by_name[n].track_index for n in ("a.jpg", "b.jpg", "c.jpg")] == [60, 120, 180]


def test_assumed_spacing_shrinks_when_photos_do_not_fit(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path, minutes=40))
    d = _photo_dir(tmp_path)
    for i in range(5):  # 5 x 10 min > 40 min -> spacing 40 / 6 min
        _jpeg_taken(d / f"p{i}.jpg", None)

    photos = load_photos(d, pts)

    mins = [pts[p.track_index].elapsed_s / 60 for p in photos]
    assert len(photos) == 5
    assert mins == sorted(mins)
    assert mins[-1] < 40
    assert min(b - a for a, b in zip(mins, mins[1:], strict=False)) > 5


def test_each_photo_uses_its_best_source(tmp_path):
    _, pts = read_gpx(_long_gpx_path(tmp_path))
    d = _photo_dir(tmp_path)
    _geotagged_jpeg(d / "a_gps.jpg", 53.77, 20.47 + 600 * LON_STEP)
    _jpeg_taken(d / "b_time.jpg", "2026:09:21 16:30:00", "+02:00")
    _jpeg_taken(d / "c_none.jpg", None)

    photos = {p.name: p for p in load_photos(d, pts)}

    assert photos["a_gps.jpg"].source == "gps"
    assert photos["b_time.jpg"].source == "time"
    assert photos["c_none.jpg"].source == "assumed"
    assert photos["c_none.jpg"].track_index == 60  # numbered among assumed photos only


def test_photo_location_from_sidecar_file(tmp_path):
    _, pts = read_gpx(_write_gpx(tmp_path))
    d = _photo_dir(tmp_path)
    Image.new("RGB", (50, 50)).save(d / "shot.png")  # no EXIF at all
    (d / "locations.json").write_text(
        json.dumps({"shot.png": [53.77, 20.47 + 20 * LON_STEP]}), encoding="utf-8"
    )

    photos = load_photos(d, pts)

    assert [(p.name, p.source) for p in photos] == [("shot.png", "manual")]
    assert photos[0].track_index == pytest.approx(20, abs=1)


def test_photo_location_by_track_km(tmp_path):
    _, pts = read_gpx(_write_gpx(tmp_path))
    d = _photo_dir(tmp_path)
    Image.new("RGB", (50, 50)).save(d / "a.jpg")
    (d / "locations.json").write_text(
        json.dumps({"_comment": "x", "a.jpg": {"km": 0.1}}), encoding="utf-8"
    )

    photos = load_photos(d, pts)

    assert photos[0].track_index == pytest.approx(30, abs=1)  # 100 m / 3.3 m per point


def test_run_generates_everything_from_four_inputs(tmp_path):
    gpx = _write_gpx(tmp_path)
    d = _photo_dir(tmp_path)
    _geotagged_jpeg(d / "a.jpg", 53.77, 20.47 + 10 * LON_STEP)
    logo = tmp_path / "logo.png"
    Image.new("RGB", (20, 10), "red").save(logo)

    out = run(gpx, tmp_path / "out", d, logo, "Półmaraton Test")

    assert out == tmp_path / "out" / "polmaraton-test.html"
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html
    assert "data:image/png;base64," in html
    data = json.loads(re.search(r"const D = (\{.*?\});\nconst N", html, re.S).group(1))
    assert data["name"] == "Półmaraton Test"
    assert len(data["t"]) == 60
    assert [p["source"] for p in data["photos"]] == ["gps"]


def test_run_defaults_name_from_gpx_and_works_without_photos(tmp_path):
    out = run(_write_gpx(tmp_path), tmp_path / "out")

    assert out.name == "test-run.html"
    assert '"photos":[]' in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "kwargs",
    [{"gpx": "missing.gpx"}, {"logo": "nope.png"}, {"photos_dir": "nodir"}],
)
def test_run_missing_inputs_raise(tmp_path, kwargs):
    args = {"gpx": _write_gpx(tmp_path), "output_dir": tmp_path / "out"}
    for key, value in kwargs.items():
        args[key] = tmp_path / value
    with pytest.raises(FileNotFoundError):
        run(**args)


def test_slugify():
    assert slugify("Mazurski Maraton Rolkowy") == "mazurski-maraton-rolkowy"
    assert slugify("Półmaraton Łódź 2026!") == "polmaraton-lodz-2026"
    assert slugify("???") == "animation"


def test_geotag_writes_exif_gps_without_touching_pixels(tmp_path):
    from src.geotag import run as geotag_run
    from src.photos import read_gps

    gpx = _write_gpx(tmp_path)
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    img = Image.effect_noise((64, 64), 80).convert("RGB")
    img.save(photos_dir / "a.jpg", "JPEG", quality=90)
    before = Image.open(photos_dir / "a.jpg").tobytes()
    (photos_dir / "locations.json").write_text(
        json.dumps({"a.jpg": {"km": 0.1}, "b.png": {"km": 0.1}}), encoding="utf-8"
    )

    tagged = geotag_run(gpx, photos_dir, backup_dir=tmp_path / "bak")

    assert [p.name for p in tagged] == ["a.jpg"]
    with Image.open(photos_dir / "a.jpg") as out:
        lat, lon = read_gps(out)
        assert out.tobytes() == before  # decoded pixels identical -> no re-encoding
    assert lat == pytest.approx(53.77, abs=1e-5)
    assert lon == pytest.approx(20.47 + 30 * LON_STEP, abs=1e-4)
    assert (tmp_path / "bak" / "a.jpg").exists()


def test_logo_in_photo_folder_is_not_a_photo(tmp_path):
    d = _photo_dir(tmp_path)
    _geotagged_jpeg(d / "a.jpg", 53.77, 20.47 + 10 * LON_STEP)
    Image.new("RGB", (20, 10), "red").save(d / "logo.png")

    out = run(_write_gpx(tmp_path), tmp_path / "out", d, logo=d / "logo.png")

    html = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r"const D = (\{.*?\});\nconst N", html, re.S).group(1))
    assert [p["name"] for p in data["photos"]] == ["a.jpg"]
