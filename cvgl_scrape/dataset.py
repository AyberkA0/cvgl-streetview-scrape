"""Layout of a dataset directory.

    metadata.csv    one row per panorama
    map.html        panorama positions on a map
    ground/         <panoid>.jpg
    aerial/         <panoid>.jpg
"""

import csv
import json
from pathlib import Path

FIELDS = ["panoid", "lat", "lon", "heading", "year", "month"]

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
if (data.center) L.circle(data.center, {radius: data.radius, color: "#c0392b", fill: false}).addTo(map);
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
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.metadata, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(panoramas)

    def read_metadata(self):
        if not self.metadata.is_file():
            raise SystemExit(f"{self.metadata} not found. Run the search stage first.")
        with open(self.metadata, newline="", encoding="utf-8") as file:
            return [{
                "panoid": row["panoid"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "heading": float(row["heading"]),
                "year": int(row["year"]) if row["year"] else None,
                "month": int(row["month"]) if row["month"] else None,
            } for row in csv.DictReader(file)]

    def write_map(self, panoramas, area):
        south, west, north, east = area.bounds()
        data = {
            "panoramas": [[p["lat"], p["lon"], p["panoid"],
                           f"{p['year']}-{p['month']:02d}" if p["year"] else None] for p in panoramas],
            "rings": [[[lat, lon] for lon, lat in ring] for ring in area.rings],
            "center": area.center,
            "radius": area.radius,
            "bounds": [[south, west], [north, east]],
        }
        (self.root / "map.html").write_text(MAP_PAGE.replace("__DATA__", json.dumps(data)),
                                            encoding="utf-8")
