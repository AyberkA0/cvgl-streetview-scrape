"""Compilation of a collected dataset directory into a training-ready dataset."""

import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image

from . import aerial
from .selection import split

COLUMNS = ["panoid", "area", "lat", "lon", "utm_x", "utm_y", "utm_zone", "heading", "year", "month",
           "split", "ground", "aerial"]

CARD = """# {name}

Paired ground-level and aerial images for cross-view geo-localization, collected with
[cvgl-streetview-scrape](https://github.com/AyberkA0/cvgl-streetview-scrape).

| | |
|---|---|
| Pairs | {pairs} |
| Ground view | {ground_size} px, 360° panorama strip, north at the image centre |
| Aerial view | {aerial_size} px, north up, centred on the panorama position |
| Ground sampling distance | {gsd} |
| Areas | {areas} |

## Layout

```
{name}/
  metadata.csv     one row per pair
  metadata.json    the same pairs as arrays, with the split indices
  splits/          one CSV file per split
  ground/          <panoid>.jpg
  aerial/          <panoid>.jpg
```

`metadata.csv` and the split files share the columns `{columns}`. `ground` and `aerial` are paths
relative to this directory. `heading` is the compass direction of the centre of the original
panorama; the stored ground views are already rotated so that north is at the centre column.
`year` and `month` are empty where the capture date is not reported.

`metadata.json` holds the same pairs in the order of `metadata.csv`:

| Key | Content |
|-----|---------|
| `panoIds` | Street View panorama identifiers |
| `latlng` | `[latitude, longitude]` in decimal degrees (WGS 84) |
| `utm` | `[easting, northing]` in metres |
| `utmZone` | UTM zone of each pair |
| `area` | Area of each pair |
| `trainSet`, `valSet`{test_key} | Zero-based indices of the pairs of each split |

UTM coordinates are planar, so the distance between two pairs of the same zone is the Euclidean
distance of their `utm` entries. All pairs of an area share one zone. Every image also carries its
position as EXIF GPS tags.

## Splits

| Split | Pairs |
|-------|-------|
{split_rows}

Splits are spatial: the area is divided into {block:.0f} m cells and every cell belongs to one split
as a whole, so that panoramas a few metres apart do not end up on both sides. Pairs in neighbouring
cells of different splits can still show overlapping ground, since an aerial patch covers about
{patch:.0f} m.

## Areas

| Area | Pairs | Train | Val | Test |
|------|-------|-------|-----|------|
{area_rows}

## Capture years

| Year | Pairs |
|------|-------|
{year_rows}

## Notes

- Imagery © Google and its providers. It is not covered by the licence of the collection tool;
  check the Google Maps Platform Terms of Service before redistributing it.
- Positions are those reported by Street View and inherit its GPS error of a few metres.
- The aerial imagery has an unknown acquisition date and may differ in season or year from the
  ground view.
"""


def export(dataset, target, name, zoom, pairs=None, block=500.0, val=0.2, test=0.0, seed=0):
    """Copies the complete pairs of `dataset` to `target` and writes metadata, splits and a card."""
    target = Path(target)
    complete = [p for p in dataset.read_metadata()
                if dataset.path("ground", p).is_file() and dataset.path("aerial", p).is_file()]
    complete.sort(key=lambda panorama: panorama["panoid"])
    if pairs is not None and len(complete) > pairs:
        complete = random.Random(seed).sample(complete, pairs)
    if not complete:
        raise SystemExit(f"{dataset.root} holds no complete pairs")

    assigned = split(complete, block, val, test, seed)
    complete.sort(key=lambda panorama: (panorama["area"], panorama["lat"], panorama["lon"]))

    for view in ("ground", "aerial"):
        (target / view).mkdir(parents=True, exist_ok=True)
    (target / "splits").mkdir(exist_ok=True)

    rows = []
    for panorama in complete:
        for view in ("ground", "aerial"):
            destination = target / view / f"{panorama['panoid']}.jpg"
            if not destination.is_file():
                shutil.copyfile(dataset.path(view, panorama), destination)
        rows.append({**panorama, "split": assigned[panorama["panoid"]],
                     "ground": f"ground/{panorama['panoid']}.jpg",
                     "aerial": f"aerial/{panorama['panoid']}.jpg"})

    def write(path, selected):
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(selected)

    write(target / "metadata.csv", rows)
    parts = [part for part in ("train", "val", "test") if any(row["split"] == part for row in rows)]
    for part in parts:
        write(target / "splits" / f"{part}.csv", [row for row in rows if row["split"] == part])

    arrays = {
        "name": name,
        "panoIds": [row["panoid"] for row in rows],
        "latlng": [[row["lat"], row["lon"]] for row in rows],
        "utm": [[row["utm_x"], row["utm_y"]] for row in rows],
        "utmZone": [row["utm_zone"] for row in rows],
        "area": [row["area"] for row in rows],
    }
    for part in parts:
        arrays[f"{part}Set"] = [index for index, row in enumerate(rows) if row["split"] == part]
    (target / "metadata.json").write_text(json.dumps(arrays), encoding="utf-8")

    first = rows[0]
    ground_size = "{} × {}".format(*Image.open(target / first["ground"]).size)
    aerial_width = Image.open(target / first["aerial"]).size[0]
    resolutions = sorted(aerial.ground_resolution(row["lat"], zoom) for row in rows)
    splits = Counter(row["split"] for row in rows)
    by_area = Counter(row["area"] or "-" for row in rows)
    by_area_split = Counter((row["area"] or "-", row["split"]) for row in rows)
    years = Counter(row["year"] or "unknown" for row in rows)

    (target / "README.md").write_text(CARD.format(
        name=name,
        pairs=len(rows),
        ground_size=ground_size,
        aerial_size=f"{aerial_width} × {aerial_width}",
        gsd=f"{resolutions[0] * 100:.1f}–{resolutions[-1] * 100:.1f} cm/px (Web Mercator zoom {zoom})",
        areas=len(by_area),
        columns="`, `".join(COLUMNS),
        split_rows="\n".join(f"| {part} | {splits[part]} |" for part in parts),
        test_key=", `testSet`" if "test" in parts else "",
        block=block,
        patch=resolutions[-1] * aerial_width,
        area_rows="\n".join(
            f"| {area} | {count} | {by_area_split[area, 'train']} | {by_area_split[area, 'val']} "
            f"| {by_area_split[area, 'test']} |" for area, count in sorted(by_area.items())),
        year_rows="\n".join(f"| {year} | {count} |" for year, count in sorted(years.items(), key=str)),
    ), encoding="utf-8")
    return len(rows), splits
