# cvgl-streetview-dataset-scraping

Tools for collecting street-level panoramas over a bounded geographic area, intended for building
ground-view image sets for cross-view geo-localization (CVGL) experiments.

Given a centre coordinate and a radius, the pipeline enumerates the Google Street View panoramas
inside the area, downloads each one at full resolution as an equirectangular image, and optionally
reprojects it into perspective views.

## Method

**1. Panorama enumeration.** The area is covered with a regular grid of query points
(`resolution` × `resolution` over the bounding square, clipped to the circle of the given radius).
Each point is sent to the Street View panorama search, which returns the nearest panorama within
50 m together with its neighbours along the road graph and the older captures taken at the same
position. Results are merged and de-duplicated by panorama ID. Because one query returns several
dozen panoramas, a grid spacing of 30–50 m is sufficient for complete coverage of the road network;
denser grids only increase the number of requests.

**2. Download.** Panoramas are stored by Google as 512 × 512 px tiles. All tiles of the highest
zoom level are fetched and stitched into a single equirectangular image. The tile grid depends on
the camera generation and is detected per panorama:

| Tile grid | Image size (px) |
|-----------|-----------------|
| 32 × 16   | 16384 × 8192    |
| 26 × 13   | 13312 × 6656    |

**3. Projection.** Each equirectangular image is converted to a cube map and the four horizontal
faces (front, right, back, left; 90° field of view each) are saved as separate images.

## Usage

Python 3.10 or newer is required.

```
pip install -r requirements.txt
```

Set the area in `config.yaml`, then run the three stages in order:

```
python 1_get_panoid_info.py      # writes panoids_<N>.json and Result.html
python 2_download_panoramas.py   # writes panoramas/
python 3_project_panoramas.py    # writes cube_pano/
```

The download stage skips panoramas that already exist on disk, so an interrupted run can be
resumed by starting it again. It stops on its own when less than 20 GB of disk space is left
(`MIN_FREE_GB`). Only one `panoids_*.json` file may be present in the working
directory.

## Configuration

| Key                    | Description                                                            |
|------------------------|------------------------------------------------------------------------|
| `center`               | Latitude and longitude of the area centre, in decimal degrees          |
| `radius`               | Radius of the area in kilometres                                       |
| `resolution`           | Number of grid steps per side of the bounding square                   |
| `projected_resolution` | Edge length of the projected views in pixels                           |
| `sides`                | Which of the four horizontal views to keep                             |

The grid spacing is approximately `2 * radius / resolution`; for a 3 km radius, `resolution: 150`
gives a 40 m spacing.

## Output

`panoids_<N>.json` holds one record per panorama:

```json
{"panoid": "E5oQDPjCGSkJZ5DKCgeOLw", "lat": 50.773069, "lon": 14.207447, "year": 2019, "month": 9}
```

`year` and `month` are present only where the search response reports a capture date, which is the
case for the panorama nearest to a query point and for its older captures.

| Path                                   | Content                                         |
|----------------------------------------|-------------------------------------------------|
| `Result.html`                          | Map of the area with all panorama positions     |
| `panoramas/<lat>_<lon>_<panoid>.jpg`   | Equirectangular panorama, JPEG quality 30       |
| `cube_pano/<lat>_<lon>_<side>.jpg`     | Perspective view, `projected_resolution` square |

A panorama occupies 2–5 MB on disk and requires 338 or 512 tile requests.

## Limitations

- The search and tile endpoints are internal to Google Maps and undocumented. They have changed
  before and may change again without notice.
- Automated bulk retrieval may conflict with the Google Maps Platform Terms of Service. The imagery
  remains the property of Google and its contributors; check the terms before redistributing
  anything collected with these tools.
- Positions are those reported by Street View and inherit its GPS error, typically a few metres.
- Only official Street View captures are collected; user-contributed photospheres are excluded.

## Acknowledgements

Based on [Streetview-panorama-scraping](https://github.com/FluffyMaguro/Streetview-panorama-scraping)
by FluffyMaguro, with thanks. The `streetview` module originates from
[robolyst/streetview](https://github.com/robolyst/streetview).
