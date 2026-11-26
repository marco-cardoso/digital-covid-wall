"""Saves the dashboard's read-only API answers as static JSON, for a site with no backend (dev).

    backend/.venv/bin/python scripts/snapshot_api.py OUT_DIR

Writes OUT_DIR/api/stats, OUT_DIR/api/insights and OUT_DIR/api/tributes, named without an extension so they sit
at the very paths the frontend asks for. They come from the local backend's own endpoint code, reading the local
database (backend/memorial.db, or MEMORIAL_DB_PATH) and the heart counts (backend/app/hearts.json).

Tributes are left out: the only ones so far are the backend's made-up seed examples, which must not appear on a
public site as if they were real. The tribute and candle totals in the stats are zeroed to match.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import DB_PATH  # noqa: E402
from app.main import wall_insights, wall_stats  # noqa: E402


def snapshot(out_dir: Path) -> dict:
    if not Path(DB_PATH).is_file():
        raise SystemExit(f"No database at {DB_PATH}; run the backend once, or set MEMORIAL_DB_PATH.")

    stats = wall_stats().model_dump(mode="json")
    stats.update(tributes=0, candles=0)
    answers = {
        "stats": stats,
        "insights": wall_insights().model_dump(mode="json"),
        "tributes": [],
    }

    api = out_dir / "api"
    api.mkdir(parents=True, exist_ok=True)
    for name, body in answers.items():
        (api / name).write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return answers


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    answers = snapshot(Path(argv[1]))
    hearts = answers["insights"]["hearts"]
    print(
        f"Snapshot: {answers['stats']['names']:,} names, {hearts['total']:,} hearts in {hearts['photos']:,} photos"
        f" ({hearts['with_writing']:,} with writing); tributes left out."
    )
    if not answers["stats"]["names"] or not hearts["total"]:
        print("Warning: no names or no heart counts in the local data; the dashboard will look empty.", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
