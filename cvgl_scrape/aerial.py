"""Satellite patches centred on a position."""

import asyncio
import io
import math

from PIL import Image

from .net import fetch

TILE_URL = "https://mt1.google.com/vt/lyrs=s&x={}&y={}&z={}"
TILE = 256
EQUATOR = 2 * math.pi * 6378137


def pixel_position(lat, lon, zoom):
    """Web Mercator pixel coordinates of a point at the given zoom level."""
    scale = TILE * 2 ** zoom
    x = (lon + 180) / 360 * scale
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    return x, y


def ground_resolution(lat, zoom):
    """Metres per pixel at the given latitude and zoom level."""
    return EQUATOR * math.cos(math.radians(lat)) / (TILE * 2 ** zoom)


async def aerial_view(session, lat, lon, zoom, size):
    """Downloads the north-up `size` x `size` patch centred on the position."""
    x, y = pixel_position(lat, lon, zoom)
    left, top = round(x - size / 2), round(y - size / 2)
    coords = [(tx, ty)
              for tx in range(left // TILE, (left + size - 1) // TILE + 1)
              for ty in range(top // TILE, (top + size - 1) // TILE + 1)]
    bodies = await asyncio.gather(*(
        fetch(session, TILE_URL.format(tx, ty, zoom)) for tx, ty in coords
    ))

    patch = Image.new("RGB", (size, size))
    for (tx, ty), body in zip(coords, bodies):
        patch.paste(Image.open(io.BytesIO(body)), (tx * TILE - left, ty * TILE - top))
    return patch
