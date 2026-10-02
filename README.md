# dtandev-running-animation

Generates an interactive HTML animation of a run (or any GPS activity) from a GPX track, a folder of photos, an event logo and the event name.

A dot moves along the route on a map while time, distance, pace, elevation and heart rate update live. The track is coloured by pace, heart rate or elevation. Photos appear as pins at the place where they were taken, and a click opens the full picture. The result is one self-contained `.html` file: no server, send it or host it anywhere.

By [Dariusz Tanajewski](https://dtanajewski.com).

## Install

Requires Python 3.11+, [uv](https://github.com/astral-sh/uv) and, optionally, [just](https://github.com/casey/just).

```bash
brew install uv just      # macOS
just setup                # uv sync + git hooks
```

## Usage

```bash
just run --gpx training_gpx/run.gpx \
         --photos photos/event \
         --logo photos/event/logo.png \
         --name "Event name"
```

Without `just`: `uv run python src/main.py --gpx ... --photos ... --logo ... --name ...`

The animation is written to `data/output/<event-name>.html`. Open it in a browser; map tiles and the Leaflet library load from the internet.

| Option | Meaning |
|---|---|
| `--gpx FILE` | GPX track with timestamps (required). Garmin Connect exports work; heart rate is read from the Garmin extension. |
| `--photos DIR` | Folder with JPEG/PNG photos (optional). |
| `--logo FILE` | Event logo shown in the page header (optional). It may sit in the photo folder, it is not treated as a photo. |
| `--name TEXT` | Event name, shown in the header and used as the file name (default: activity name from the GPX). |
| `--output DIR` | Output folder (default `data/output`). |
| `--photo-utc-offset H` | UTC offset of the camera clock, for photos placed by capture time (default: inferred). |
| `--photo-max-distance M` | Max distance between a GPS-tagged photo and the track (default 50 m). |

## Example

[examples/mazurski-maraton-rolkowy](examples/mazurski-maraton-rolkowy) holds a finished animation together with everything needed to regenerate it: the GPX track, four photos and the logo. Download the `.html` file from there and open it in a browser. The positions of the photos in that example are illustrative, see its README.

## Where photos land on the track

Decided per photo, the first method that works wins:

1. **`locations.json`** in the photo folder, an optional manual override: `{"IMG_1.jpg": {"km": 12.4}}` (distance along the track) or `{"IMG_1.jpg": [53.77, 20.47]}` (lat, lon). Keys starting with `_` are ignored.
2. **GPS tags in EXIF.** Photos further than `--photo-max-distance` from the track are skipped.
3. **Capture time in EXIF**, matched with the track's timestamps. If the camera did not record its time zone, the offset is inferred from where the photos fit into the activity.
4. **Assumption:** photos were taken 10 minutes apart, in file-name order, the first one 10 minutes after the start. If that does not fit into the activity, they are spread evenly.

The popup of a pin placed by method 3 or 4 says its position is estimated. The log shows how many photos were placed by which method; check it, methods 3 and 4 are guesses.

### Writing the positions into the photos

```bash
uv run python -m src.geotag --gpx training_gpx/run.gpx --photos photos/event --backup photos/event/_originals
```

Writes the `locations.json` positions into the JPEGs' EXIF GPS tags, so any photo app shows them. Only the EXIF block is rewritten (pixels are not re-encoded); originals are copied to `--backup` first.

## Development

```bash
just test     # pytest
just check    # ruff lint + format check
just fix      # ruff autofix + format
just lint     # all pre-commit hooks
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (checked by a pre-commit hook). How the code works: [docs/how-it-works.md](docs/how-it-works.md).

## Limitations

- Elevation comes from the GPX (watch barometer or GPS). Heights from a DEM are not supported yet.
- Pace is shown in min/km for every activity type, also for skating or cycling.
- Photos placed by capture time or by the 10-minute assumption are estimates. Screenshots and photos with stripped EXIF always end up in the assumption unless listed in `locations.json`. HEIC is not supported, export as JPEG.
- Photos are embedded in the HTML as base64 (thumbnail 96 px, full 1280 px), so many photos make a large file.
- The page needs internet access for the map (Esri satellite imagery by default, OpenStreetMap as an option) and Leaflet.
