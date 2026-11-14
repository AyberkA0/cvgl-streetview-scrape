"""Area of interest: a circle, a polygon, or the intersection of both."""

import json
import math

EARTH_RADIUS = 6371008.8
METRES_PER_DEGREE = math.pi * EARTH_RADIUS / 180


def distance(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((phi2 - phi1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS * math.asin(math.sqrt(a))


def load_rings(path):
    """Reads the outer rings of the polygons in a GeoJSON file as lists of (lon, lat)."""
    with open(path, encoding="utf-8") as file:
        data = json.load(file)

    geometries = [feature["geometry"] for feature in data["features"]] \
        if data["type"] == "FeatureCollection" else [data.get("geometry", data)]

    rings = []
    for geometry in geometries:
        if geometry["type"] == "Polygon":
            rings.append(geometry["coordinates"][0])
        elif geometry["type"] == "MultiPolygon":
            rings.extend(polygon[0] for polygon in geometry["coordinates"])
        else:
            raise ValueError(f"{path}: unsupported geometry type {geometry['type']}")
    return rings


def in_ring(lat, lon, ring):
    """Ray casting test of a point against a closed ring of (lon, lat)."""
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


class Area:
    def __init__(self, center=None, radius=None, rings=None):
        """`center` is (lat, lon), `radius` is in metres, `rings` come from load_rings."""
        if (center is None) != (radius is None):
            raise ValueError("center and radius must be given together")
        if center is None and not rings:
            raise ValueError("give a center and radius, a boundary, or both")
        self.center, self.radius, self.rings = center, radius, rings or []

    def contains(self, lat, lon):
        if self.center and distance(lat, lon, *self.center) > self.radius:
            return False
        if self.rings and not any(in_ring(lat, lon, ring) for ring in self.rings):
            return False
        return True

    def bounds(self):
        """Bounding box as (south, west, north, east)."""
        if self.rings:
            lons = [x for ring in self.rings for x, _ in ring]
            lats = [y for ring in self.rings for _, y in ring]
            return min(lats), min(lons), max(lats), max(lons)
        lat, lon = self.center
        dlat = self.radius / METRES_PER_DEGREE
        dlon = dlat / math.cos(math.radians(lat))
        return lat - dlat, lon - dlon, lat + dlat, lon + dlon

    def grid(self, spacing):
        """Query points every `spacing` metres over the bounding box.

        With a circle, points outside of it are left out. Points outside of a
        polygon are kept, since a panorama close to them can still lie inside.
        """
        south, west, north, east = self.bounds()
        dlat = spacing / METRES_PER_DEGREE
        dlon = dlat / math.cos(math.radians((south + north) / 2))
        rows = math.ceil((north - south) / dlat) + 1
        cols = math.ceil((east - west) / dlon) + 1

        points = [(south + i * dlat, west + j * dlon) for i in range(rows) for j in range(cols)]
        if self.center:
            points = [p for p in points if distance(*p, *self.center) <= self.radius + spacing]
        return points
