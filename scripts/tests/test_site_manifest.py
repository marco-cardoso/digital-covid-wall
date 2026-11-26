"""Tests for building a site's known-good list (scripts/site_manifest.py)."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import site_manifest  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def site(tmp_path):
    (tmp_path / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "dist" / "index.html").write_bytes(b"<html></html>")
    (tmp_path / "dist" / "assets" / "app.js").write_bytes(b"run()")
    (tmp_path / "wall" / "tiles").mkdir(parents=True)
    (tmp_path / "wall" / "wall.json").write_bytes(b"{}")
    (tmp_path / "wall" / "tiles" / "0_0.jpg").write_bytes(b"jpg")
    (tmp_path / "wall" / ".DS_Store").write_bytes(b"junk")
    return tmp_path


def test_files_and_folders_are_mapped_to_keys_with_their_hashes(site):
    m = site_manifest.build(
        "dev", "https://dev.example.org/",
        [f"{site}/dist/index.html=index.html", f"{site}/dist/assets=assets", f"{site}/wall=wall"],
        excludes=[".DS_Store"], now=NOW,
    )
    assert m["site"] == "dev"
    assert m["url"] == "https://dev.example.org"
    assert m["recorded_at"] == "2026-11-26T12:00:00Z"
    assert m["deploying_until"] is None
    assert list(m["files"]) == ["assets/app.js", "index.html", "wall/tiles/0_0.jpg", "wall/wall.json"]
    assert m["files"]["assets/app.js"] == {
        "sha256": hashlib.sha256(b"run()").hexdigest(), "md5": hashlib.md5(b"run()").hexdigest(), "size": 5,
    }


def test_a_folder_can_go_at_the_root(site):
    m = site_manifest.build("prod", "https://example.org", [f"{site}/dist="], now=NOW)
    assert list(m["files"]) == ["assets/app.js", "index.html"]


def test_a_deploy_window_is_marked_when_asked(site):
    m = site_manifest.build("dev", "https://x", [f"{site}/dist="], deploying_minutes=30, now=NOW)
    assert m["deploying_until"] == "2026-11-26T12:30:00Z"


@pytest.mark.parametrize(
    "mappings, message",
    [
        (["{s}/nowhere=x"], "does not exist"),
        (["{s}/dist/index.html="], "a single file needs a key"),
        (["{s}/dist=", "{s}/dist/index.html=index.html"], "index.html is mapped twice"),
    ],
)
def test_mistakes_in_the_mapping_stop_it(site, mappings, message):
    with pytest.raises(SystemExit, match=message):
        site_manifest.build("dev", "https://x", [m.format(s=site) for m in mappings], now=NOW)


def test_the_command_line_writes_the_list(site, capsys):
    out = site / "manifest.json"
    assert site_manifest.main(["--site", "dev", "--url", "https://x", "--map", f"{site}/dist=",
                               "--deploying-minutes", "5", "--out", str(out)]) == 0
    assert len(json.loads(out.read_text())["files"]) == 2
    assert "Known-good list for dev: 2 files, deploy window to" in capsys.readouterr().out
