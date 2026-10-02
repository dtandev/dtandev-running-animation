# Example: Mazurski Maraton Rolkowy

A real inline skating activity (Ruciane-Nida, 22.7 km), with four photos and the event logo. The finished animation is [mazurski-maraton-rolkowy.html](mazurski-maraton-rolkowy.html): download it and open it in a browser (it needs internet access for the map).

Regenerate it from the files in this folder, from the repository root:

```bash
just run --gpx examples/mazurski-maraton-rolkowy/activity.gpx \
         --photos examples/mazurski-maraton-rolkowy/photos \
         --logo examples/mazurski-maraton-rolkowy/logo.png \
         --name "Mazurski Maraton Rolkowy" \
         --output examples/mazurski-maraton-rolkowy
```

Notes:

- The GPS tags in the photos are illustrative. The pictures themselves carry no position, so I spread them over the route 16 to 18 minutes apart. The pins show how the feature looks, not where the photos were really taken.
- The photos are scaled down to 1600 px on the long side.
- The photos and the logo are not covered by the MIT licence of this repository. They belong to their owners and are included only to demonstrate the generator.
