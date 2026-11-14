import json

import pytest
from PIL import Image

from cvgl_scrape import aerial, streetview
from cvgl_scrape.area import Area, distance, in_ring
from cvgl_scrape.cli import load_config, main

SQUARE = [[32.0, 41.0], [32.1, 41.0], [32.1, 41.1], [32.0, 41.1], [32.0, 41.0]]


def test_distance_of_one_degree_of_latitude():
    assert distance(41.0, 32.0, 42.0, 32.0) == pytest.approx(111195, rel=1e-3)


def test_point_in_ring():
    assert in_ring(41.05, 32.05, SQUARE)
    assert not in_ring(41.05, 32.2, SQUARE)


def test_area_combines_circle_and_polygon():
    area = Area(center=(41.0, 32.0), radius=1000, rings=[SQUARE])
    assert area.contains(41.005, 32.005)
    assert not area.contains(40.995, 32.005)   # inside the circle, outside the polygon
    assert not area.contains(41.05, 32.05)     # inside the polygon, outside the circle


def test_area_needs_a_shape():
    with pytest.raises(ValueError):
        Area()
    with pytest.raises(ValueError):
        Area(center=(41.0, 32.0))


def test_grid_spacing_and_coverage():
    area = Area(center=(41.2, 32.6), radius=500)
    points = area.grid(50)
    assert distance(*points[0], *points[1]) == pytest.approx(50, rel=0.02)
    # Roughly the number of 50 m cells in a circle of 550 m
    assert 300 < len(points) < 480


def test_pixel_position_and_resolution():
    assert aerial.pixel_position(0, 0, 0) == pytest.approx((128, 128))
    assert aerial.ground_resolution(0, 0) == pytest.approx(156543.03, rel=1e-6)
    assert aerial.ground_resolution(41.2, 19) == pytest.approx(0.2247, abs=1e-4)


def entry(panoid, lat, lon, heading):
    return [[2, panoid], None, [[None, None, lat, lon], [100.0], [heading, 90.0, 0.0]]]


def test_parse_search():
    entries = [entry("a", 41.0, 32.0, 10.0), entry("b", 41.1, 32.1, 20.0), entry("c", 41.0, 32.0, 30.0)]
    nearest = [None] * 7
    nearest[5] = [[None, None, None, [entries], None, None, None, None, [[2, [2015, 6]]]]]
    nearest[6] = [None] * 7 + [[2023, 9]]
    panoramas = streetview.parse_search(json.dumps([[0], nearest]))

    assert [p["panoid"] for p in panoramas] == ["a", "b", "c"]
    assert (panoramas[0]["year"], panoramas[0]["month"]) == (2023, 9)
    assert panoramas[1]["year"] is None
    assert (panoramas[2]["year"], panoramas[2]["heading"]) == (2015, 30.0)


def test_parse_search_without_result():
    assert streetview.parse_search('[[5,"generic","Search returned no images."]]') == []


def test_tile_rows():
    assert streetview.tile_rows(1232, 224) == [1, 2]
    assert streetview.tile_rows(1232, 324) == [0, 1, 2, 3]


@pytest.mark.parametrize("columns", [7, 8])
def test_build_strip_turns_north_to_the_centre(columns):
    width, height = streetview.SIZES[columns]
    heading = 90
    # The image centre looks east, so north lies a quarter turn to its left
    north = width // 2 - width * heading // 360
    pano = Image.new("RGB", (8 * 512, 4 * 512))
    pano.paste((255, 0, 0), (north - 20, 0, north + 20, height))
    pano.paste((0, 0, 255), (0, height // 2 - 10, width, height // 2 + 10))

    tiles = {(x, y): pano.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)) if x < columns else None
             for x in range(8) for y in range(4)}
    strip = streetview.build_strip(tiles, heading, 1232, 324)

    assert strip.size == (1232, 324)
    red, _, _ = strip.getpixel((616, 40))
    assert red > 200                                  # north marker at the centre column
    assert strip.getpixel((100, 162))[2] > 200        # horizon at the centre row


def test_check_size():
    streetview.check_size(1232, 324)
    with pytest.raises(ValueError):
        streetview.check_size(1232, 700)
    with pytest.raises(ValueError):
        streetview.check_size(4000, 500)


def test_config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ground_size: 616x162\nzoom: 18\n")
    assert load_config(path) == {"ground_size": (616, 162), "zoom": 18}

    path.write_text("zom: 18\n")
    with pytest.raises(SystemExit):
        load_config(path)


def test_status_of_missing_dataset(tmp_path):
    with pytest.raises(SystemExit):
        main(["status", "--out", str(tmp_path)])


def pano(panoid, lat, lon, area="a", year=None):
    return {"panoid": panoid, "area": area, "lat": lat, "lon": lon, "heading": 0.0,
            "year": year, "month": 1 if year else None}


def test_thin_keeps_latest_capture_per_cell():
    from cvgl_scrape.selection import thin
    kept = thin([pano("old", 41.00001, 32.00001, year=2015), pano("new", 41.00002, 32.00002, year=2023),
                 pano("far", 41.01, 32.0)], 10)
    assert sorted(p["panoid"] for p in kept) == ["far", "new"]


def test_allocate_redistributes_shortfall():
    from cvgl_scrape.selection import allocate
    assert allocate({"a": 10, "b": 100, "c": 100}, 90) == {"a": 10, "b": 40, "c": 40}
    assert allocate({"a": 5, "b": 5}, 90) == {"a": 5, "b": 5}


def test_sample_is_balanced_and_repeatable():
    from collections import Counter
    from cvgl_scrape.selection import sample
    panoramas = [pano(f"a{i}", 41 + i * 1e-4, 32) for i in range(50)] + \
                [pano(f"b{i}", 40 + i * 1e-4, 30, area="b") for i in range(10)]
    chosen = sample(panoramas, 30, True, 0)
    assert Counter(p["area"] for p in chosen) == {"a": 20, "b": 10}
    assert chosen == sample(list(reversed(panoramas)), 30, True, 0)


def test_split_keeps_blocks_together():
    from collections import Counter
    from cvgl_scrape.selection import cell, split
    panoramas = [pano(f"p{i}_{j}", 41 + i * 0.002, 32 + j * 0.0001) for i in range(40) for j in range(25)]
    assigned = split(panoramas, 200, 0.1, 0.1, 0)
    counts = Counter(assigned.values())
    assert 80 <= counts["test"] <= 150 and 80 <= counts["val"] <= 150
    by_block = {}
    for p in panoramas:
        by_block.setdefault(cell(p["lat"], p["lon"], 200), set()).add(assigned[p["panoid"]])
    assert all(len(names) == 1 for names in by_block.values())


def test_export(tmp_path):
    import csv
    from cvgl_scrape.dataset import Dataset
    from cvgl_scrape.export import export
    dataset = Dataset(tmp_path / "raw")
    panoramas = [pano(f"p{i}", 41 + i * 0.01, 32, year=2020) for i in range(12)]
    dataset.write_metadata(panoramas)
    for view, size in (("ground", (1232, 324)), ("aerial", (256, 256))):
        (dataset.root / view).mkdir()
        for p in panoramas[:10]:           # two panoramas stay incomplete
            Image.new("RGB", size).save(dataset.path(view, p))

    count, splits = export(dataset, tmp_path / "out", "DEMO", 19, pairs=8, block=500, val=0.25, test=0.25)
    rows = list(csv.DictReader(open(tmp_path / "out" / "metadata.csv")))
    assert count == len(rows) == 8 and sum(splits.values()) == 8
    assert all((tmp_path / "out" / row["ground"]).is_file() and (tmp_path / "out" / row["aerial"]).is_file()
               for row in rows)
    assert len(list((tmp_path / "out" / "ground").iterdir())) == 8
    assert "| Pairs | 8 |" in (tmp_path / "out" / "README.md").read_text(encoding="utf-8")

    import json
    arrays = json.loads((tmp_path / "out" / "metadata.json").read_text())
    assert arrays["panoIds"] == [row["panoid"] for row in rows]
    assert sorted(arrays["trainSet"] + arrays["valSet"] + arrays["testSet"]) == list(range(8))
    assert all(rows[i]["split"] == "val" for i in arrays["valSet"])
    assert arrays["latlng"][0] == [float(rows[0]["lat"]), float(rows[0]["lon"])]
    assert arrays["utm"][0] == [float(rows[0]["utm_x"]), float(rows[0]["utm_y"])]
    assert arrays["utmZone"][0] == "36N"


def test_utm_reference_point():
    from cvgl_scrape.utm import to_utm, zone_of
    # CN Tower, 43°38'33.24"N 79°23'13.7"W: zone 17, 630084 m E, 4833438 m N
    lat, lon = 43 + 38 / 60 + 33.24 / 3600, -(79 + 23 / 60 + 13.7 / 3600)
    assert zone_of(lon) == 17
    x, y = to_utm(lat, lon, 17)
    assert x == pytest.approx(630084, abs=1) and y == pytest.approx(4833438, abs=1)
    assert to_utm(41.0, 33.0, 36)[0] == pytest.approx(500000)


def test_utm_distance_matches_great_circle():
    from cvgl_scrape.utm import assign_utm
    a, b = assign_utm([pano("a", 41.2000, 32.6270), pano("b", 41.2040, 32.6330)])
    planar = ((a["utm_x"] - b["utm_x"]) ** 2 + (a["utm_y"] - b["utm_y"]) ** 2) ** 0.5
    # UTM is scaled by 0.9996 on the central meridian; the two agree within 0.1 %
    assert planar == pytest.approx(distance(41.2000, 32.6270, 41.2040, 32.6330), rel=1e-3)
    assert a["utm_zone"] == b["utm_zone"] == "36N"


def test_gps_exif_round_trip(tmp_path):
    from cvgl_scrape.dataset import gps_exif
    path = tmp_path / "image.jpg"
    Image.new("RGB", (8, 8)).save(path, "JPEG", exif=gps_exif(41.2074567, -32.6564321, "abc"))
    exif = Image.open(path).getexif()
    gps = exif.get_ifd(0x8825)

    def degrees(parts):
        return float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600

    assert exif[0x010E] == "abc"
    assert (gps[1], gps[3]) == ("N", "W")
    assert degrees(gps[2]) == pytest.approx(41.2074567, abs=1e-8)
    assert degrees(gps[4]) == pytest.approx(32.6564321, abs=1e-8)
