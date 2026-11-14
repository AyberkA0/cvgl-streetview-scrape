"""Universal Transverse Mercator coordinates on the WGS 84 ellipsoid."""

import math
from collections import defaultdict

A = 6378137.0
F = 1 / 298.257223563
K0 = 0.9996
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)


def zone_of(lon):
    """Number of the 6° zone that holds a longitude."""
    return int((lon + 180) // 6) % 60 + 1


def to_utm(lat, lon, zone):
    """Easting and northing in metres within the given zone (series of Snyder, 1987)."""
    phi = math.radians(lat)
    central = math.radians(zone * 6 - 183)
    n = A / math.sqrt(1 - E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = EP2 * math.cos(phi) ** 2
    a = (math.radians(lon) - central) * math.cos(phi)
    m = A * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * phi
             - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * E2 ** 3 / 3072) * math.sin(6 * phi))

    x = 500000 + K0 * n * (a + (1 - t + c) * a ** 3 / 6
                           + (5 - 18 * t + t ** 2 + 72 * c - 58 * EP2) * a ** 5 / 120)
    y = K0 * (m + n * math.tan(phi) * (a ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a ** 4 / 24
                                       + (61 - 58 * t + t ** 2 + 600 * c - 330 * EP2) * a ** 6 / 720))
    if lat < 0:
        y += 10000000
    return x, y


def assign_utm(panoramas):
    """Adds utm_x, utm_y and utm_zone to every panorama.

    All panoramas of an area share the zone of the area's mean longitude, so
    that distances within an area are plain Euclidean distances even where the
    area straddles a zone boundary.
    """
    groups = defaultdict(list)
    for panorama in panoramas:
        groups[panorama["area"]].append(panorama)
    for group in groups.values():
        zone = zone_of(sum(p["lon"] for p in group) / len(group))
        for panorama in group:
            x, y = to_utm(panorama["lat"], panorama["lon"], zone)
            panorama["utm_x"], panorama["utm_y"] = round(x, 2), round(y, 2)
            panorama["utm_zone"] = f"{zone}{'N' if panorama['lat'] >= 0 else 'S'}"
    return panoramas
