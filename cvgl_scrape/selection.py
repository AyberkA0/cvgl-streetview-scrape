"""Selection of panoramas for a dataset and spatial train/val/test splits."""

import math
import random
from collections import defaultdict

METRES_PER_DEGREE = 111_320.0


def cell(lat, lon, size):
    """Index of the `size`-metre grid cell that holds a position."""
    return (math.floor(lat * METRES_PER_DEGREE / size),
            math.floor(lon * METRES_PER_DEGREE * math.cos(math.radians(lat)) / size))


def thin(panoramas, size):
    """Keeps one panorama per `size`-metre cell of each area, preferring the latest capture."""
    best = {}
    for panorama in panoramas:
        key = (panorama["area"], *cell(panorama["lat"], panorama["lon"], size))
        rank = (panorama["year"] or 0, panorama["month"] or 0, panorama["panoid"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, panorama)
    return [panorama for _, panorama in best.values()]


def allocate(available, target):
    """Splits `target` evenly over the areas; what an area cannot supply goes to the others."""
    quota = dict.fromkeys(available, 0)
    remaining = target
    unfilled = set(available)
    while remaining > 0 and unfilled:
        share = max(1, remaining // len(unfilled))
        for name in sorted(unfilled):
            take = min(share, available[name] - quota[name], remaining)
            quota[name] += take
            remaining -= take
        unfilled = {name for name in unfilled if quota[name] < available[name]}
    return quota


def sample(panoramas, target, balance, seed):
    """Draws `target` panoramas at random, evenly over the areas if `balance` is set."""
    rng = random.Random(seed)
    ordered = sorted(panoramas, key=lambda panorama: panorama["panoid"])
    if not balance:
        return rng.sample(ordered, min(target, len(ordered)))

    groups = defaultdict(list)
    for panorama in ordered:
        groups[panorama["area"]].append(panorama)
    quota = allocate({name: len(group) for name, group in groups.items()}, target)
    return [panorama for name in sorted(groups) for panorama in rng.sample(groups[name], quota[name])]


def split(panoramas, block, val, test, seed):
    """Assigns whole `block`-metre cells to train, val or test, so that neighbours stay together.

    Returns {panoid: split name}. `val` and `test` are fractions of the panoramas.
    """
    blocks = defaultdict(list)
    for panorama in panoramas:
        blocks[(panorama["area"], *cell(panorama["lat"], panorama["lon"], block))].append(panorama)

    keys = sorted(blocks)
    random.Random(seed).shuffle(keys)

    assigned, counts = {}, {"test": 0, "val": 0}
    for key in keys:
        if counts["test"] < test * len(panoramas):
            name = "test"
        elif counts["val"] < val * len(panoramas):
            name = "val"
        else:
            name = "train"
        if name in counts:
            counts[name] += len(blocks[key])
        for panorama in blocks[key]:
            assigned[panorama["panoid"]] = name
    return assigned
