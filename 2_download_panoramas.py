import asyncio
import json
import os
import traceback
import glob
import shutil
import aiohttp

import streetview

# Downloading stops when less than this much disk space is left
MIN_FREE_GB = 20


async def get_grid(panoid, session):
    """ Finds out how many tiles the panorama has, as this depends on the camera used """
    for cols, rows in streetview.GRIDS:
        url = streetview.tile_url(panoid, cols - 1, rows - 1)
        async with session.get(url) as response:
            if response.status == 200:
                return cols, rows
    raise Exception(f'No full resolution tiles available for {panoid}')


async def download_tiles_async(tiles, directory, session, retries=5):
    """ Downloads all the tiles in a Google Stree View panorama into a directory. """

    for i, (x, y, fname, url) in enumerate(tiles):
        # Try to download the image file
        for attempt in range(retries):
            try:
                async with session.get(url) as response:
                    assert response.status == 200, f'HTTP {response.status} for {url}'
                    content = await response.read()
                    with open(directory + '/' + fname, 'wb') as out_file:
                        out_file.write(content)
                    break
            except Exception as e:
                error = e
                await asyncio.sleep(2)
        else:
            raise error


async def download_panorama(panoid,
                            session=None,
                            tile_diretory='tiles',
                            pano_directory='panoramas'):
    """ 
    Downloads a panorama from latitude and longitude
    Heavily IO bound (~98%), ~40s per panorama without using asyncio.
    """
    if not os.path.isdir(tile_diretory):
        os.makedirs(tile_diretory)
    if not os.path.isdir(pano_directory):
        os.makedirs(pano_directory)

    try:
        grid = await get_grid(panoid['panoid'], session)
        x = streetview.tiles_info(panoid['panoid'], grid)
        await download_tiles_async(x, tile_diretory, session)
        streetview.stich_tiles(panoid['panoid'],
                               x,
                               tile_diretory,
                               pano_directory,
                               point=(panoid['lat'], panoid['lon']))
        streetview.delete_tiles(x, tile_diretory)

    except:
        print(f'Failed to create panorama\n{traceback.format_exc()}')


def panoid_created(panoid):
    """ Checks if the panorama was already created """
    file = f"{panoid['lat']}_{panoid['lon']}_{panoid['panoid']}.jpg"
    return os.path.isfile(os.path.join('panoramas', file))


async def download_loop(panoids, pmax):
    """ Main download loop """
    conn = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=conn,
                                     auto_decompress=False) as session:
        try:
            await asyncio.gather(*[
                download_panorama(panoid, session=session)
                for panoid in panoids[:pmax] if not panoid_created(panoid)
            ])
        except:
            print(traceback.format_exc())


if __name__ == "__main__":

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

    # Download panorama in batches of 100
    i = 0
    while True:
        i += 1
        free_gb = shutil.disk_usage('.').free / 1024**3
        if free_gb < MIN_FREE_GB:
            print(f'Stopping: only {free_gb:.1f} GB of disk space left')
            break
        print(f'Running the next batch: {(i-1)*100+1} → {i*100}')
        asyncio.run(download_loop(panoids, 100 * i))
        if 100 * i > len(panoids):
            break
