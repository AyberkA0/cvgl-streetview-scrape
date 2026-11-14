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
