"""Regenerate backend/app/victims.json from the tesseract-project heart JSON files.

Each JSON file carries a top-level `names` list (the OCR'd text found on the
memorial hearts). We collect those names and deduplicate them (case-sensitive,
whitespace-trimmed, preserving first-seen order). The backend loads the result
into an empty `victims` table on startup.

Usage:
    python scripts/import_victims.py --source DIR
"""

import argparse
import glob
import json
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "victims.json"


def collect_names(source: Path) -> list[str]:
    """Return the de-duplicated, ordered list of names from every JSON file."""
    seen: set[str] = set()
    ordered: list[str] = []
    for path in sorted(glob.glob(str(source / "*.json"))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  skipping {path}: {exc}")
            continue
        for raw in data.get("names", []):
            if not raw:
                continue
            name = raw.strip()
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Directory containing the heart *.json files.",
    )
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    if not args.source.is_dir():
        parser.error(f"source directory not found: {args.source}")

    names = collect_names(args.source)
    args.out.write_text(
        json.dumps(names, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(names)} unique names from {args.source} to {args.out}")


if __name__ == "__main__":
    main()
