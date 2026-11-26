"""Tests for the integrity checker. No network: the site is a dict of paths to bodies.

    backend/.venv/bin/python -m pytest terraform/modules/site-monitor/lambda
"""

import hashlib
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

import checker
from checker import Problem

URL = "https://dev.example.org"
PAGE = (b'<!doctype html><html><head><link rel="icon" href="/favicon.svg">'
        b'<script type="module" crossorigin src="/assets/app.js"></script>'
        b'<link rel="stylesheet" href="/assets/app.css"></head><body><div id="root"></div></body></html>')
SITE = {
    "index.html": PAGE,
    "favicon.svg": b"<svg/>",
    "assets/app.js": b"console.log('wall')",
    "assets/app.css": b"body{}",
    "api/stats": b'{"names":1}',
    "wall/wall.json": b'{"dzi":"/wall/w.dzi"}',
    "wall/w_files/0/0_0.jpg": b"tile",
}


def entry(body):
    return {"sha256": hashlib.sha256(body).hexdigest(), "md5": hashlib.md5(body).hexdigest(), "size": len(body)}


def manifest(**changes):
    value = {"site": "dev", "url": URL, "recorded_at": "2026-11-26T12:00:00Z", "deploying_until": None,
             "files": {path: entry(body) for path, body in SITE.items()}}
    value.update(changes)
    return value


def bucket(site=SITE):
    return [(key, len(body), f'"{hashlib.md5(body).hexdigest()}"') for key, body in site.items()]


def server(site=SITE, broken=()):
    fetched = []

    def get(url):
        path = url[len(URL) + 1:]
        fetched.append(path)
        if path in broken:
            raise urllib.error.URLError("connection refused")
        # like CloudFront here: an unknown path is answered with the app's page
        return site.get(path or "index.html", site["index.html"])

    get.fetched = fetched
    return get


# ---- the list -----------------------------------------------------------------------------------------------------


def test_a_manifest_must_name_a_site_and_its_files():
    assert checker.load_manifest(json.dumps(manifest()))["url"] == URL
    with pytest.raises(ValueError):
        checker.load_manifest('{"files": {}}')
    with pytest.raises(ValueError):
        checker.load_manifest("[]")


def test_a_deploy_window_ends_when_it_says_and_never_after_half_an_hour():
    start = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    m = manifest(deploying_until="2026-11-26T12:20:00Z")
    assert checker.deploying(m, start + timedelta(minutes=10))
    assert not checker.deploying(m, start + timedelta(minutes=21))
    # a list cannot keep the window open for itself
    long = manifest(deploying_until="2027-01-01T00:00:00Z")
    assert checker.deploying(long, start + timedelta(minutes=29))
    assert not checker.deploying(long, start + timedelta(minutes=31))
    # S3's own time for the write wins over what the list says about itself
    assert not checker.deploying(long, start + timedelta(minutes=5), written_at=start - timedelta(hours=1))
    assert not checker.deploying(manifest(), start)


def test_an_etag_is_an_md5_unless_the_upload_was_multipart():
    assert checker.etag_md5('"abc"') == "abc"
    assert checker.etag_md5('"abc-3"') is None
    assert checker.etag_md5("") is None


# ---- the bucket ---------------------------------------------------------------------------------------------------


def test_a_bucket_that_matches_has_no_problems():
    assert checker.check_inventory(bucket(), manifest()) == []


def test_the_bucket_check_finds_changed_missing_and_unexpected_files():
    site = dict(SITE)
    site["index.html"] = b"<h1>hacked</h1>"
    del site["api/stats"]
    site["evil.js"] = b"alert(1)"

    assert checker.check_inventory(bucket(site), manifest()) == [
        Problem("changed", "index.html", "bucket"),
        Problem("missing", "api/stats", "bucket"),
        Problem("unexpected", "evil.js", "bucket"),
    ]


def test_a_same_size_change_is_found_by_its_md5_and_a_multipart_one_by_its_size():
    same_size = [(k, s, '"00000000000000000000000000000000"' if k == "favicon.svg" else e) for k, s, e in bucket()]
    assert checker.check_inventory(same_size, manifest()) == [Problem("changed", "favicon.svg", "bucket")]
    multipart = [(k, s, '"abc-2"') for k, s, _ in bucket()]
    assert checker.check_inventory(multipart, manifest()) == []


def test_during_a_deploy_old_and_missing_files_are_expected_but_strangers_are_not():
    site = dict(SITE)
    site["index.html"] = b"the previous build"
    del site["assets/app.js"]
    site["evil.js"] = b"alert(1)"

    assert checker.check_inventory(bucket(site), manifest(), in_deploy=True) == [Problem("unexpected", "evil.js", "bucket")]


def test_one_write_or_delete_is_checked_as_it_happens():
    m = manifest()
    body = SITE["index.html"]
    md5 = f'"{hashlib.md5(body).hexdigest()}"'
    assert checker.check_event("created", "index.html", len(body), md5, m) == []
    assert checker.check_event("created", "index.html", 10, '"x"', m) == [Problem("changed", "index.html", "bucket")]
    assert checker.check_event("created", "index.html", 10, '"x"', m, in_deploy=True) == []
    assert checker.check_event("created", "x.html", 1, '"x"', m, in_deploy=True) == [Problem("unexpected", "x.html", "bucket")]
    assert checker.check_event("deleted", "index.html", None, None, m) == [Problem("missing", "index.html", "bucket", "deleted")]
    assert checker.check_event("deleted", "index.html", None, None, m, in_deploy=True) == []
    assert checker.check_event("deleted", "old.js", None, None, m) == []  # gone, and never on the list


# ---- the live site ------------------------------------------------------------------------------------------------


def test_a_live_site_that_matches_has_no_problems_and_everything_it_loads_is_fetched():
    get = server()
    assert checker.check_live(manifest(), get=get) == []
    assert {"", "assets/app.js", "assets/app.css", "favicon.svg", "api/stats", "wall/wall.json"} <= set(get.fetched)


def test_a_defaced_home_page_is_found():
    site = {**SITE, "index.html": b"<h1>Hacked</h1>"}
    assert checker.check_live(manifest(), get=server(site)) == [Problem("changed", "", "live site", "the home page")]


def test_a_changed_bundle_or_data_file_is_found():
    site = {**SITE, "assets/app.js": b"steal()", "api/stats": b'{"names":0}'}
    assert checker.check_live(manifest(), get=server(site)) == [
        Problem("changed", "api/stats", "live site"),
        Problem("changed", "assets/app.js", "live site"),
    ]


def test_a_page_that_loads_from_elsewhere_or_runs_inline_code_is_flagged_even_mid_deploy():
    page = PAGE.replace(b"</head>", b'<script src="https://evil.example/x.js"></script><script>steal()</script>'
                                    b'<img src="data:image/png;base64,AAAA"></head>')
    site = {**SITE, "index.html": page}
    m = manifest(files={**manifest()["files"], "index.html": entry(page)})
    assert checker.check_live(m, get=server(site), in_deploy=True) == [
        Problem("external", "", "live site", "https://evil.example/x.js"),
        Problem("inline-script", "", "live site", "1 inline script(s)"),
    ]


def test_a_page_that_loads_a_file_not_on_the_list_is_flagged():
    page = PAGE.replace(b"/assets/app.css", b"/assets/other.css")
    m = manifest(files={**manifest()["files"], "index.html": entry(page)})
    problems = checker.check_live(m, get=server({**SITE, "index.html": page}))
    assert Problem("unexpected", "assets/other.css", "live site") in problems


def test_an_unreachable_site_or_file_is_reported():
    def down(url):
        raise urllib.error.URLError("certificate verify failed")

    assert checker.check_live(manifest(), get=down) == [Problem("unreachable", "", "live site", "certificate verify failed")]
    problems = checker.check_live(manifest(), get=server(broken={"api/stats"}))
    assert problems == [Problem("unreachable", "api/stats", "live site", "connection refused")]


def test_a_missing_page_served_as_the_app_page_counts_as_changed():
    site = {k: v for k, v in SITE.items() if k != "wall/wall.json"}
    assert checker.check_live(manifest(), get=server(site)) == [Problem("changed", "wall/wall.json", "live site")]


def test_the_sample_walks_through_every_file_in_turn():
    keys = [f"k{i}" for i in range(7)]
    seen = set()
    for turn in range(4):
        seen.update(checker.sample(keys, 2, turn))
    assert seen == set(keys)
    assert checker.sample([], 2, 0) == []
    assert checker.sample(["a"], 5, 3) == ["a"]


def test_problems_read_as_sentences():
    assert str(Problem("changed", "index.html", "bucket")) == "index.html: changed (bucket)"
    assert str(Problem("external", "", "live site", "https://x")) == "/: loads something from another site (live site): https://x"


# ---- run from the command line (GitHub Actions) ------------------------------------------------------------------


def test_the_command_line_exits_1_with_the_problems_listed(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()))
    monkeypatch.setattr(checker, "fetch", server({**SITE, "index.html": b"hacked"}))

    assert checker.main(["--manifest", str(path), "--turn", "0"]) == 1
    out = capsys.readouterr().out
    assert "dev: 1 problem(s) on https://dev.example.org" in out
    assert "/: changed (live site): the home page" in out


def test_the_command_line_exits_0_when_all_is_well(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()))
    monkeypatch.setattr(checker, "fetch", server())

    assert checker.main(["--manifest", str(path)]) == 0
    assert "matches its known-good list (7 files on the list)" in capsys.readouterr().out


def test_fetch_asks_for_a_fresh_copy_and_reads_the_body(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"body"

    def urlopen(request, timeout):
        seen.update(url=request.full_url, agent=request.get_header("User-agent"), timeout=timeout)
        return Response()

    monkeypatch.setattr(checker.urllib.request, "urlopen", urlopen)
    assert checker.fetch("https://x.example/") == b"body"
    assert seen == {"url": "https://x.example/", "agent": checker.USER_AGENT, "timeout": checker.FETCH_TIMEOUT}
