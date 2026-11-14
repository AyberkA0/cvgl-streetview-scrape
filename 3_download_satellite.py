import asyncio
import glob
import io
import json
import math
import os
import traceback

import aiohttp
import yaml
from PIL import Image

TILE_URL = "https://mt1.google.com/vt/lyrs=s&x={0:}&y={1:}&z={2:}"
TILE = 256
# Patches downloaded at the same time
CONCURRENCY = 20


def pixel_position(lat, lon, zoom):
    """ Web Mercator pixel coordinates of a point at the given zoom level """
    scale = TILE * 2**zoom
    x = (lon + 180) / 360 * scale
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    return x, y


def ground_resolution(lat, zoom):
    """ Metres per pixel at the given latitude """
    return 2 * math.pi * 6378137 * math.cos(math.radians(lat)) / (TILE * 2**zoom)


async def fetch_tile(url, session, retries=5):
    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                assert response.status == 200, f'HTTP {response.status} for {url}'
                return Image.open(io.BytesIO(await response.read()))
        except Exception as e:
            error = e
            await asyncio.sleep(2)
    raise error


async def download_patch(panoid, session, semaphore, zoom, size):
    """ Saves the patch of the given size centred on the panorama position """
    async with semaphore:
        try:
            x, y = pixel_position(panoid['lat'], panoid['lon'], zoom)
            left, top = round(x - size / 2), round(y - size / 2)
            coords = [(tx, ty)
                      for tx in range(left // TILE, (left + size - 1) // TILE + 1)
                      for ty in range(top // TILE, (top + size - 1) // TILE + 1)]
            tiles = await asyncio.gather(*[
                fetch_tile(TILE_URL.format(tx, ty, zoom), session) for tx, ty in coords
            ])

            patch = Image.new('RGB', (size, size))
            for (tx, ty), tile in zip(coords, tiles):
                patch.paste(tile, (tx * TILE - left, ty * TILE - top))
            patch.save(patch_path(panoid), quality=95)
            return True
        except Exception:
            print(f"Failed to create patch for {panoid['panoid']}\n{traceback.format_exc()}")
            return False


def patch_path(panoid):
    return os.path.join('satellite', f"{panoid['lat']}_{panoid['lon']}_{panoid['panoid']}.jpg")


async def download_loop(panoids, zoom, size):
    semaphore = asyncio.Semaphore(CONCURRENCY)
    conn = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=conn) as session:
        return await asyncio.gather(*[
            download_patch(panoid, session, semaphore, zoom, size) for panoid in panoids
        ])


if __name__ == "__main__":

    with open('config.yaml') as f:
        config = yaml.safe_load(f)
        zoom = config['satellite']['zoom']
        size = config['satellite']['size']
        center = config['center']

    # Load panoids info
    if not glob.glob('panoids*.json'):
        print('No panoids file found')
        exit()
    elif len(glob.glob('panoids*.json')) > 1:
        print('Multiple panoids files found. Please remove files not needed')
        exit()

    with open(glob.glob('panoids*.json')[0], 'r') as f:
        panoids = json.load(f)

    print(f"Loaded {len(panoids)} panoids")
    print(f"Zoom {zoom}: {ground_resolution(center[0], zoom) * 100:.1f} cm per pixel")

    os.makedirs('satellite', exist_ok=True)
    todo = [p for p in panoids if not os.path.isfile(patch_path(p))]
    print(f"Downloading {len(todo)} patches")

    results = asyncio.run(download_loop(todo, zoom, size))
    print(f"Finished: {sum(results)} downloaded, {len(results) - sum(results)} failed")
