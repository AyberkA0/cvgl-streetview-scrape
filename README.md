# cvgl-streetview-dataset-scraping

Tools for collecting paired ground-level and aerial images over a bounded geographic area, intended
for cross-view geo-localization (CVGL) experiments.

Given a centre coordinate, a radius and optionally a boundary polygon, the pipeline enumerates the
Google Street View panoramas inside the area and produces one image pair per panorama:

| View   | Size (px)  | Content                                                              |
|--------|------------|----------------------------------------------------------------------|
| Ground | 1232 × 324 | 360° panorama strip, north at the image centre, ±47° around horizon  |
| Aerial | 256 × 256  | Satellite patch, north up, centred on the panorama position          |

## Method

**1. Panorama enumeration.** The area is covered with a regular grid of query points
(`resolution` × `resolution` over the bounding square, clipped to the circle of the given radius).
Each point is sent to the Street View panorama search, which returns the nearest panorama within
50 m together with its neighbours along the road graph and the older captures taken at the same
position. Results are merged, de-duplicated by panorama ID and, if a boundary is given, restricted
to the panoramas inside the polygon. Because one query returns several dozen panoramas, a grid
spacing of 30–50 m is sufficient for complete coverage of the road network.

**2. Ground view.** Panoramas are stored by Google as 512 × 512 px tiles in an equirectangular
layout. The tiles of zoom level 3 (4096 × 2048 px, or 3328 × 1664 px for older cameras) are fetched
and stitched. The image is then shifted horizontally by the reported heading so that north falls on
the centre column, cropped symmetrically around the horizon to the target aspect ratio, and
resampled to the target size with a Lanczos filter. With the default 1232 × 324 px the strip spans
360° horizontally and 94.7° vertically, which removes most of the sky and of the capture vehicle.
Camera pitch and roll are not corrected.

**3. Aerial view.** For each panorama position the Web Mercator pixel coordinates at a fixed zoom
level are computed, the satellite tiles covering a window centred on that position are fetched, and
the window is cropped out. The ground sampling distance at zoom level *z* and latitude *φ* is

```
GSD = 2π · 6378137 · cos(φ) / (256 · 2^z)   [m/px]
```

which at zoom 19 gives 22.5 cm/px at 41.2° N, so that a 256 px patch covers about 57.5 m. The zoom
level is fixed for the whole dataset; the GSD therefore varies with cos(φ) across latitudes.

## Usage

Python 3.10 or newer is required.

```
pip install -r requirements.txt
```

Set the area in `config.yaml`, then run the three stages in order:

```
python 1_get_panoid_info.py      # writes panoids_<N>.json and Result.html
python 2_download_panoramas.py   # writes panoramas/
python 3_download_satellite.py   # writes satellite/
```

Stages 2 and 3 skip files that already exist, so an interrupted run can be resumed by starting it
again. Only one `panoids_*.json` file may be present in the working directory.

## Configuration

| Key                | Description                                                              |
|--------------------|--------------------------------------------------------------------------|
| `center`           | Latitude and longitude of the area centre, in decimal degrees            |
| `radius`           | Radius of the area in kilometres                                         |
| `resolution`       | Number of grid steps per side; spacing is about `2 * radius / resolution`|
| `boundary`         | Optional path to a GeoJSON polygon; panoramas outside of it are dropped  |
| `panorama.width`   | Width of the ground view in pixels                                       |
| `panorama.height`  | Height of the ground view in pixels                                      |
| `satellite.zoom`   | Web Mercator zoom level of the aerial view                               |
| `satellite.size`   | Edge length of the aerial view in pixels                                 |

The supplied configuration covers the campus of Karabük University.

## Output

`panoids_<N>.json` holds one record per panorama:

```json
{"panoid": "wiQBTe-MfUr7Xm_gXWj2Yg", "lat": 41.216408, "lon": 32.651809, "heading": 283.6693, "year": 2023, "month": 9}
```

`heading` is the compass direction of the centre of the original panorama in degrees. `year` and
`month` are present only where the search response reports a capture date, which is the case for
the panorama nearest to a query point and for its older captures.

The two images of a pair share the file name `<lat>_<lon>_<panoid>.jpg`:

| Path          | Content                                      |
|---------------|----------------------------------------------|
| `panoramas/`  | Ground views                                 |
| `satellite/`  | Aerial views                                 |
| `Result.html` | Map of the area with all panorama positions  |

## Limitations

- The search and tile endpoints are internal to Google Maps and undocumented. They have changed
  before and may change again without notice.
- Automated bulk retrieval may conflict with the Google Maps Platform Terms of Service. The imagery
  remains the property of Google and its providers; check the terms before redistributing anything
  collected with these tools.
- Positions are those reported by Street View and inherit its GPS error, typically a few metres,
  which translates into an offset of the panorama from the centre of the aerial patch.
- Older captures of the same position are kept as separate panoramas and are paired with nearly
  identical aerial patches. The aerial imagery has a single, unknown acquisition date and may not
  match the season or year of the ground view.
- Only official Street View captures are collected; user-contributed photospheres are excluded.

## Acknowledgements

Based on [Streetview-panorama-scraping](https://github.com/FluffyMaguro/Streetview-panorama-scraping)
by FluffyMaguro, with thanks. The `streetview` module originates from
[robolyst/streetview](https://github.com/robolyst/streetview). The campus boundary is taken from
OpenStreetMap, © OpenStreetMap contributors.
