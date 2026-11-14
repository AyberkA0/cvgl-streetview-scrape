# cvgl-streetview-dataset-scraping

A command line tool for collecting paired ground-level and aerial images over a bounded geographic
area, intended for cross-view geo-localization (CVGL) experiments.

Given a circle, a boundary polygon, or both, it enumerates the Google Street View panoramas inside
the area and produces one image pair per panorama:

| View   | Default size (px) | Content                                                              |
|--------|-------------------|----------------------------------------------------------------------|
| Ground | 1232 × 324        | 360° panorama strip, north at the image centre, ±47° around horizon  |
| Aerial | 256 × 256         | Satellite patch, north up, centred on the panorama position          |

## Examples

Pairs collected on the campus of Karabük University, scaled down for display. Imagery © Google and
its providers.

| Ground view (1232 × 324) | Aerial view (256 × 256) |
|--------------------------|-------------------------|
| <img src="docs/samples/1_ground.jpg" width="616"> | <img src="docs/samples/1_aerial.jpg" width="162"> |
| <img src="docs/samples/2_ground.jpg" width="616"> | <img src="docs/samples/2_aerial.jpg" width="162"> |
| <img src="docs/samples/3_ground.jpg" width="616"> | <img src="docs/samples/3_aerial.jpg" width="162"> |
| <img src="docs/samples/4_ground.jpg" width="616"> | <img src="docs/samples/4_aerial.jpg" width="162"> |

## Installation

Python 3.10 or newer is required.

```
git clone https://github.com/AyberkA0/cvgl-streetview-dataset-scraping
cd cvgl-streetview-dataset-scraping
pip install .
```

This installs the `cvgl-scrape` command. Without installing, `python -m cvgl_scrape` is equivalent.

## Usage

Collect everything within 500 m of a point:

```
cvgl-scrape run --center 41.2074 32.6564 --radius 0.5 --out data/example
```

Collect everything inside a polygon, using the supplied configuration for the campus of Karabük
University:

```
cvgl-scrape run --config configs/karabuk_university.yaml
```

Inspect a few pairs before committing to a full run:

```
cvgl-scrape run --config configs/karabuk_university.yaml --limit 10
```

`run` executes three stages, which are also available as separate commands:

| Command  | Action                                                                  |
|----------|-------------------------------------------------------------------------|
| `search` | Lists the panoramas inside the area in `metadata.csv` and draws the map |
| `ground` | Downloads the ground view of every listed panorama                      |
| `aerial` | Downloads the aerial view of every listed panorama                      |
| `status` | Reports how many views and complete pairs a dataset directory holds     |

Images that already exist are skipped, so an interrupted download is resumed by running the same
command again. The exit status is non-zero if any request failed permanently.

### Options

| Option                | Default      | Description                                                 |
|-----------------------|--------------|-------------------------------------------------------------|
| `-o`, `--out`         | `dataset`    | Dataset directory                                           |
| `-c`, `--config`      |              | YAML file providing defaults for the options below          |
| `--center LAT LON`    |              | Centre of a circular area, in decimal degrees               |
| `--radius KM`         |              | Radius of the circular area                                 |
| `--boundary GEOJSON`  |              | Polygon or multipolygon; panoramas outside of it are dropped|
| `--spacing M`         | `40`         | Distance between query points                               |
| `--ground-size WxH`   | `1232x324`   | Size of the ground view                                     |
| `--aerial-size PX`    | `256`        | Edge length of the aerial view                              |
| `--zoom`              | `19`         | Web Mercator zoom level of the aerial view                  |
| `--limit N`           |              | Download only the first N panoramas                         |
| `--concurrency N`     | `16`         | Panoramas processed at the same time                        |

Either `--center` with `--radius`, or `--boundary`, is required; with both, the area is their
intersection. A configuration file uses the option names with underscores (`ground_size: 1232x324`);
options given on the command line take precedence.

## Output

```
<out>/
  metadata.csv     one row per panorama
  map.html         panorama positions on a map
  ground/          <panoid>.jpg
  aerial/          <panoid>.jpg
```

`metadata.csv` has the columns

| Column    | Description                                                                 |
|-----------|-----------------------------------------------------------------------------|
| `panoid`  | Street View panorama identifier, also the file name of both views           |
| `lat`     | Latitude in decimal degrees (WGS 84)                                        |
| `lon`     | Longitude in decimal degrees (WGS 84)                                       |
| `heading` | Compass direction of the centre of the original panorama, in degrees        |
| `year`    | Capture year, empty if not reported                                         |
| `month`   | Capture month, empty if not reported                                        |

A panorama can be listed and still be unavailable for download; such rows have no ground view.

## Method

**Panorama enumeration.** The bounding box of the area is covered with a regular grid of query
points. Each point is sent to the Street View panorama search, which returns the nearest panorama
within 50 m together with its neighbours along the road graph and the older captures taken at the
same position. Results are merged by panorama identifier and restricted to the area. Because one
query returns several dozen panoramas, a grid spacing of 30–50 m is sufficient for complete
coverage of the road network. Capture dates are reported only for the panorama nearest to a query
point and for its older captures.

**Ground view.** Panoramas are stored as 512 × 512 px tiles in an equirectangular layout. The tiles
of zoom level 3 (4096 × 2048 px, or 3328 × 1664 px for older cameras) are fetched and stitched. The
image is shifted horizontally by the reported heading so that north falls on the centre column,
cropped symmetrically around the horizon to the target aspect ratio, and resampled with a Lanczos
filter. A strip of *W* × *H* pixels spans 360° horizontally and 360° · *H* / *W* vertically, which
is 94.7° for the default size and removes most of the sky and of the capture vehicle. Camera pitch
and roll are not corrected.

**Aerial view.** The Web Mercator pixel coordinates of the panorama position are computed at a
fixed zoom level, the satellite tiles covering a window centred on that position are fetched, and
the window is cropped out. The ground sampling distance at zoom level *z* and latitude *φ* is

```
GSD = 2π · 6378137 · cos(φ) / (256 · 2^z)   [m/px]
```

which at zoom 19 gives 22.5 cm/px at 41.2° N, so that a 256 px patch covers 57.5 m. The zoom level
is fixed for the whole dataset; the GSD therefore varies with cos(φ) across latitudes.

## Limitations

- The search and tile endpoints are internal to Google Maps and undocumented. They have changed
  before and may change again without notice.
- Automated bulk retrieval may conflict with the Google Maps Platform Terms of Service. The imagery
  remains the property of Google and its providers; check the terms before redistributing anything
  collected with this tool.
- Positions are those reported by Street View and inherit its GPS error, typically a few metres,
  which translates into an offset of the panorama from the centre of the aerial patch.
- Older captures of the same position are kept as separate panoramas and are paired with nearly
  identical aerial patches. Splitting such a dataset at random leaks positions between the training
  and the test set.
- The aerial imagery has a single, unknown acquisition date and may not match the season or year of
  the ground view.
- Only official Street View captures are collected; user-contributed photospheres are excluded.

## Development

```
pip install -e ".[dev]"
pytest
```

## License

The code is released under the MIT License, see [LICENSE](LICENSE). The licence covers the code only,
not the imagery retrieved with it nor the sample images in `docs/samples`.

## Acknowledgements

The grid-based enumeration of panoramas follows the idea of
[Streetview-panorama-scraping](https://github.com/FluffyMaguro/Streetview-panorama-scraping) by
FluffyMaguro, with thanks. The campus boundary is taken from OpenStreetMap, © OpenStreetMap
contributors.
