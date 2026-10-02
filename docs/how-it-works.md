# How it works

```
GPX ──► gpx_track.read_gpx ──► points (lat, lon, ele, time, hr, distance, pace)
                                   │
photos ──► photos.load_photos ─────┤  (each photo gets a track index)
                                   ▼
logo, name ──────────► animation.write_animation ──► template.html + embedded JSON ──► one .html
```

| Module | Role |
|---|---|
| [src/main.py](../src/main.py) | CLI and `run()`: checks inputs, wires the steps, names the output file. |
| [src/gpx_track.py](../src/gpx_track.py) | Parses GPX, computes cumulative distance, elapsed time, smoothed pace, elevation gain. |
| [src/photos.py](../src/photos.py) | Reads EXIF, decides where each photo belongs on the track, makes thumbnails. |
| [src/animation.py](../src/animation.py) | Builds the JSON payload and injects it into the template. |
| [src/template.html](../src/template.html) | The page: Leaflet map, stats, controls, elevation profile, photo pins. All JavaScript is inline. |
| [src/geotag.py](../src/geotag.py) | Optional tool: writes positions into photos' EXIF GPS. |

## Track processing

- **Distance** is the sum of haversine distances between consecutive points.
- **Pace** is the distance covered in a trailing 10 s window, converted to min/km. Raw point-to-point speed at 1 Hz is too noisy. Pace slower than 20 min/km is treated as standing still and shown as "–". Garmin files may sample less often than once a second; the window then holds fewer points but the result is still valid.
- **Elevation gain** counts a climb only after the height changed by at least 1 m from the last reference, which suppresses barometer noise.
- Points without a timestamp are dropped; fewer than two timestamped points is an error.

## Photo placement

See the README for the four methods. Details that matter:

- Matching by position takes the nearest track point, so on a route that passes the same place twice the photo may land on the wrong pass. Time-based placement does not have this problem.
- Capture time (`DateTimeOriginal`) is naive local time. With `OffsetTimeOriginal` it is exact. Without it, the offset is chosen among whole and half hours from -12 to +14 as the one that puts most photos inside the activity (± 5 minutes). Ties go to the offset closest to the track's solar time zone. If one hour of daylight saving fits as well as another, the choice can be wrong: pass `--photo-utc-offset`.
- A photo whose capture time falls outside the activity (camera clock off) falls back to the 10-minute assumption.
- Photos are rotated according to EXIF orientation, then encoded twice: a 96 px square thumbnail and a 1280 px JPEG (quality 82).

## The page

- The payload is stored as parallel arrays (`lat`, `lon`, `ele`, `t`, `dist`, `pace`, `hr`) plus the photo list. `t` is seconds from the start; the player moves through the arrays by time, not by index, so pauses in the recording are replayed as pauses.
- **Track colour:** the track is split into segments of 15 points, each coloured by the mean of the chosen metric on a blue (low) → red (high) scale. The scale spans the 5th–95th percentile of the metric so a single outlier does not flatten it. Pace is converted to speed first, so red always means "more intensity".
- **Photo pins** appear when the runner reaches the photo's track index and are removed again when the animation is rewound. The elevation profile marks each photo with a camera badge: grey before it is reached, blue after.
- Playback speed 10×–300×; clicking the profile or dragging the slider seeks.

## Extending

- **DEM elevation:** replace `ele` in `read_gpx` (or in `build_payload`) with values sampled from a raster; the page only reads the `ele` array.
- **Another metric for the colour:** add an entry to `METRICS` (and an icon to `ICONS`) in the template and the matching array to `build_payload`.
- **Another map:** add a layer to the `base` object in the template.
