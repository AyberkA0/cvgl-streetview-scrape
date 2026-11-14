"""Street View panorama search and ground-view extraction."""

import asyncio
import io
import json
import math

from PIL import Image, ImageChops

from .net import NotFound, fetch

SEARCH_URL = ("https://maps.googleapis.com/$rpc/google.internal.maps.mapsjs.v1."
              "MapsJsInternalService/SingleImageSearch")
TILE_URL = ("https://streetviewpixels-pa.googleapis.com/v1/tile"
            "?cb_client=apiv3&panoid={}&output=tile&x={}&y={}&zoom={}&nbt=1")

# Tiles are fetched at this zoom level. The equirectangular image then measures
# 4096 x 2048 px (8 tile columns), or 3328 x 1664 px (7 columns) for older cameras.
ZOOM = 3
TILE = 512
SIZES = {8: (4096, 2048), 7: (3328, 1664)}
MAX_WIDTH = 3328


def parse_search(text):
    """Extracts the panoramas listed in a search response.

    The response holds the panorama nearest to the query point, its neighbours
    and the older captures of the same position. Capture dates are reported
    for the nearest panorama and the older captures only.
    """
    data = json.loads(text)
    try:
        nearest = data[1]
        entries = nearest[5][0][3][0]
    except (IndexError, TypeError):
        return []

    dates = {}
    try:
        dates[0] = nearest[6][7]
        for item in nearest[5][0][8] or []:
            dates[item[0]] = item[1]
    except (IndexError, TypeError):
        pass

    panoramas = []
    for index, entry in enumerate(entries):
        try:
            panorama = {
                "panoid": entry[0][1],
                "lat": float(entry[2][0][2]),
                "lon": float(entry[2][0][3]),
                "heading": float(entry[2][2][0]),
                "year": None,
                "month": None,
            }
        except (IndexError, TypeError):
            continue
        date = dates.get(index)
        if date and len(date) >= 2:
            panorama["year"], panorama["month"] = date[0], date[1]
        panoramas.append(panorama)
    return panoramas


async def search(session, lat, lon, radius=50):
    """Panoramas around a point: the nearest one within `radius` metres and its relatives."""
    payload = json.dumps([
        ["apiv3"],
        [[None, None, lat, lon], radius],
        [[None, None, 1], ["en", "US"], None, None, None, None, None, None, [2], None, [[[2, True, 2]]]],
        [[1, 2, 3, 4, 8, 6]],
    ])
    body = await fetch(session, SEARCH_URL, method="POST", data=payload,
                       headers={"Content-Type": "application/json+protobuf"})
    return parse_search(body.decode("utf-8"))


def check_size(width, height):
    if width > MAX_WIDTH:
        raise ValueError(f"ground view width must not exceed {MAX_WIDTH} px")
    if height * 2 > width:
        raise ValueError("ground view height must not exceed half of its width")


def band(pano_size, width, height):
    """Top and bottom row of the horizon-centred band with the output aspect ratio."""
    pano_width, pano_height = pano_size
    extent = height * pano_width / width
    top = (pano_height - extent) / 2
    return top, top + extent


def tile_rows(width, height):
    """Tile rows that intersect the band for either camera generation."""
    rows = set()
    for size in SIZES.values():
        top, bottom = band(size, width, height)
        rows.update(range(int(top // TILE), math.ceil(bottom / TILE)))
    return sorted(rows)


def build_strip(tiles, heading, width, height):
    """Assembles the ground view from a dict of {(x, y): tile image or None}.

    The panorama is shifted so that north falls on the centre column, cropped
    around the horizon and resampled to `width` x `height`.
    """
    columns = 8 if any(tile for (x, _), tile in tiles.items() if x == 7) else 7
    size = SIZES[columns]

    canvas = Image.new("RGB", size)
    for (x, y), tile in tiles.items():
        if tile:
            canvas.paste(tile, (x * TILE, y * TILE))

    canvas = ImageChops.offset(canvas, round(heading / 360 * size[0]), 0)
    top, bottom = band(size, width, height)
    return canvas.resize((width, height), Image.LANCZOS, box=(0, top, size[0], bottom))


async def ground_view(session, panorama, width, height):
    """Downloads a panorama and returns its ground view. Raises NotFound if it is gone."""
    coords = [(x, y) for x in range(8) for y in tile_rows(width, height)]
    bodies = await asyncio.gather(*(
        fetch(session, TILE_URL.format(panorama["panoid"], x, y, ZOOM), absent=(400,))
        for x, y in coords
    ))
    if not any(bodies):
        raise NotFound(panorama["panoid"])

    tiles = {xy: Image.open(io.BytesIO(body)) if body else None for xy, body in zip(coords, bodies)}
    return build_strip(tiles, panorama["heading"], width, height)
