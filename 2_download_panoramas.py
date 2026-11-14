import asyncio
import glob
import io
import json
import os
import traceback

import aiohttp
import yaml
from PIL import Image, ImageChops

import streetview

ZOOM = 3
TILE = 512
ROWS = range(4)
# Panorama size at this zoom level for a given number of tile columns
SIZES = {8: (4096, 2048), 7: (3328, 1664)}
# Panoramas downloaded at the same time
CONCURRENCY = 20


async def fetch_tile(url, session, retries=5):
    """ Returns the tile, or None if it lies outside of the panorama """
    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 400:
                    return None
                assert response.status == 200, f'HTTP {response.status} for {url}'
                return Image.open(io.BytesIO(await response.read()))
        except Exception as e:
            error = e
            await asyncio.sleep(2)
    raise error


def make_strip(tiles, heading, width, height):
    """ Stitches the tiles, turns north to the image centre and crops around the horizon """
    cols = 8 if tiles[7, 0] else 7
    pano_width, pano_height = SIZES[cols]

    strip = Image.new('RGB', (pano_width, pano_height))
    for (x, y), tile in tiles.items():
        if tile:
            strip.paste(tile, (x * TILE, y * TILE))

    strip = ImageChops.offset(strip, round(heading / 360 * pano_width), 0)

    band = height * pano_width / width
    top = pano_height / 2 - band / 2
    return strip.resize((width, height), Image.LANCZOS, box=(0, top, pano_width, top + band))


async def download_panorama(panoid, session, semaphore, width, height):
    async with semaphore:
        try:
            coords = [(x, y) for x in range(8) for y in ROWS]
            images = await asyncio.gather(*[
                fetch_tile(streetview.tile_url(panoid['panoid'], x, y, ZOOM), session)
                for x, y in coords
            ])
            strip = make_strip(dict(zip(coords, images)), panoid['heading'], width, height)
            strip.save(pano_path(panoid), quality=90)
            return True
        except Exception:
            print(f"Failed to create panorama {panoid['panoid']}\n{traceback.format_exc()}")
            return False


def pano_path(panoid):
    return os.path.join('panoramas', f"{panoid['lat']}_{panoid['lon']}_{panoid['panoid']}.jpg")


async def download_loop(panoids, width, height):
    semaphore = asyncio.Semaphore(CONCURRENCY)
    conn = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=conn) as session:
        return await asyncio.gather(*[
            download_panorama(panoid, session, semaphore, width, height) for panoid in panoids
        ])


if __name__ == "__main__":

    with open('config.yaml') as f:
        config = yaml.safe_load(f)['panorama']

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

    os.makedirs('panoramas', exist_ok=True)
    todo = [p for p in panoids if not os.path.isfile(pano_path(p))]
    print(f"Downloading {len(todo)} panoramas")

    results = asyncio.run(download_loop(todo, config['width'], config['height']))
    print(f"Finished: {sum(results)} downloaded, {len(results) - sum(results)} failed")
