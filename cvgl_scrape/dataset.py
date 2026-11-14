"""Layout of a dataset directory.

    metadata.csv    one row per panorama
    map.html        panorama positions on a map
    ground/         <panoid>.jpg
    aerial/         <panoid>.jpg

Every image carries the panorama position as EXIF GPS tags and the panorama
identifier as its EXIF image description.
"""

import csv
import json
from pathlib import Path

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from .utm import assign_utm

def gps_exif(lat, lon, description=None):
    """EXIF block holding a WGS 84 position, to be passed to Image.save(exif=...)."""

    def dms(value):
        value = abs(value)
        degrees = int(value)
        minutes = int((value - degrees) * 60)
        seconds = (value - degrees - minutes / 60) * 3600
        return degrees, minutes, IFDRational(round(seconds * 10**6), 10**6)

    exif = Image.Exif()
    if description:
        exif[0x010E] = description                      # ImageDescription
    gps = exif.get_ifd(0x8825)
    gps[0] = b"\x02\x03\x00\x00"                       # GPSVersionID
    gps[1], gps[2] = "N" if lat >= 0 else "S", dms(lat)   # GPSLatitudeRef, GPSLatitude
    gps[3], gps[4] = "E" if lon >= 0 else "W", dms(lon)   # GPSLongitudeRef, GPSLongitude
    gps[18] = "WGS-84"                                    # GPSMapDatum
    return exif


FIELDS = ["panoid", "area", "lat", "lon", "utm_x", "utm_y", "utm_zone", "heading", "year", "month"]

MAP_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Panorama positions</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html, body, #map { height: 100%; margin: 0; }</style>
<div id="map"></div>
<script>
const data = __DATA__;
const map = L.map("map", {preferCanvas: true});
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            {maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
for (const ring of data.rings) L.polygon(ring, {color: "#c0392b", fill: false}).addTo(map);
for (const [lat, lon, radius] of data.circles)
  L.circle([lat, lon], {radius: radius, color: "#c0392b", fill: false}).addTo(map);
for (const [lat, lon, panoid, date] of data.panoramas)
  L.circleMarker([lat, lon], {radius: 3, weight: 1, color: "#1f4e9c"})
   .bindPopup(panoid + (date ? "<br>" + date : "")).addTo(map);
map.fitBounds(data.bounds);
</script>
"""


class Dataset:
    def __init__(self, root):
        self.root = Path(root)
        self.metadata = self.root / "metadata.csv"

    def path(self, view, panorama):
        return self.root / view / f"{panorama['panoid']}.jpg"

    def write_metadata(self, panoramas):
        assign_utm(panoramas)
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.metadata, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(panoramas)

    def read_metadata(self):
        if not self.metadata.is_file():
            raise SystemExit(f"{self.metadata} not found. Run the search stage first.")
        with open(self.metadata, newline="", encoding="utf-8") as file:
            return assign_utm([{
                "panoid": row["panoid"],
                "area": row.get("area") or "",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "heading": float(row["heading"]),
                "year": int(row["year"]) if row["year"] else None,
                "month": int(row["month"]) if row["month"] else None,
            } for row in csv.DictReader(file)])

    def write_map(self, panoramas, areas):
        boxes = [area.bounds() for area in areas]
        south, west = min(box[0] for box in boxes), min(box[1] for box in boxes)
        north, east = max(box[2] for box in boxes), max(box[3] for box in boxes)
        data = {
            "panoramas": [[p["lat"], p["lon"], p["panoid"],
                           f"{p['year']}-{p['month']:02d}" if p["year"] else None] for p in panoramas],
            "rings": [[[lat, lon] for lon, lat in ring] for area in areas for ring in area.rings],
            "circles": [[*area.center, area.radius] for area in areas if area.center],
            "bounds": [[south, west], [north, east]],
        }
        (self.root / "map.html").write_text(MAP_PAGE.replace("__DATA__", json.dumps(data)),
                                            encoding="utf-8")
