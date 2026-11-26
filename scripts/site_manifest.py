"""Builds a site's known-good list: every file the deploy puts in the bucket, with its SHA-256, MD5 and size.

The tamper monitor (terraform/modules/site-monitor) checks the bucket and the live site against it.

    python scripts/site_manifest.py --site dev --url https://dev.covidwall.co.uk \\
        --map frontend/dist/index.html=index.html --map frontend/dist/assets=assets ... \\
        [--deploying-minutes 30] --out manifest.json

--map LOCAL=KEY puts a file at KEY, or every file under a folder at KEY/<its path> (KEY may be empty for the
bucket's root). --exclude drops files by name (shell pattern). --deploying-minutes marks a deploy as under way for
that long: the monitor then expects files on the list to be missing or old for a while.
"""

import argparse
import fnmatch
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHUNK = 1024 * 1024


def digest(path):
    sha256, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            sha256.update(chunk)
            md5.update(chunk)
    return {"sha256": sha256.hexdigest(), "md5": md5.hexdigest(), "size": path.stat().st_size}


def files_for(mapping, excludes):
    local, _, prefix = mapping.partition("=")
    source, prefix = Path(local), prefix.strip("/")
    if source.is_file():
        if not prefix:
            raise SystemExit(f"--map {mapping}: a single file needs a key")
        return {prefix: source}
    if not source.is_dir():
        raise SystemExit(f"--map {mapping}: {local} does not exist")
    found = {}
    for path in sorted(source.rglob("*")):
        if path.is_file() and not any(fnmatch.fnmatch(path.name, pattern) for pattern in excludes):
            key = path.relative_to(source).as_posix()
            found[f"{prefix}/{key}" if prefix else key] = path
    return found


def build(site, url, mappings, excludes=(), deploying_minutes=0, now=None):
    now = now or datetime.now(timezone.utc)
    files = {}
    for mapping in mappings:
        for key, path in files_for(mapping, excludes).items():
            if key in files:
                raise SystemExit(f"{key} is mapped twice")
            files[key] = digest(path)
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    return {
        "site": site,
        "url": url.rstrip("/"),
        "recorded_at": now.strftime(stamp),
        "deploying_until": (now + timedelta(minutes=deploying_minutes)).strftime(stamp) if deploying_minutes else None,
        "files": dict(sorted(files.items())),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--map", action="append", required=True, dest="mappings", metavar="LOCAL=KEY")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--deploying-minutes", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    manifest = build(args.site, args.url, args.mappings, args.exclude, args.deploying_minutes)
    Path(args.out).write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    state = f", deploy window to {manifest['deploying_until']}" if manifest["deploying_until"] else ""
    print(f"Known-good list for {args.site}: {len(manifest['files']):,} files{state}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
