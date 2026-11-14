"""Command line interface."""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

import yaml

from . import __version__, aerial, streetview
from .area import Area, load_rings
from .dataset import Dataset, gps_exif
from .export import export
from .net import run_all
from .selection import sample, thin

DEFAULTS = {
    "out": "dataset",
    "center": None,
    "radius": None,
    "boundary": None,
    "areas": None,
    "spacing": 40.0,
    "thin": None,
    "target": None,
    "balance": False,
    "seed": 0,
    "ground_size": (1232, 324),
    "aerial_size": 256,
    "zoom": 19,
    "concurrency": 16,
}


def size(text):
    try:
        width, height = (int(part) for part in str(text).lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}")
    return width, height


def load_config(path):
    with open(path, encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    unknown = sorted(set(config) - set(DEFAULTS))
    if unknown:
        raise SystemExit(f"{path}: unknown keys: {', '.join(unknown)}")
    if "ground_size" in config:
        config["ground_size"] = size(config["ground_size"])
    return config


def build_parser(config):
    defaults = {**DEFAULTS, **config}

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", metavar="FILE",
                        help="YAML file with default values for the options")
    common.add_argument("-o", "--out", metavar="DIR", help="dataset directory (default: %(default)s)")
    common.add_argument("--concurrency", type=int, metavar="N",
                        help="panoramas processed at the same time (default: %(default)s)")

    area = argparse.ArgumentParser(add_help=False)
    group = area.add_argument_group("area")
    group.add_argument("--center", type=float, nargs=2, metavar=("LAT", "LON"),
                       help="centre of a circular area in decimal degrees")
    group.add_argument("--radius", type=float, metavar="KM", help="radius of the circular area")
    group.add_argument("--boundary", metavar="GEOJSON",
                       help="polygon; only panoramas inside of it are kept")
    group.add_argument("--areas", metavar="FILE",
                       help="YAML list of named areas, each with a center and radius or a boundary")
    group.add_argument("--spacing", type=float, metavar="M",
                       help="distance between query points in metres (default: %(default)s)")

    group = area.add_argument_group("selection")
    group.add_argument("--thin", type=float, metavar="M",
                       help="keep one panorama per M-metre cell, preferring the latest capture")
    group.add_argument("--target", type=int, metavar="N",
                       help="keep N panoramas chosen at random")
    group.add_argument("--balance", action="store_true", default=None,
                       help="spread --target evenly over the areas")
    group.add_argument("--seed", type=int, help="seed of the random choice (default: %(default)s)")

    limit = argparse.ArgumentParser(add_help=False)
    limit.add_argument("--limit", type=int, metavar="N",
                       help="process only the first N panoramas, e.g. for a trial run")

    ground = argparse.ArgumentParser(add_help=False)
    ground.add_argument_group("ground view").add_argument(
        "--ground-size", type=size, metavar="WxH", help="size in pixels (default: 1232x324)")

    air = argparse.ArgumentParser(add_help=False)
    group = air.add_argument_group("aerial view")
    group.add_argument("--aerial-size", type=int, metavar="PX",
                       help="edge length in pixels (default: %(default)s)")
    group.add_argument("--zoom", type=int,
                       help="Web Mercator zoom level (default: %(default)s)")

    build = argparse.ArgumentParser(add_help=False)
    build.add_argument("--to", metavar="DIR", required=True, help="directory of the compiled dataset")
    build.add_argument("--name", help="dataset name (default: name of the target directory)")
    build.add_argument("--pairs", type=int, metavar="N", help="keep exactly N pairs chosen at random")
    build.add_argument("--block", type=float, default=500.0, metavar="M",
                       help="edge of the cells that are kept together in one split (default: %(default)s)")
    build.add_argument("--val", type=float, default=0.2,
                       help="fraction of validation pairs (default: %(default)s)")
    build.add_argument("--test", type=float, default=0.0,
                       help="fraction of test pairs (default: %(default)s)")
    build.add_argument("--seed", type=int, help="seed of the random choices (default: %(default)s)")

    parser = argparse.ArgumentParser(
        prog="cvgl-scrape",
        description="Collect paired Street View panoramas and satellite patches over an area.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    for name, parents, function, text in [
        ("run", [common, area, limit, ground, air], run, "search, then download both views"),
        ("search", [common, area], search, "list the panoramas inside the area"),
        ("ground", [common, limit, ground], download_ground, "download the ground views"),
        ("aerial", [common, limit, air], download_aerial, "download the aerial views"),
        ("status", [common], status, "show what a dataset directory contains"),
        ("export", [common, build], compile_dataset, "compile the complete pairs into a training-ready dataset"),
    ]:
        command = commands.add_parser(name, parents=parents, help=text, description=text.capitalize() + ".")
        command.set_defaults(function=function, limit=None, **defaults)
    return parser


def make_areas(args):
    """The areas to search as {name: Area}; a single unnamed area unless --areas is given."""
    try:
        if not args.areas:
            return {"": Area(
                center=tuple(args.center) if args.center else None,
                radius=args.radius * 1000 if args.radius else None,
                rings=load_rings(args.boundary) if args.boundary else None,
            )}
        with open(args.areas, encoding="utf-8") as file:
            entries = yaml.safe_load(file)
        return {entry["name"]: Area(
            center=tuple(entry["center"]) if "center" in entry else None,
            radius=entry["radius"] * 1000 if "radius" in entry else None,
            rings=load_rings(entry["boundary"]) if "boundary" in entry else None,
        ) for entry in entries}
    except (ValueError, KeyError) as error:
        raise SystemExit(f"error: {error}")


def report(label, outcomes, errors, present=0):
    line = f"{label}: {outcomes['ok']} done"
    if present:
        line += f", {present} already present"
    if outcomes["unavailable"]:
        line += f", {outcomes['unavailable']} no longer available"
    if outcomes["failed"]:
        line += f", {outcomes['failed']} failed"
    print(line)
    for message in errors[:5]:
        print(f"  {message}", file=sys.stderr)
    if len(errors) > 5:
        print(f"  ... and {len(errors) - 5} more", file=sys.stderr)
    return not outcomes["failed"]


def search(args):
    areas = make_areas(args)
    dataset = Dataset(args.out)
    points = [point for area in areas.values() for point in area.grid(args.spacing)]
    found = {}

    async def worker(session, point):
        for panorama in await streetview.search(session, *point):
            known = found.get(panorama["panoid"])
            if known is None or (known["year"] is None and panorama["year"] is not None):
                found[panorama["panoid"]] = panorama

    outcomes, errors = asyncio.run(run_all(
        points, worker, concurrency=args.concurrency * 4, label="search", unit="pt"))

    panoramas = []
    for panorama in found.values():
        name = next((name for name, area in areas.items()
                     if area.contains(panorama["lat"], panorama["lon"])), None)
        if name is not None:
            panoramas.append({**panorama, "area": name})
    ok = report("search", outcomes, errors)
    print(f"{len(panoramas)} panoramas inside the area")

    if args.thin:
        panoramas = thin(panoramas, args.thin)
        print(f"{len(panoramas)} after keeping one per {args.thin:g} m cell")
    if len(areas) > 1:
        available = Counter(p["area"] for p in panoramas)
        print("available per area: " + ", ".join(f"{name} {available[name]}" for name in areas))
    if args.target:
        panoramas = sample(panoramas, args.target, args.balance, args.seed)
        print(f"{len(panoramas)} chosen at random" + (", balanced over the areas" if args.balance else ""))

    panoramas.sort(key=lambda p: (p["area"], p["lat"], p["lon"]))
    dataset.write_metadata(panoramas)
    dataset.write_map(panoramas, list(areas.values()))

    dated = sum(p["year"] is not None for p in panoramas)
    print(f"{len(panoramas)} panoramas ({dated} with a capture date) listed in {dataset.metadata}")
    return ok


def download(args, view, label, make_image):
    dataset = Dataset(args.out)
    panoramas = dataset.read_metadata()[:args.limit]
    todo = [p for p in panoramas if not dataset.path(view, p).is_file()]
    (dataset.root / view).mkdir(parents=True, exist_ok=True)

    async def worker(session, panorama):
        image = await make_image(session, panorama)
        path = dataset.path(view, panorama)
        partial = path.with_suffix(".part")
        image.save(partial, "JPEG", quality=92,
                   exif=gps_exif(panorama["lat"], panorama["lon"], panorama["panoid"]))
        partial.replace(path)

    outcomes, errors = asyncio.run(run_all(
        todo, worker, concurrency=args.concurrency, label=label, unit="img"))
    return report(label, outcomes, errors, present=len(panoramas) - len(todo))


def download_ground(args):
    width, height = args.ground_size
    try:
        streetview.check_size(width, height)
    except ValueError as error:
        raise SystemExit(f"error: {error}")
    return download(args, "ground", "ground",
                    lambda session, p: streetview.ground_view(session, p, width, height))


def download_aerial(args):
    panoramas = Dataset(args.out).read_metadata()
    if panoramas:
        latitude = sum(p["lat"] for p in panoramas) / len(panoramas)
        print(f"zoom {args.zoom}: {aerial.ground_resolution(latitude, args.zoom) * 100:.1f} cm/px, "
              f"{aerial.ground_resolution(latitude, args.zoom) * args.aerial_size:.1f} m per patch")
    return download(args, "aerial", "aerial",
                    lambda session, p: aerial.aerial_view(session, p["lat"], p["lon"],
                                                          args.zoom, args.aerial_size))


def status(args):
    dataset = Dataset(args.out)
    panoramas = dataset.read_metadata()
    ground = sum(dataset.path("ground", p).is_file() for p in panoramas)
    air = sum(dataset.path("aerial", p).is_file() for p in panoramas)
    pairs = sum(dataset.path("ground", p).is_file() and dataset.path("aerial", p).is_file()
                for p in panoramas)
    print(f"{dataset.root}: {len(panoramas)} panoramas listed, {ground} ground views, "
          f"{air} aerial views, {pairs} complete pairs")
    return True


def compile_dataset(args):
    target = Path(args.to)
    count, splits = export(Dataset(args.out), target, args.name or target.name, args.zoom, pairs=args.pairs,
                           block=args.block, val=args.val, test=args.test, seed=args.seed)
    print(f"{target}: {count} pairs (" + ", ".join(f"{part} {size}" for part, size in sorted(splits.items())) + ")")
    if args.pairs and count < args.pairs:
        print(f"warning: only {count} of the requested {args.pairs} pairs are complete", file=sys.stderr)
    return True


def run(args):
    ok = search(args)
    ok = download_ground(args) and ok
    ok = download_aerial(args) and ok
    status(args)
    return ok


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    first = argparse.ArgumentParser(add_help=False)
    first.add_argument("-c", "--config")
    known, _ = first.parse_known_args(argv)

    args = build_parser(load_config(known.config) if known.config else {}).parse_args(argv)
    try:
        return 0 if args.function(args) else 1
    except KeyboardInterrupt:
        print("\ninterrupted; run the same command again to resume", file=sys.stderr)
        return 130
