"""Regenerate backend/app/hearts.json from the heart-detection manifest.

scripts/extract_hearts.py counts the hearts in every photo and writes build/hearts/manifest.json. The
dashboard only needs the counts per photo, so this keeps those for the photos that are on the wall,
numbered the way the wall numbers them (wall.json), with the day each was taken. Photos the wall leaves
out (close-ups) are dropped, so the totals agree with the wall.

Usage:
    python scripts/import_hearts.py [--manifest build/hearts/manifest.json] [--wall frontend/public/wall/wall.json]
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "backend" / "app" / "hearts.json"


def shot_date(name: str) -> str:
    """'PXL_20230730_084939539.jpg' -> '2023-07-30' ('' when the name carries no date)."""
    match = re.search(r"_(\d{4})(\d{2})(\d{2})_", name)
    return "-".join(match.groups()) if match else ""


def collect_photos(manifest: dict, wall: dict) -> list[dict]:
    """Heart counts per wall photo, in wall order. Photos missing from the manifest count as zero hearts."""
    counted = {p["photo"]: p for p in manifest.get("per_photo", [])}
    photos = []
    for entry in sorted(wall.get("photos", []), key=lambda p: p["number"]):
        found = counted.get(entry["file"], {})
        photos.append(
            {
                "number": entry["number"],
                "date": shot_date(entry["file"]),
                "hearts": found.get("hearts_detected", 0),
                "writing": found.get("hearts_with_writing", 0),
            }
        )
    return photos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=ROOT / "build" / "hearts" / "manifest.json")
    ap.add_argument("--wall", type=Path, default=ROOT / "frontend" / "public" / "wall" / "wall.json")
    ap.add_argument("--out", type=Path, default=OUTPUT)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    wall = json.loads(args.wall.read_text(encoding="utf-8"))
    photos = collect_photos(manifest, wall)
    args.out.write_text(
        json.dumps({"generated": manifest.get("generated", ""), "photos": photos}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{len(photos)} wall photos, {sum(p['hearts'] for p in photos):,} hearts "
        f"({sum(p['writing'] for p in photos):,} with writing) -> {args.out}"
    )


if __name__ == "__main__":
    main()
