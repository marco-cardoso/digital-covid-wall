"""Checks a deployed website against its known-good list (the manifest the deploy recorded).

The manifest lists every file the site's bucket should hold, with its SHA-256, MD5 and size:

    {"site": "dev", "url": "https://dev.covidwall.co.uk", "recorded_at": "2026-11-26T12:00:00Z",
     "deploying_until": null, "files": {"index.html": {"sha256": "...", "md5": "...", "size": 556}, ...}}

Three checks, each returning a list of Problems:

- check_inventory: every object in the bucket (as S3 lists it) against the list: changed, missing, unexpected.
- check_event: one S3 write or delete, as it happens.
- check_live: the site as visitors get it, over HTTPS: the page and everything it loads, the dashboard's data,
  the wall's description, and a rotating sample of the other files. It also flags a page that loads scripts or
  styles from another site, or carries inline scripts.

While a deploy is under way (deploying_until, at most DEPLOY_WINDOW after the list was recorded) files on the list
may be missing or still old; anything not on the list, and anything loaded from elsewhere, is still a problem.

Standard library only, so it also runs outside AWS:

    python checker.py --manifest manifest.json      # checks the live site; exit status 1 on any problem
"""

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

DEPLOY_WINDOW = timedelta(minutes=30)
SAMPLE_SIZE = 20
FETCH_TIMEOUT = 15
USER_AGENT = "covid-wall-integrity-check/1"
# Checked on every run, when the site has them: what visitors see first, and what the deploy changes most.
ALWAYS = ("api/stats", "api/insights", "api/tributes", "wall/wall.json", "favicon.svg", "icons.svg")


@dataclass(frozen=True, order=True)
class Problem:
    kind: str  # changed | missing | unexpected | external | inline-script | unreachable | no-manifest
    path: str
    where: str  # bucket | live site | manifest
    detail: str = ""

    def __str__(self):
        text = {
            "changed": "changed",
            "missing": "missing",
            "unexpected": "not on the known-good list",
            "external": "loads something from another site",
            "inline-script": "has an inline script",
            "unreachable": "could not be fetched",
            "no-manifest": "no known-good list to check against",
        }[self.kind]
        line = f"{self.path or '/'}: {text} ({self.where})"
        return f"{line}: {self.detail}" if self.detail else line


# ---- The known-good list ------------------------------------------------------------------------------------------


def parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_manifest(text):
    manifest = json.loads(text)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict) or not manifest.get("url"):
        raise ValueError("not a site manifest")
    return manifest


def deploying(manifest, now, written_at=None):
    """Whether a deploy is under way: until its stated end, and never longer than DEPLOY_WINDOW after the list
    was written (S3's own time when known, so a list cannot hold the window open for itself)."""
    until = manifest.get("deploying_until")
    if not until:
        return False
    start = written_at or parse_time(manifest["recorded_at"])
    return now < min(parse_time(until), start + DEPLOY_WINDOW)


def etag_md5(etag):
    """The MD5 an S3 ETag stands for; None for a multipart upload, whose ETag is not a plain MD5."""
    etag = (etag or "").strip('"')
    return None if "-" in etag or not etag else etag


# ---- The bucket ---------------------------------------------------------------------------------------------------


def compare_object(key, size, etag, expected):
    if expected is None:
        return Problem("unexpected", key, "bucket")
    md5 = etag_md5(etag)
    if size != expected["size"] or (md5 is not None and md5 != expected["md5"]):
        return Problem("changed", key, "bucket")
    return None


def check_inventory(objects, manifest, in_deploy=False):
    """objects: (key, size, etag) for everything in the bucket."""
    files = manifest["files"]
    problems, seen = [], set()
    for key, size, etag in objects:
        seen.add(key)
        problem = compare_object(key, size, etag, files.get(key))
        if problem and not (in_deploy and problem.kind == "changed"):
            problems.append(problem)
    if not in_deploy:
        problems += [Problem("missing", key, "bucket") for key in files if key not in seen]
    return sorted(problems)


def check_event(change, key, size, etag, manifest, in_deploy=False):
    """change: 'created' or 'deleted'."""
    expected = manifest["files"].get(key)
    if change == "deleted":
        return [] if expected is None or in_deploy else [Problem("missing", key, "bucket", "deleted")]
    problem = compare_object(key, size, etag, expected)
    if problem and not (in_deploy and problem.kind == "changed"):
        return [problem]
    return []


# ---- The live site ------------------------------------------------------------------------------------------------


class _References(HTMLParser):
    """The URLs a page loads (src, href on links, and the like) and how many inline scripts it has."""

    ATTRIBUTES = {"script": "src", "link": "href", "img": "src", "iframe": "src", "source": "src", "embed": "src",
                  "object": "data", "video": "src", "audio": "src"}

    def __init__(self):
        super().__init__()
        self.urls, self.inline_scripts, self._in_script = [], 0, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = self.ATTRIBUTES.get(tag)
        if name and attrs.get(name):
            self.urls.append(attrs[name])
        if tag == "script":
            self._in_script = not attrs.get("src")

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline_scripts += 1
            self._in_script = False

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def page_references(html):
    parser = _References()
    parser.feed(html)
    return parser.urls, parser.inline_scripts


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # verifies the certificate
        return response.read()


def sample(keys, count, turn):
    """`count` keys, a different stretch on each turn, so every file is fetched in time."""
    if not keys:
        return []
    start = (turn * count) % len(keys)
    return [keys[(start + i) % len(keys)] for i in range(min(count, len(keys)))]


def check_live(manifest, get=None, turn=0, in_deploy=False):
    get = get or fetch
    files = manifest["files"]
    base = manifest["url"].rstrip("/") + "/"
    host = urlsplit(base).netloc
    problems, checked = [], set()

    def compare(path):
        checked.add(path)
        try:
            body = get(urljoin(base, path))
        except (urllib.error.URLError, OSError, ValueError) as error:
            problems.append(Problem("unreachable", path, "live site", str(getattr(error, "reason", error))))
            return None
        expected = files.get(path)
        if expected is None:
            problems.append(Problem("unexpected", path, "live site"))
        elif hashlib.sha256(body).hexdigest() != expected["sha256"] and not in_deploy:
            problems.append(Problem("changed", path, "live site"))
        return body

    checked.add("index.html")
    try:
        page = get(base)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return [Problem("unreachable", "", "live site", str(getattr(error, "reason", error)))]
    expected = files.get("index.html")
    if expected is None or (hashlib.sha256(page).hexdigest() != expected["sha256"] and not in_deploy):
        problems.append(Problem("changed", "", "live site", "the home page"))

    urls, inline = page_references(page.decode("utf-8", "replace"))
    if inline:
        problems.append(Problem("inline-script", "", "live site", f"{inline} inline script(s)"))
    for url in urls:
        parts = urlsplit(urljoin(base, url))
        if parts.scheme == "data":
            continue
        if parts.netloc != host:
            problems.append(Problem("external", "", "live site", url))
            continue
        path = parts.path.lstrip("/")
        if path and path not in checked:
            compare(path)

    for path in ALWAYS:
        if path in files and path not in checked:
            compare(path)
    rest = sorted(key for key in files if key not in checked)
    for path in sample(rest, SAMPLE_SIZE, turn):
        compare(path)
    return sorted(problems)


# ---- Outside AWS --------------------------------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a live site against its known-good list.")
    parser.add_argument("--manifest", required=True, help="the manifest JSON file")
    parser.add_argument("--turn", type=int, default=None, help="which sample of files (default: from the clock)")
    args = parser.parse_args(argv)

    with open(args.manifest, encoding="utf-8") as handle:
        manifest = load_manifest(handle.read())
    now = datetime.now(timezone.utc)
    turn = args.turn if args.turn is not None else int(now.timestamp()) // 300
    problems = check_live(manifest, turn=turn, in_deploy=deploying(manifest, now))

    site = manifest.get("site", manifest["url"])
    if problems:
        print(f"{site}: {len(problems)} problem(s) on {manifest['url']}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"{site}: {manifest['url']} matches its known-good list ({len(manifest['files']):,} files on the list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
