# -*- coding: utf-8 -*-
"""
:Module: ``streetview``
:Author: `Adrian Letchford <http://www.dradrian.com>`_
:Organisation: `Warwick Business School <http://www.wbs.ac.uk/>`_, `University of Warwick <http://www.warwick.ac.uk/>`_.


This is a light module for downloading photos from Google street view. The
functions allow you to retrieve current and **old** photos.

The photos on Google street view are panoramas and are refered to as such.
However, you have the option of downloading flat photos, or panoramas.

Retrieving photos is a two step process. First, you must translate GPS
coordinates into panorama ids. The following code retrieves a list of
the closest panoramas giving you their id and date:

>>> import streetview
>>> panoids = streetview.panoids(lat, lon)

You can then use the panorama ids to download photos with the following
function:

>>> streetview.api_download(panoid, heading, flat_dir, key)

"""

import re
import json
from datetime import datetime
import requests
import time
import shutil
import itertools
from PIL import Image
from io import BytesIO
import os

from pprint import pprint

imgx = 26 # Modified image width. Default is 26 which sometimes results in crop.


SEARCH_URL = "https://maps.googleapis.com/$rpc/google.internal.maps.mapsjs.v1.MapsJsInternalService/SingleImageSearch"
SEARCH_HEADERS = {"Content-Type": "application/json+protobuf"}


def search_body(lat, lon, radius=50):
    """
    Builds the request body for Google's internal panorama search. The old
    GET endpoint (GeoPhotoService.SingleImageSearch) was shut down by Google.
    """
    return json.dumps([
        ["apiv3"],
        [[None, None, lat, lon], radius],
        [[None, None, 1], ["en", "US"], None, None, None, None, None, None, [2], None, [[[2, True, 2]]]],
        [[1, 2, 3, 4, 8, 6]],
    ])


def _panoids_data(lat, lon, proxies=None):
    """
    Gets the response of the script on Google's servers that returns the
    closest panoramas (ids) to a give GPS coordinate.
    """
    return requests.post(SEARCH_URL, data=search_body(lat, lon), headers=SEARCH_HEADERS, proxies=proxies)


def panoids(lat, lon, closest=False, disp=False, proxies=None, resp=None):
    """
    Gets the closest panoramas (ids) to the GPS coordinates.
    If the 'closest' boolean parameter is set to true, only the panoramas
    at the closest location will be returned (at all the available dates)
    """
    resp = _panoids_data(lat, lon, proxies)
    return panoids_from_response(resp.text, closest=closest, disp=disp)


def panoids_from_response(text, closest=False, disp=False, proxies=None):
    """
    Gets panoids from response (gotten asynchronously).

    The response lists the matched panorama first, then its neighbours, then
    older panoramas taken at the same spot. Dates are only known for the
    matched panorama and the older ones.
    """
    data = json.loads(text)

    # No panorama near this point: [[5, "generic", "Search returned no images."]]
    if len(data) < 2 or not isinstance(data[1], list):
        return []
    pano = data[1]

    try:
        entries = pano[5][0][3][0]
    except (IndexError, TypeError):
        return []

    pans = []
    for entry in entries:
        try:
            pans.append({
                "panoid": entry[0][1],
                "lat": float(entry[2][0][2]),
                "lon": float(entry[2][0][3]),
                # Compass direction of the image centre in degrees
                "heading": float(entry[2][2][0])})
        except (IndexError, TypeError):
            pans.append(None)

    def set_date(index, date):
        if index < len(pans) and pans[index] and date and 1 <= date[1] <= 12:
            pans[index].update({"year": date[0], "month": date[1]})

    # Date of the matched panorama
    try:
        set_date(0, pano[6][7])
    except (IndexError, TypeError):
        pass

    # Dates of the older panoramas, given as (index into entries, [year, month])
    dated = [0]
    try:
        for item in pano[5][0][8] or []:
            set_date(item[0], item[1])
            dated.append(item[0])
    except (IndexError, TypeError):
        pass

    if closest:
        pans = [pans[i] for i in dated if i < len(pans)]

    pans = [p for p in pans if p]

    # Remove duplicate panoramas
    pans = [p for i, p in enumerate(pans) if p not in pans[:i]]

    if disp:
        for pan in pans:
            print(pan)

    # Sort the pans array
    def func(x):
        if 'year' in x:
            return datetime(year=x['year'], month=x['month'], day=1)
        else:
            return datetime(year=3000, month=1, day=1)
    pans.sort(key=func)

    return pans


TILE_URL = "https://streetviewpixels-pa.googleapis.com/v1/tile?cb_client=apiv3&panoid={0:}&output=tile&x={1:}&y={2:}&zoom={3:}&nbt=1"

# nbt=1 makes Google answer 400 for tiles outside of the panorama instead of
# sending a black tile, which is how the grid of a panorama is detected.
# Tile grids (columns, rows) used at zoom 5, newest cameras first.
# 32x16 = 16384x8192 px, 26x13 = 13312x6656 px
GRIDS = [(32, 16), (26, 13)]


def tile_url(panoid, x, y, zoom=5):
    return TILE_URL.format(panoid, x, y, zoom)


def tiles_info(panoid, grid=(imgx, 13)):
    """
    Generate a list of a panorama's tiles and their position.

    The format is (x, y, filename, fileurl)
    """

    # The tiles positions
    coord = list(itertools.product(range(grid[0]), range(grid[1])))

    tiles = [(x, y, "%s_%dx%d.jpg" % (panoid, x, y), tile_url(panoid, x, y)) for x, y in coord]

    return tiles


def download_tiles(tiles, directory, disp=False):
    """
    Downloads all the tiles in a Google Stree View panorama into a directory.

    Params:
        tiles - the list of tiles. This is generated by tiles_info(panoid).
        directory - the directory to dump the tiles to.
    """

    for i, (x, y, fname, url) in enumerate(tiles):

        if disp and i % 20 == 0:
            print("Image %d (%d)" % (i, len(tiles)))

        # Try to download the image file
        while True:
            try:
                response = requests.get(url, stream=True)
                break
            except requests.ConnectionError:
                print("Connection error. Trying again in 2 seconds.")
                time.sleep(2)

        with open(directory + '/' + fname, 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)
        del response


def stich_tiles(panoid, tiles, directory, final_directory, point=None):
    """
    Stiches all the tiles of a panorama together. The tiles are located in
    `directory'.
    """

    tile_width = 512
    tile_height = 512

    cols = max(t[0] for t in tiles) + 1
    rows = max(t[1] for t in tiles) + 1

    panorama = Image.new('RGB', (cols*tile_width, rows*tile_height))

    for x, y, fname, url in tiles:

        fname = directory + "/" + fname
        tile = Image.open(fname)

        panorama.paste(im=tile, box=(x*tile_width, y*tile_height))

        del tile


    if point == None:
        name = f"{panoid}.jpg"
    else:
         name = f"{point[0]}_{point[1]}_{panoid}.jpg"

    panorama.save(os.path.join(final_directory, name), quality=30)


    del panorama


def delete_tiles(tiles, directory):
    for x, y, fname, url in tiles:
        os.remove(directory + "/" + fname)


def api_download(panoid, heading, flat_dir, key, width=640, height=640,
                 fov=120, pitch=0, extension='jpg', year=2017, fname=None):
    """
    Download an image using the official API. These are not panoramas.

    Params:
        :panoid: the panorama id
        :heading: the heading of the photo. Each photo is taken with a 360
            camera. You need to specify a direction in degrees as the photo
            will only cover a partial region of the panorama. The recommended
            headings to use are 0, 90, 180, or 270.
        :flat_dir: the direction to save the image to.
        :key: your API key.
        :width: downloaded image width (max 640 for non-premium downloads).
        :height: downloaded image height (max 640 for non-premium downloads).
        :fov: image field-of-view.
        :image_format: desired image format.
        :fname: file name

    You can find instructions to obtain an API key here: https://developers.google.com/maps/documentation/streetview/
    """
    if not fname:
        fname = "%s_%s_%s" % (year, panoid, str(heading))
    image_format = extension if extension != 'jpg' else 'jpeg'

    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        # maximum permitted size for free calls
        "size": "%dx%d" % (width, height),
        "fov": fov,
        "pitch": pitch,
        "heading": heading,
        "pano": panoid,
        "key": key
    }

    response = requests.get(url, params=params, stream=True)
    try:
        img = Image.open(BytesIO(response.content))
        filename = '%s/%s.%s' % (flat_dir, fname, extension)
        img.save(filename, image_format)
    except:
        print("Image not found")
        filename = None
    del response
    return filename


def download_flats(panoid, flat_dir, key, width=400, height=300,
                   fov=120, pitch=0, extension='jpg', year=2017):
    for heading in [0, 90, 180, 270]:
        api_download(panoid, heading, flat_dir, key, width, height, fov, pitch, extension, year)
